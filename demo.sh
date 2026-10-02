#!/bin/bash
# Scripted demo of the alignment layer, in a throwaway copy of a task folder.
#
#   ./demo.sh                      uses examples/marathon_slack if present, else ./task
#   ./demo.sh /path/to/task        any folder with a PROMPT.md and some docs
#   DEMO_PAUSE=0.2 ./demo.sh       faster, for a quick check rather than a recording
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=${1:-}
if [ -z "$SRC" ]; then
  for c in "$HOME/research/marathon_slack/task" "$HERE/task"; do [ -d "$c" ] && SRC=$c && break; done
fi
[ -d "${SRC:-}" ] || { echo "give me a task folder: ./demo.sh /path/to/task" >&2; exit 1; }
WORK=$(mktemp -d /tmp/oversight-demo.XXXX)
cp -R "$SRC"/. "$WORK"/
cp -R "$HERE/overlay"/. "$WORK"/
[ -f "$SRC/../PROMPT.md" ] && cp "$SRC/../PROMPT.md" "$WORK"/ || true
python3 - "$WORK" <<'PY'
import json, os, sys
p = os.path.join(sys.argv[1], "oversight", "memory")
os.makedirs(p, exist_ok=True)
json.dump({"surface_mode": "file"}, open(os.path.join(p, "settings.json"), "w"), indent=1)
PY
echo "demo workspace: $WORK"
python3 "$WORK/oversight/tests/demo.py" "$WORK"
echo "workspace kept at $WORK (delete it when you are done)"
