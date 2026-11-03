"""Build step 2 check: one payload through v6_gate directly and through clock_wrap, same history."""
import json, os, subprocess, sys, tempfile
from adapter_v6 import V6
T = "../conduit/trajectory_rw4/events.jsonl"; IDX = int(sys.argv[1])
lines = open(T).read().splitlines(); root = json.loads(lines[0])["cwd"]
res = {}
for mode in ("direct", "wrapped"):
    w = tempfile.mkdtemp(); os.rmdir(w); a = V6()
    a.setup(w, "../conduit/PROMPT.md", dict(quiet_s=120, judge_model="claude-sonnet-5", rules_file="../conduit/rules_conduit_fixed.json"))
    h = os.path.join(w, "oversight", "events.jsonl")
    open(h, "a").write("\n".join(l.replace(root, w) for l in lines[:IDX]) + "\n")
    payload = lines[IDX].replace(root, w)
    gate = os.path.join(w, ".claude", "hooks", "v6_gate.py")
    cmd = [sys.executable, gate] if mode == "direct" else [sys.executable, os.path.abspath("clock_wrap.py"), gate]
    env = dict(os.environ, CLAUDE_PROJECT_DIR=w, OV_REPLAY_NOW=str(json.loads(lines[IDX])["ov_ts"] / 1000), OV_QUIET_S="120")
    n0 = len(open(h).readlines())
    p = subprocess.run(cmd, input=payload, capture_output=True, text=True, env=env, cwd=w)
    new = [json.loads(l) for l in open(h).readlines()[n0:]]
    res[mode] = [{k: e.get(k) for k in ("ov_event", "kind", "risk", "reason", "detail", "departs", "pid")} for e in new]
    print(mode, json.dumps(res[mode]), "| shown" if "permissionDecision" in p.stdout else "| not shown")
f = lambda r: [{k: v for k, v in e.items() if k not in ("departs", "pid")} for e in r]
print("detector output identical:", f(res["direct"]) == f(res["wrapped"]))
