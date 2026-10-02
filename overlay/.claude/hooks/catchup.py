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

# unseen files: everything written since the last look, in nodes the user has not opened
written = 0
last = c.get("last_look_ts", 0)
seen = set(c.get("seen_nodes") or [])
for e in align.load_events(proj):
    if e.get("ov_ts", 0) <= last or e.get("ov_event") != "pre_tool":
        continue
    if e.get("tool_name") in ("Write", "Edit", "MultiEdit") and (e.get("agent_id") or "orchestrator") not in seen:
        written += 1
c["unseen_files"] = written
align.save_counters(proj, c)

unseen_points = written // 10
total = (c.get("flags_unanswered", 0) + c.get("checks_unanswered", 0)
         + 2 * c.get("repeat_flags", 0) + unseen_points)
threshold = int(st.get("catchup_threshold", 5))
if total < threshold or (align.now_ms() - c.get("last_catchup_ts", 0)) < 60000:
    sys.exit(0)

c["last_catchup_ts"] = align.now_ms()
align.save_counters(proj, c)
mins = max(0, int((align.now_ms() - c.get("last_look_ts", align.now_ms())) / 60000))
msg = "\n".join([
    "oversight catch up?   since your last look (%d min)" % mins,
    "  %d departures from what you said, not surfaced" % c.get("flags_unanswered", 0),
    "  %d checks you did not answer" % c.get("checks_unanswered", 0),
    "  %d files written in nodes you have not opened" % written,
    "  open the graph   http://localhost:4173/?since=last-look",
    "  outdatedness %d, your threshold is %d . nothing is paused" % (total, threshold),
])
print(json.dumps({"systemMessage": msg}))
