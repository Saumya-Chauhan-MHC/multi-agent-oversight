#!/bin/bash
# Launch the agent under study on the prepared task (run ./setup.sh first).
# The task prompt is PROMPT.md verbatim. Open the viewer in another window:
#   cd task && python3 oversight/viewer/serve.py   ->  http://localhost:4173
HERE=$(cd "$(dirname "$0")" && pwd)
cd "$HERE/task" || { echo "no task/ folder; run ./setup.sh <instance_id> first" >&2; exit 1; }
printf '\033]0;agent under study\007'
exec claude --permission-mode acceptEdits "$(cat PROMPT.md)"
