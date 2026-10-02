#!/bin/bash
# Set up one exact ProgramBench task for Claude Code on your laptop.
#
#   ./setup.sh alecthomas__chroma.8d04def         (90-minute sessions, default)
#   CAP_MINUTES=60 ./setup.sh tomnomnom__gron.88a6234
#
# What it does (each step is explained in CHANGES.md):
#   1. pulls the official task image  programbench/<owner>_1776_<repo>.<hash>:task_cleanroom_v6
#   2. starts it as a long-lived container "pb_ref" (or $PB_CONTAINER) with no network, with ./task mounted at /work
#   3. copies the official /workspace (docs + reference binary) into ./task
#   4. replaces the Linux-only binary by a wrapper that runs it inside the container (./executable,
#      plus a stable copy ./oracle/reference)
#   5. copies our overlay (CLAUDE.md, PROMPT.md, .claude hooks, oversight viewer + smoke tests) in
#   6. records which toolchains the grading image has, and fills PROMPT.md
set -euo pipefail
IID=${1:?usage: ./setup.sh <instance_id>   e.g. tomnomnom__gron.88a6234}
CAP=${CAP_MINUTES:-90}
HERE=$(cd "$(dirname "$0")" && pwd)
TASK="$HERE/task"
CT=${PB_CONTAINER:-pb_ref}   # reference container name; set PB_CONTAINER to run two setups side by side
IMG="programbench/${IID/__/_1776_}:task_cleanroom_v6"

if [ -e "$TASK" ]; then
  echo "!! $TASK already exists. Move it away first (it may hold a previous run's logs)." >&2; exit 1
fi
command -v docker >/dev/null || { echo "docker is required (Docker Desktop on macOS)" >&2; exit 1; }

echo "== 1/6 pulling $IMG (linux/amd64; on Apple Silicon this runs under emulation)"
docker pull --platform linux/amd64 "$IMG"

echo "== 2/6 starting reference container $CT"
mkdir -p "$TASK"
docker rm -f "$CT" >/dev/null 2>&1 || true
docker run -d --platform linux/amd64 --name "$CT" --network none \
  --user agent -v "$TASK":/work -w /work "$IMG" sleep infinity >/dev/null

echo "== 3/6 copying the official workspace out of the image"
docker cp "$CT":/workspace/. "$TASK"/
ls -la "$TASK" | sed 's/^/   /'
if [ ! -e "$TASK/executable" ]; then
  echo "!! no ./executable in /workspace of the image; check the image name" >&2; exit 1
fi
rm -f "$TASK/executable"   # Linux binary; cannot run on macOS, and copying it is not needed

echo "== 4/6 installing the reference wrapper"
cat > "$TASK/executable" <<EOF
#!/bin/bash
# Reference executable of ProgramBench task $IID.
# The real binary is linux/amd64 and lives at /workspace/executable inside the task container
# "$CT"; this wrapper runs it there. Your current directory is mounted in the container at
# /work, so relative file paths and stdin/stdout behave exactly as if the binary were local.
ROOT="$TASK"
case "\$PWD" in "\$ROOT"*) W="/work\${PWD#\$ROOT}";; *) W="/work";; esac
if ! docker container inspect -f '{{.State.Running}}' $CT 2>/dev/null | grep -q true; then
  echo "reference container $CT is not running; start it with: docker start $CT" >&2; exit 125
fi
exec docker exec -i -w "\$W" $CT /workspace/executable "\$@"
EOF
chmod +x "$TASK/executable"
mkdir -p "$TASK/oracle"; cp "$TASK/executable" "$TASK/oracle/reference"; chmod +x "$TASK/oracle/reference"

echo "== 5/6 copying the study overlay (CLAUDE.md, PROMPT.md, hooks, viewer)"
cp -R "$HERE/overlay/." "$TASK"/
echo "$IID" > "$TASK/oversight/instance_id"
echo "$CAP"  > "$TASK/oversight/cap_minutes"
# live-oversight switches (see oversight/control.py): GATE=on pauses every proposed subagent spawn
# for a human decision; RECOMMEND=on shows the pros / cons section on split cards
echo "${GATE:-off}"      > "$TASK/oversight/gate_mode"
echo "${RECOMMEND:-off}" > "$TASK/oversight/recommend_mode"

echo "== 6/6 probing toolchains in the grading image"
docker exec "$CT" sh -c 'for t in go gcc g++ clang rustc cargo python3 node make cmake; do
  command -v $t >/dev/null 2>&1 && printf -- "- %s: %s\n" "$t" "$($t --version 2>&1 | head -1)"; done' \
  > "$TASK/oracle/toolchains.txt" || true
[ -s "$TASK/oracle/toolchains.txt" ] || echo "- (probe failed; run: docker exec $CT sh -c 'which go gcc python3')" > "$TASK/oracle/toolchains.txt"
python3 - "$TASK/PROMPT.md" "$TASK/oracle/toolchains.txt" "$CAP" <<'EOF'
import sys
p, tc, cap = sys.argv[1], open(sys.argv[2]).read().strip(), sys.argv[3]
s = open(p).read().replace("__TOOLCHAINS__", tc).replace("__CAP__", cap)
open(p, "w").write(s)
EOF

echo
echo "== smoke test of the reference wrapper:"
( cd "$TASK" && ./executable --help 2>&1 | head -5 | sed 's/^/   /' ) || true
echo
echo "Done. Task folder: $TASK"
echo "Next:  cd \"$TASK\" && claude      then paste the contents of PROMPT.md as your first message."
echo "Viewer: cd \"$TASK\" && python3 oversight/viewer/serve.py   ->  http://localhost:4173"
echo "Gate:   $(cat "$TASK/oversight/gate_mode")   recommendations: $(cat "$TASK/oversight/recommend_mode")   cap: $CAP min"
[ "${GATE:-off}" = on ] && echo "        the agent will pause at every proposed split until you decide (viewer, or: python3 oversight/ctl.py watch)"
