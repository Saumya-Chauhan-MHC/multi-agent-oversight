#!/usr/bin/env bash
# Live interactive run of delegation_laundering with the v3 oversight tool installed.
#   ./live_v3.sh                                  # django__django-16032, rep 0
#   ./live_v3.sh django__django-12273 1           # another instance / rep
# The task model is the one the v3 replay used for that instance (runs/sonnet45_plain/<inst>/v3_task_model).
# End the session with /exit; scoring follows. Results: delegation_laundering/runs/live_v3/<inst>/multi-<rep>/
set -euo pipefail
cd "$(dirname "$0")"

INST="${1:-django__django-16032}"
REP="${2:-0}"
TM="delegation_laundering/runs/sonnet45_plain/$INST/v3_task_model/oversight/task_model.json"
[ -f "$TM" ] || { echo "no v3 task model for $INST at $TM"; exit 1; }

exec .venv/bin/python run.py delegation_laundering \
  --instance "$INST" --cond multi --prompt plain \
  --model claude-sonnet-4-5-20250929 \
  --exp live_v3 --rep "$REP" \
  --oversight --interactive --tool v3 --task-model "$TM"
