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
