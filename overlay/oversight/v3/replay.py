#!/usr/bin/env python3
"""Offline eval: run a recorded trajectory back through the tool, decision by decision.

The point is to answer "would we have spoken here, and should we have" without re-running the
agent. Two rules make the result mean something:

  1. No lookahead. At decision i the three lists are rebuilt from events[:i] only, so the port
     registry and the dependency map hold what they held at the time, not what the run later
     revealed.
  2. The clock is the trajectory's own. The quiet window, the one-at-a-time queue and the hourly
     preempt are advanced by the recorded timestamps, so "shown" means shown then, not shown
     eventually.

Usage:
    python3 -m oversight.v3.replay TRAJECTORY.jsonl --model-dir DIR [--out results.jsonl]
                                  [--no-judge] [--limit N]
"""
import argparse, json, os, shutil, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from oversight.v3 import taskmodel as tmod, filter as filt, policy, judge3


def decisions(events):
    """The decision points: every PreToolUse the live gate would have seen, in order."""
    out = []
    for i, e in enumerate(events):
        if e.get("hook_event_name") != "PreToolUse":
            continue
        if e.get("tool_name") not in ("Bash", "Write", "Edit", "MultiEdit", "Task", "Agent"):
            continue
        out.append((i, e))
    return out


BASE_MS = 1_700_000_000_000      # a fixed epoch for trajectories that recorded no clock
SPACING_MS = 30_000              # and a plausible 30s between decisions


def briefs(events):
    """agent_id -> the brief it was spawned with.

    SubagentStart records an opaque id and nothing else, and the brief lives in the Agent call
    that preceded it, so the two are bound in spawn order. Without this the judge sees an id
    like a409a3221a2 and cannot tell which component agent is acting, so it falls back to the
    ownership rule and hedges: "if this agent is not the REST API agent". The live hook reads the
    brief from the parent record, so a replay that leaves it out scores a gap the tool does not
    have. Spawn always precedes the agent's own actions, so this breaks no lookahead rule.
    """
    pending, out = [], {}
    for e in events:
        if (e.get("hook_event_name") == "PreToolUse"
                and e.get("tool_name") in ("Task", "Agent")):
            ti = e.get("tool_input") or {}
            pending.append("%s\n%s" % (ti.get("description") or "", ti.get("prompt") or ""))
        elif e.get("ov_event") == "subagent_start" and e.get("agent_id"):
            out[e["agent_id"]] = pending.pop(0) if pending else ""
    return out


def _ts(e, n):
    """The recorded millisecond clock for this decision, or a synthetic one spaced evenly.

    A trajectory with no usable timestamps still has to exercise the quiet window and the
    hourly preempt, so the fallback is an even 30s per decision rather than zero: at zero
    every window comparison collapses and nothing is ever due.
    """
    for k in ("ts", "timestamp", "time", "at"):
        v = e.get(k)
        if isinstance(v, (int, float)) and v > 1e8:
            return int(v if v > 1e11 else v * 1000)
    return BASE_MS + n * SPACING_MS


def run(traj_path, model_dir, judge=True, limit=None, verbose=True, verdicts=None):
    events = [json.loads(l) for l in open(traj_path) if l.strip()]
    tm = tmod.load(model_dir)
    if not tmod.preferences(tm):
        raise SystemExit("no preferences in %s; run the extractor there first" % model_dir)
    rules_sig = tmod.rules_signature(tm)
    brief_of = briefs(events)

    prior = {}
    if verdicts:                                       # reuse judgements from an earlier replay
        for l in open(verdicts):
            if l.strip():
                r = json.loads(l)
                if r.get("verdict"):
                    prior[int(r["idx"])] = r

    proj = tempfile.mkdtemp(prefix="replay-")          # policy state for this replay only
    os.makedirs(os.path.join(proj, "oversight"), exist_ok=True)
    results, clock0 = [], None
    try:
        for n, (i, e) in enumerate(decisions(events)):
            if limit and n >= limit:
                break
            prefix = events[:i]                         # rule 1: no lookahead
            at = _ts(e, n)
            who = e.get("agent_id") or "orchestrator"
            tool, ti = e.get("tool_name"), e.get("tool_input") or {}

            rec = dict(idx=n, event_idx=i, at=at, agent=who, tool=tool,
                       action=filt.action_text(tool, ti)[:400])
            trigger = filt.check(tm, prefix, tool, ti, who)
            if not trigger:
                rec.update(filtered=True, trigger=None, band="free", shown=False)
                results.append(rec)
                continue

            rec.update(filtered=False, trigger=trigger.get("reason"), risk=trigger.get("risk"),
                       dependents=trigger.get("dependents") or [], owner=trigger.get("owner"))
            key = policy.cache_key(rec["action"], rules_sig, who)
            cached = policy.cache_get(proj, key)
            if cached and cached.get("band") != "hold":
                rec.update(band="cached", cached_as=cached.get("band"), shown=False,
                           verdict=cached.get("verdict"), confidence=cached.get("confidence"))
                results.append(rec)
                continue

            if n in prior:
                v = {k: prior[n].get(k) for k in ("verdict", "covered", "confidence", "prefs",
                                                  "metric", "evidence", "consequence",
                                                  "correction", "source")}
            elif judge:
                v = judge3.judge(tm, rec["action"], trigger, brief_of.get(who, "")[:2500],
                                 {"name": who})
            else:                                       # structure only, for a dry run
                v = dict(verdict="departs" if trigger.get("risk") else "fits", covered=True,
                         confidence=0.9 if trigger.get("risk") else 0.4, evidence=[],
                         prefs=[], metric="tests" if trigger.get("risk") else None)
            band = policy.band(v, proj, trigger=rec["trigger"])
            rec.update(band=band, **{k: v.get(k) for k in
                                     ("verdict", "confidence", "prefs", "metric", "evidence",
                                      "consequence", "correction", "source")})
            policy.cache_put(proj, key, dict(band=band, verdict=v.get("verdict"),
                                             confidence=v.get("confidence")))
            if band == "silent":
                rec.update(shown=False, why_not="band_silent")
                results.append(rec)
                continue

            flag = dict(rid="r%d" % n, ts=at, agent=who, tool=tool, action=rec["action"],
                        trigger=rec["trigger"], risk=rec.get("risk"),
                        dependents=rec.get("dependents") or [], band=band,
                        **{k: v.get(k) for k in ("verdict", "confidence", "prefs", "reqs",
                                                 "grounds", "metric", "evidence", "consequence",
                                                 "correction")})
            block = policy.enqueue(proj, flag)
            due = policy.due(proj, at=at)
            # Both bands are delivered now, so both count as shown. Before the check band had an
            # output channel this line read `band == "hold"`, and it was faithful to the hook --
            # which is how the replay came to score surfacing 0.00 on a recording where the band
            # scorer said the tool had put both opportunities in the right band. The replay was
            # right and the hook was wrong.
            shown = bool(band in ("hold", "check") and due is not None
                         and due["label"] == block["label"])
            rec.update(shown=shown, block=block["label"],
                       block_size=len(block["members"]),
                       preempted=bool(due and due.get("preempted")) if shown else False)
            if shown and due.get("preempted"):
                policy.consume_preempt(proj, at=at)
            if shown:
                policy.mark_shown(proj, flag["rid"], at=at)
            if not shown:
                rec["why_not"] = ("band_check" if band == "check"
                                  else "queued_behind_or_quiet_window")
            results.append(rec)
            if verbose and (shown or band != "free"):
                print("  %3d %-12s %-7s %-6s %s" % (n, rec["trigger"] or "-", band,
                                                    "SHOWN" if shown else "", rec["action"][:52]))
    finally:
        shutil.rmtree(proj, ignore_errors=True)
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("trajectory")
    ap.add_argument("--model-dir", required=True)
    ap.add_argument("--out")
    ap.add_argument("--no-judge", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--verdicts", help="an earlier results.jsonl, to replay the policy only")
    a = ap.parse_args()
    res = run(a.trajectory, a.model_dir, judge=not a.no_judge, limit=a.limit,
              verdicts=a.verdicts)
    if a.out:
        with open(a.out, "w") as fh:
            for r in res:
                fh.write(json.dumps(r) + "\n")
    free = sum(1 for r in res if r.get("filtered"))
    judged = sum(1 for r in res if not r.get("filtered") and r.get("band") not in ("cached",))
    print("\n%d decisions: %d free, %d cached, %d judged, %d shown"
          % (len(res), free, sum(1 for r in res if r.get("band") == "cached"), judged,
             sum(1 for r in res if r.get("shown"))))


if __name__ == "__main__":
    main()
