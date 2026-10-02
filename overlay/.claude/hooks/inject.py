#!/usr/bin/env python3
"""SessionStart: put the user's lines into the orchestrator's first prompt (SSOT B2, I0).

Silent to the user by design: the agent is told what the user wants, not how closely it is watched,
so q4 and q5 never reach it.
"""
import sys, json, os
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
proj = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
sys.path.insert(0, os.path.join(proj, "oversight"))
try:
    import memory
    text = memory.i0()
except Exception:
    text = ""
if text:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                             "additionalContext": text}}))
else:
    # No lines means the gate has nothing to align to and will stay silent all session. Say so, or
    # the tool looks like it is working when it is doing nothing at all.
    print(json.dumps({"systemMessage":
                      "oversight: no lines yet, so nothing will be judged this session.\n"
                      "  run  python3 oversight/ctl.py init  in another terminal, then restart me."}))
