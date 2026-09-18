#!/usr/bin/env python3
"""Instruction delivery (PostToolUse).

A human can address one running agent: `python3 oversight/ctl.py tell <node> "<text>"` or the
viewer's "Send instruction". The message waits in oversight/control/inbox/<agent>.jsonl and is
injected into that agent's context on its next tool call, as additionalContext on the tool result.
Only the addressed agent sees it. Delivery is recorded.
"""
import sys, json, os, re, time

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
root = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
ov = os.path.join(root, "oversight")
key = re.sub(r"[^\w.-]", "_", data.get("agent_id") or "main")
p = os.path.join(ov, "control", "inbox", f"{key}.jsonl")
if not os.path.exists(p):
    sys.exit(0)
dp = p + ".delivered"
done = set(open(dp).read().split()) if os.path.exists(dp) else set()
msgs = []
for ln in open(p):
    try:
        m = json.loads(ln)
    except Exception:
        continue
    if m.get("id") not in done:
        msgs.append(m)
if not msgs:
    sys.exit(0)
ctx = "\n\n".join("<human_overseer_message>\n" + m["text"] + "\n</human_overseer_message>" for m in msgs)
ctx = ("A human overseeing this task sent you the following. It takes priority over your current plan "
       "where they conflict.\n\n" + ctx)
print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": ctx}}))
with open(dp, "a") as f:
    f.write("".join(m["id"] + "\n" for m in msgs))
try:
    no = int(open(os.path.join(ov, "session_no.txt")).read().strip())
except Exception:
    no = 1
with open(os.path.join(ov, "events.jsonl"), "a") as f:
    f.write(json.dumps(dict(ov_event="instruction_delivered", ov_ts=int(time.time() * 1000),
                            ov_session_no=no, session_id=data.get("session_id", "control"),
                            agent_id=data.get("agent_id"), inbox_ids=[m["id"] for m in msgs],
                            text=[m["text"][:300] for m in msgs])) + "\n")
sys.exit(0)
