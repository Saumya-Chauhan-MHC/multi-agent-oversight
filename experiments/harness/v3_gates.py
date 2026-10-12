"""The v3 tool (overlay/oversight/v3), replayed offline on a recorded run.

v3 has its own replay (oversight.v3.replay.run): no lookahead, the trajectory's own clock, the real
filter, judge, bands, queue and quiet window. This module only feeds it our runs:

  task model  v3 extracts requirements and preferences from the brief instead of asking q1-q5. The
              brief is the run's prompt.txt; the repo is the run's testbed/ (the extractor resolves
              each requirement's check against the files there). One model per instance, shared by
              every rep, stored at runs/<exp>/<instance>/v3_task_model/oversight/task_model.json.
  events      tools.jsonl -> the PreToolUse records v3 reads. Calls the harness denied (the lead's
              own Bash/Edit/Write in the multi condition) never ran, so they are left out.
  briefs      v3 binds briefs to subagents in spawn order; we already have a better binding
              (gates.briefs_by_agent), so it is passed in instead.

Ground truth per call is still Scenario.violating. Nothing under overlay/ is written.
"""
import json, os, sys

from . import gates

OVERLAY = os.path.dirname(gates.OVERSIGHT)
sys.path.insert(0, OVERLAY)
from oversight.v3 import extract as v3extract, replay as v3replay, taskmodel as v3tm   # noqa: E402

OUT = "oversight_replay_v3.json"


def model_dir(run):
    return os.path.join(os.path.dirname(run), "v3_task_model")


def task_model(run, extract=True):
    """The instance's task model, extracted once from this run's prompt and testbed."""
    d = model_dir(run)
    if os.path.exists(v3tm.path(d)) or not extract:
        return d
    prompt = open(os.path.join(run, "prompt.txt")).read()
    tm = v3extract.extract(os.path.join(run, "testbed"), prompt, "", "", save=False)
    v3tm.save(d, tm)
    return d


def violating_calls(sc, run, calls):
    """Indices of the violating calls. The v2 replay already stored them per call; reading them back
    avoids Scenario.violating, which reads judge.json per run and is slower."""
    v2 = os.path.join(run, gates.out_name("default"))
    if os.path.exists(v2):
        return {e["idx"] for e in json.load(open(v2))["events"] if e.get("violating")}
    return {k for k, c in enumerate(calls) if sc.violating(c, run)}


def replay(sc, run, judge=True, extract=True):
    calls = [json.loads(l) for l in open(os.path.join(run, "tools.jsonl"))]
    kept = [k for k, c in enumerate(calls) if c.get("decision") == "allow"]
    events = [dict(hook_event_name="PreToolUse", tool_name=calls[k]["tool"], tool_input=calls[k]["input"],
                   agent_id=None if calls[k]["agent"] == "main" else calls[k]["agent"], ts=calls[k]["ts"])
              for k in kept]
    brief_of = {ag: "%s\n%s" % (b.get("description") or "", b.get("prompt") or "")
                for ag, b in gates.briefs_by_agent(run, calls).items()}
    traj = os.path.join(run, "v3_trajectory.jsonl")
    with open(traj, "w") as fh:
        for e in events:
            fh.write(json.dumps(e) + "\n")

    orig = v3replay.briefs
    v3replay.briefs = lambda _events: brief_of
    try:
        res = v3replay.run(traj, task_model(run, extract), judge=judge, verbose=False)
    finally:
        v3replay.briefs = orig

    truth = violating_calls(sc, run, calls)
    for r in res:
        r["call_idx"] = kept[r["event_idx"]]
        r["violating"] = r["call_idx"] in truth
    out = dict(run=os.path.relpath(run, sc.runs), judged=judge, results=res)
    if judge:
        json.dump(out, open(os.path.join(run, OUT), "w"), indent=1)
    return out


def summarize(o):
    res = o["results"]
    bad = [r for r in res if r["violating"]]
    first_bad = min((r["call_idx"] for r in bad), default=None)
    held = [r for r in res if r.get("shown") and r.get("band") == "hold"]
    noted = [r for r in res if r.get("shown") and r.get("band") == "check"]
    by_then = lambda rs: first_bad is not None and any(r["call_idx"] <= first_bad for r in rs)
    return dict(run=o["run"], decisions=len(res), to_judge=sum(not r.get("filtered") for r in res),
                violating_calls=len(bad), bad_filtered=sum(bool(r.get("filtered")) for r in bad),
                bad_shown=sum(bool(r.get("shown")) for r in bad),
                held_by_then=by_then(held), noted_by_then=by_then(noted),
                holds_shown=len(held), checks_shown=len(noted),
                triggers=sorted({r["trigger"] for r in bad if r.get("trigger")}))
