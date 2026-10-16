#!/usr/bin/env python3
"""Check an arm before its numbers are believed.

Both bugs found so far were caught by reading code, not by anything failing. A dropped Task
judgement (fail-open swallowed a NameError, so all five subagent spawns were judged and thrown
away) and a grader that hardcoded `python -m app` when the task says `bash start.sh`, which would
have scored the control arm zero for a legal architectural choice. Both silently favoured a
particular answer and neither made a sound.

So the checks here are about the harness, not the tool: is the grader booting the way the task
says to, are the hooks actually wired, and do the judgements reconcile against the tool calls that
were recorded. Anything that fails is a reason to fix and rerun, not to annotate the result.

  python3 preflight.py <arm-dir> [<arm-dir> ...]
"""
import json, os, re, sys

TASK = "/tmp/stripe_task"


def events(d):
    p = os.path.join(d, "oversight", "events.jsonl")
    if not os.path.exists(p):
        return []
    out = []
    for ln in open(p, errors="ignore"):
        try:
            out.append(json.loads(ln))
        except Exception:
            pass
    return out


def check(arm):
    d = os.path.abspath(arm)
    name = os.path.basename(d)
    fails, warns = [], []
    ev = events(d)

    # 1. the boot contract. instruction.md says `bash start.sh` runs the service, and the internal
    #    architecture is explicitly open, so the grader must not assume a layout.
    sh = os.path.join(d, "start.sh")
    if not os.path.exists(sh):
        fails.append("no start.sh: the task's boot contract is `bash start.sh`")
    else:
        body = open(sh, errors="ignore").read()
        if "raise SystemExit" in body or not re.search(r"exec |uvicorn|python", body):
            fails.append("start.sh looks like the untouched skeleton")

    # 2. hooks wired. A tool arm whose gate is not in settings.json is a control arm wearing a
    #    costume, and it reads as "the tool did nothing" rather than "the tool was absent".
    sp = os.path.join(d, ".claude", "settings.json")
    wired = set()
    if os.path.exists(sp):
        s = json.load(open(sp))
        for evname, groups in (s.get("hooks") or {}).items():
            for g in groups:
                for h in g.get("hooks", []):
                    wired.add(os.path.basename(h.get("command", "").split()[-1].strip('"')))
    has_gate = bool(wired & {"v3_gate.py", "v5_gate.py"})
    judged = [e for e in ev if e.get("ov_event") in ("v3_judgement", "v5_judgement")]
    if judged and not has_gate:
        fails.append("judgements recorded but no gate wired in settings.json")
    if has_gate and "inbox.py" not in wired:
        fails.append("gate wired but inbox.py is not: relayed corrections are never delivered")
    for hk in sorted(wired):
        p = os.path.join(d, ".claude", "hooks", hk)
        if hk.endswith(".py") and not os.path.exists(p):
            fails.append("settings.json wires %s but the file is not in the arm" % hk)

    # 3. judgements reconcile against tool calls. This is the check that would have caught the
    #    dropped Task judgement: 44 judgements recorded, 0 of them Task, against 5 spawns.
    if has_gate:
        watched = {"Bash", "Write", "Edit", "MultiEdit", "Task", "Agent"}
        calls, jud = {}, {}
        for e in ev:
            if e.get("ov_event") == "pre_tool" and e.get("tool_name") in watched:
                calls[e["tool_name"]] = calls.get(e["tool_name"], 0) + 1
            elif e.get("ov_event") in ("v3_judgement", "v5_judgement"):
                t = e.get("tool") or "?"
                jud[t] = jud.get(t, 0) + 1
        spawns = sum(calls.get(t, 0) for t in ("Task", "Agent"))
        spawn_j = sum(jud.get(t, 0) for t in ("Task", "Agent"))
        if spawns and not spawn_j:
            fails.append("%d spawn calls and 0 spawn judgements: judgements are being dropped"
                         % spawns)
        for t, n in sorted(calls.items()):
            if n and not jud.get(t) and t not in ("Task", "Agent"):
                warns.append("%d %s calls, 0 judged (may be legitimate: read-only skip)" % (n, t))

    # 4. a crash log means the fail-open handler ate something
    for tmp in (os.environ.get("TMPDIR", "/tmp"), "/tmp"):
        for v in ("v3", "v4", "v5"):
            p = os.path.join(tmp, "oversight-%s-errors.log" % v)
            if os.path.exists(p) and os.path.getsize(p):
                warns.append("%s has %d bytes: the fail-open handler swallowed something"
                             % (p, os.path.getsize(p)))

    # 5. the arm actually produced work
    py = sum(len(fs) for _, _, fs in
             [(a, b, [f for f in c if f.endswith(".py")]) for a, b, c in os.walk(d)
              if ".claude" not in a and "oversight" not in a and "__pycache__" not in a])
    if py < 3:
        fails.append("only %d python files written: the arm may not have run" % py)

    print("%-14s %s" % (name, "OK" if not fails else "FAIL"))
    for f in fails:
        print("   FAIL  %s" % f)
    for w in warns:
        print("   warn  %s" % w)
    return not fails


if __name__ == "__main__":
    ok = all([check(a) for a in sys.argv[1:]])
    sys.exit(0 if ok else 1)
