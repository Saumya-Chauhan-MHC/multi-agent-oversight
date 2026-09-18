#!/usr/bin/env python3
"""Session time cap. Ports the two time-related behaviours of the official ProgramBench agent
config (mini-swe-agent programbench.yaml) into Claude Code hooks:

  official: 10 min before the wall-time limit every observation carries an IMPORTANT block
            ("You are running low on time ... write AGENT_REPORT.md ... hand off to the next agent");
            at the limit the run is cut off.
  here:     `cap.py warn` (PostToolUse + UserPromptSubmit) injects that same text as
            additionalContext when < 10 min remain (or < a third of a short cap);
            `cap.py gate` (PreToolUse, all tools) denies every tool once the cap is reached, with a
            reason telling the agent to stop. You then exit Claude Code and the session is over.

The cap length is oversight/cap_minutes (written by setup.sh, default 90; 0 disables).
The timer starts at each launch / resume (record.py writes oversight/cap_start_<n>.txt).
"""
import sys, json, os, time

mode = sys.argv[1] if len(sys.argv) > 1 else "gate"
try:
    data = json.load(sys.stdin)
except Exception:
    data = {}
root = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
out = os.path.join(root, "oversight")

def read_int(p, default):
    try:
        return int(open(p).read().strip())
    except Exception:
        return default

cap_min = read_int(os.path.join(out, "cap_minutes"), 90)
no = read_int(os.path.join(out, "session_no.txt"), 1)
start = read_int(os.path.join(out, f"cap_start_{no}.txt"), int(time.time()))
# time spent paused waiting for a human decision (gate.py) is not charged to the agent
start += read_int(os.path.join(out, f"paused_{no}.txt"), 0)
if cap_min <= 0:
    sys.exit(0)
remaining = cap_min * 60 - (int(time.time()) - start)

LOW_TIME = (
    "<IMPORTANT>\nYou are running low on time. You have approximately {m} minutes remaining before "
    "this session ends.\nPlease wrap up your work now:\n"
    "1. Ensure your solution compiles and produces an executable (it's ok if it is still missing functionality)\n"
    "2. If there are any steps left to do, or limitations that you are aware of, please write them to a "
    "document \"AGENT_REPORT.md\". Focus on handing off to the next agent, i.e., focus on clearly describing "
    "the problems and any todo items that are left over.\n</IMPORTANT>"
)

if mode == "gate":
    if remaining <= 0:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                f"Session time cap ({cap_min} min) reached. Do not run more tools. "
                "Summarise the state of the work in one short message and stop; the task will be "
                "continued in a later session.")}}))
    sys.exit(0)

# low-time window: 10 min, or a third of the cap for short caps (a 15-min run warns at 10 min)
warn_s = min(600, cap_min * 60 // 3)
if mode == "warn" and 0 < remaining < warn_s:
    ev = data.get("hook_event_name", "PostToolUse")
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": ev,
        "additionalContext": LOW_TIME.format(m=max(1, remaining // 60))}}))
sys.exit(0)
