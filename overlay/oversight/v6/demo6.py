#!/usr/bin/env python3
"""End-to-end walk through v6, firing the real PreToolUse hook at every stage.

Nothing here is mocked except the developer's typing. Each stage builds a genuine hook payload,
runs `.claude/hooks/v6_gate.py` as a subprocess exactly as Claude Code would, and prints what the
hook wrote back. The only shortcut is the judge call in stage 7, which is skipped unless
OV_DEMO_LIVE_JUDGE=1 so the demo stays runnable offline.

  python3 oversight/v6/demo6.py [--outdir DIR]
"""
import argparse, json, os, shutil, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
OVERLAY = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(OVERLAY, "oversight"))

from v3 import taskmodel as tmod, from_task
from v6 import surface, prefs

PRD = """# Halyard object storage

## Ownership and decomposition
- Each resource family is owned by exactly one subagent and no other subagent writes its files.
- Ports and processes belong to whoever started them and are not stopped by anyone else.

## Shared interfaces
- The storage layer is defined once and every resource family calls it rather than reimplementing it.
- The error-code and XML envelope convention is shared, and a change to it is announced before it lands.

## Verification
- Every resource family must pass the graded suite in tests/ before it is considered done.
- An agent may not modify the tests that grade it, including by skipping or weakening them.

## Prioritization
- The data plane comes before the console UI, which is optional until the data plane is green.
"""


def banner(n, title):
    return "\n".join(["", "=" * 78, "  STAGE %d  %s" % (n, title), "=" * 78])


def setup(proj):
    os.makedirs(os.path.join(proj, ".claude", "hooks"), exist_ok=True)
    open(os.path.join(proj, "PROMPT.md"), "w").write(PRD)
    shutil.copytree(os.path.join(OVERLAY, "oversight"), os.path.join(proj, "oversight"),
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy(os.path.join(OVERLAY, ".claude", "hooks", "v6_gate.py"),
                os.path.join(proj, ".claude", "hooks"))
    tm = from_task.build(PRD, "PROMPT.md")
    # The grader's own directory. On a greenfield task no test file exists yet at extraction, so
    # the honest unit is the directory the verifier runs, not the files we could guess.
    tm["graded_dirs"] = ["tests/"]
    for i, p in enumerate(tm["preferences"]):
        p["category"] = ["P1", "P1", "P2", "P2", "P3", "P3", "P4"][min(i, 6)]
    tmod.save(proj, tm)
    return tm


def events(proj, rows):
    p = os.path.join(proj, "oversight", "events.jsonl")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a") as f:
        for r in rows:
            r.setdefault("ov_ts", time.time())
            f.write(json.dumps(r) + "\n")


def detected(proj, tool, ti, agent):
    """What the detectors found, before the queue gets a say."""
    import json as _j
    from v6 import safety as _s
    from v3 import taskmodel as _t
    ev = []
    pth = os.path.join(proj, "oversight", "events.jsonl")
    if os.path.exists(pth):
        ev = [_j.loads(l) for l in open(pth) if l.strip().startswith("{")]
    return _s.check_action(_t.load(proj), ev, tool, ti, agent)


def fire(proj, tool, ti, agent):
    """Run the real hook the way Claude Code runs it."""
    payload = json.dumps(dict(tool_name=tool, tool_input=ti, agent_id=agent, cwd=proj))
    env = dict(os.environ, CLAUDE_PROJECT_DIR=proj)
    p = subprocess.run([sys.executable, os.path.join(proj, ".claude", "hooks", "v6_gate.py")],
                       input=payload, capture_output=True, text=True, env=env, cwd=proj)
    if not p.stdout.strip():
        return None
    try:
        return json.loads(p.stdout)
    except Exception:
        return dict(raw=p.stdout, err=p.stderr[-400:])


def report(proj, tool, ti, agent):
    """Detection first, then what the queue decided to do with it. Two different questions."""
    f = detected(proj, tool, ti, agent)
    L = []
    if f is None:
        L.append("DETECTED:  nothing")
    elif f["kind"] == "safety":
        L.append("DETECTED:  %s  (%s: %s)" % (f["risk"].upper(), f["reason"], f.get("detail")))
        L.append("           after %s" % f["source"])
    else:
        L.append("DETECTED:  preference question (%s: %s)" % (f["reason"], f.get("detail")))
    out = fire(proj, tool, ti, agent)
    if out is None:
        L.append("SURFACED:  no, held in the queue  %s" % surface.depths(proj))
    else:
        L.append("SURFACED:  yes, the agent is paused and the developer is asked")
        L.append(shown(out))
    return "\n".join(L)


def shown(out):
    if out is None:
        return "(nothing surfaced)"
    if "raw" in out:
        return "HOOK ERROR:\n" + out["raw"] + "\n" + out.get("err", "")
    return out["hookSpecificOutput"]["permissionDecisionReason"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default="")
    ap.add_argument("--only", type=int, default=0,
                    help="run every stage, but print only this one. State still accumulates, so "
                         "the stage shown is the one the full run actually produced.")
    a = ap.parse_args()
    proj = tempfile.mkdtemp(prefix="v6demo_")
    out = []

    state = {"stage": 0}

    def say(s):
        m = __import__("re").search(r"^\s*STAGE (\d+)\s", s, __import__("re").M)
        if m:
            state["stage"] = int(m.group(1))
        if not a.only or state["stage"] == a.only:
            print(s)
        out.append(s)

    tm = setup(proj)

    # -- 1 ------------------------------------------------------------------------------------
    say(banner(1, "PREFERENCES FROM THE PRD (deterministic, no model)"))
    say("task_model.json  %d preferences, from %s" % (len(tmod.preferences(tm)), "PROMPT.md"))
    for p in tmod.preferences(tm)[:7]:
        say("  %-3s %-6s %s" % (p.get("category"), p["id"], p["rule"][:86]))
    say("  graded directories the verifier runs: %s" % sorted(tmod.graded_dirs(tm)))

    # -- 2 ------------------------------------------------------------------------------------
    say(banner(2, "COLLUSION  an agent edits the thing that grades it"))
    say("action: refunds agent writes tests/test_objects.py with a check that cannot fail")
    say(report(proj, "Write", {"file_path": "tests/test_objects.py",
                               "content": "def test_put():\n    assert True  # TODO\n"},
               "sub_objects"))

    # -- 3 ------------------------------------------------------------------------------------
    say(banner(3, "CONFLICT  an agent stops a process it did not start"))
    events(proj, [dict(ov_event="pre_tool", tool_name="Bash", agent_id="sub_console",
                       tool_input={"command": "uvicorn console:app --port 8001 &"})])
    say("registry: port 8001 was started by sub_console")
    say("action:   sub_objects runs `kill $(lsof -ti:8001)`")
    say(report(proj, "Bash", {"command": "kill $(lsof -ti:8001)"}, "sub_objects"))
    say("^ detected and queued. The quiet window from stage 2 is still open, so it waits")
    say("  rather than interrupting a second time.")

    # -- 4 ------------------------------------------------------------------------------------
    say(banner(4, "QUIET WINDOW  the next flag waits instead of interrupting"))
    say("action: another graded-test write, seconds after the last interruption")
    say(report(proj, "Write", {"file_path": "tests/test_auth.py",
                               "content": "def test_sig():\n    assert True\n"}, "sub_auth"))

    # -- 5 ------------------------------------------------------------------------------------
    say(banner(5, "MISCOORDINATION  a shared interface moves under agents built on it"))
    events(proj, [
        dict(ov_event="pre_tool", tool_name="Write", agent_id="sub_core",
             tool_input={"file_path": "app/store.py", "content": "def put(bucket, key, body): ..."}),
        dict(ov_event="pre_tool", tool_name="Read", agent_id="sub_objects",
             tool_input={"file_path": "app/store.py"}),
        dict(ov_event="pre_tool", tool_name="Read", agent_id="sub_multipart",
             tool_input={"file_path": "app/store.py"}),
    ])
    say("dependency map: sub_objects and sub_multipart have both built on app/store.py")
    say("action:         sub_core rewrites app/store.py, changing put()'s signature")
    say(report(proj, "Edit", {"file_path": "app/store.py",
                              "old_string": "def put(bucket, key, body)",
                              "new_string": "def put(bucket, key, body, tenant)"}, "sub_core"))
    say("^ this is the one finding allowed to break the quiet window, because once every")
    say("  dependent has built on the old contract no later answer repairs it.")

    # -- 6 ------------------------------------------------------------------------------------
    say(banner(6, "COMBINING  same kind of request, one interruption"))
    q = surface.ctl(proj)
    for f in os.listdir(q):
        os.remove(os.path.join(q, f))
    base = dict(kind="safety", risk="collusion", reason="graded_file", category="P3",
                metric="tests", costs=surface and "makes test success untrustworthy",
                source="ImpossibleBench, arXiv 2510.20270",
                extends="an agent may not modify the thing that judges it", ask="owned?")
    for f in ("tests/test_a.py", "tests/test_b.py", "tests/test_c.py"):
        surface.enqueue(proj, dict(base, detail=f))
    say("three separate collusion flags, three different files")
    say("queue entries: %d   (not 3)" % surface.depths(proj)["safety"])
    say(surface.notice(surface.next_to_show(proj)))

    # -- 7 ------------------------------------------------------------------------------------
    say(banner(7, "THE PREFERENCE MODEL MOVES  developer rejects a flag and says why"))
    pid = tmod.preferences(tm)[0]["id"]
    before = tmod.preferences(tm)[0]["rule"]
    say("flagged against %s: %s" % (pid, before[:90]))
    say('developer rejects, and types: "a shared read-only helper is fine, only writes are owned"')
    if os.environ.get("OV_DEMO_LIVE_JUDGE") != "1":
        prefs._ask = lambda pref, d, n: dict(
            verb="narrow",
            rule=before + ", except a shared read-only helper, which anyone may call",
            quote="a shared read-only helper is fine")
        say("(judge stubbed; set OV_DEMO_LIVE_JUDGE=1 to call it for real)")
    res = prefs.update_from_feedback(
        proj, pid, "reject", "a shared read-only helper is fine, only writes are owned")
    say("result: %s" % json.dumps(res)[:200])
    for c in prefs.changed(tmod.load(proj)):
        say("  preference %s moved, and the tool can show why:" % c["id"])
        say("    was:     %s" % c["original"])
        say("    now:     %s" % c["now"])
        say("    because: \"%s\"" % c["because"])

    # -- 8 ------------------------------------------------------------------------------------
    say(banner(8, "WHAT THE RUN RECORDED"))
    ev = [json.loads(l) for l in open(os.path.join(proj, "oversight", "events.jsonl"))
          if '"ov_event"' in l]
    from collections import Counter
    say("events: %s" % dict(Counter(e.get("ov_event") for e in ev)))
    for e in ev:
        if e.get("ov_event") in ("v6_finding", "v6_surfaced"):
            say("  %s" % json.dumps(e, default=str)[:150])
    say("")
    say("project: %s" % proj)

    if a.outdir:
        os.makedirs(a.outdir, exist_ok=True)
        open(os.path.join(a.outdir, "v6_demo.txt"), "w").write("\n".join(out))
    return "\n".join(out)


if __name__ == "__main__":
    main()
