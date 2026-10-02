#!/usr/bin/env python3
"""SubagentStop: count what the user has not seen, and print the catch-up line at a natural pause.

A subagent finishing is the boundary the SSOT names, and it is also the cheapest moment to interrupt
a user: the work has a seam there. Nothing is paused by this hook.
"""
import sys, json, os
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
proj = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
sys.path.insert(0, os.path.join(proj, "oversight"))
try:
    import memory, align
except Exception:
    sys.exit(0)

st, c = memory.settings(), align.counters(proj)
total, parts = align.outdatedness(proj, st)
c["unseen_files"] = parts["unseen_files"]
align.save_counters(proj, c)

threshold = int(st.get("catchup_threshold", 5))
if total < threshold or (align.now_ms() - c.get("last_catchup_ts", 0)) < 60000:
    sys.exit(0)

mins = max(0, int((align.now_ms() - c.get("last_look_ts", align.now_ms())) / 60000))
written = parts["unseen_files"]
msg = "\n".join([
    "oversight catch up?   since your last look (%d min)" % mins,
    "  %d departures from what you said, not surfaced" % c.get("flags_unanswered", 0),
    "  %d checks you did not answer" % c.get("checks_unanswered", 0),
    "  %d files written in nodes you have not opened" % written,
    "  open the graph   http://localhost:4173/?since=last-look",
    "  %d subagents finished while you were away" % parts["finished"],
    "  outdatedness %d, your threshold is %d . nothing is paused" % (total, threshold),
])
align.queue_notice(proj, msg)
c["last_catchup_ts"] = align.now_ms()        # stamped only once the line is safely queued, so a
align.save_counters(proj, c)                 # failure here does not silently burn the interval   # SubagentStop output is never shown; the next
print(json.dumps({"systemMessage": msg}))      # PostToolUse hook prints it
