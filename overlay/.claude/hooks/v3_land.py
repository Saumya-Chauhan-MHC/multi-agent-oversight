#!/usr/bin/env python3
"""PostToolUse: the action happened, so anything queued about it can no longer be steered."""
import sys, json, os
sys.excepthook = lambda *a: sys.exit(0)
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
PROJ = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
sys.path.insert(0, PROJ)
try:
    from oversight.v3 import taskmodel as tmod, policy, filter as filt
    from oversight import align
except Exception:
    sys.exit(0)
tm = tmod.load(PROJ)
if not tmod.preferences(tm):
    sys.exit(0)
action = filt.action_text(data.get("tool_name"), data.get("tool_input"))
key = policy.cache_key(action, tmod.rules_signature(tm))[:8]
for b in policy._blocks(PROJ):
    for m in list(b["members"]):
        if m["rid"].startswith(key):
            policy.mark_landed(PROJ, m["rid"])
sys.exit(0)
