#!/bin/bash
# Grade ./task with the official ProgramBench hidden tests.
#
#   ./grade.sh            packs task/ into run/<instance_id>/submission.tar.gz and runs `programbench eval`
#   ./grade.sh pack       only packs (e.g. to grade on a Linux x86_64 machine later)
#
# Needs: docker, and `programbench` (pip install programbench, or uv: `uvx programbench`).
# The eval pulls the task image, wipes /workspace, extracts the submission, runs ./compile.sh with the
# network blocked, then runs every hidden test branch against ./executable and writes
# run/<instance_id>/<instance_id>.eval.json. Test archives are fetched from HuggingFace on demand.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
TASK="$HERE/task"
IID=$(cat "$TASK/oversight/instance_id")
RUN="$HERE/run"
mkdir -p "$RUN/$IID"

echo "== packing $TASK -> $RUN/$IID/submission.tar.gz"
# Excluded: our study files (oversight/, .claude/, oracle/, CLAUDE.md, PROMPT.md) and the current
# ./executable (the grader deletes it anyway and rebuilds from compile.sh). Everything the agent
# wrote, including its .git, goes in.
tar -czf "$RUN/$IID/submission.tar.gz" -C "$TASK" \
  --exclude=./oversight --exclude=./.claude --exclude=./oracle \
  --exclude=./CLAUDE.md --exclude=./PROMPT.md --exclude=./executable .
tar -tzf "$RUN/$IID/submission.tar.gz" | head -20 | sed 's/^/   /'
[ "${1:-}" = "pack" ] && exit 0

if command -v programbench >/dev/null; then PB=programbench
elif command -v uvx >/dev/null; then PB="uvx programbench"
else echo "install programbench first:  pip install programbench   (or install uv and use uvx)" >&2; exit 1; fi

echo "== programbench eval (this pulls the image and may take a while)"
export DOCKER_DEFAULT_PLATFORM=linux/amd64
$PB eval "$RUN"
echo "== summary"
$PB info "$RUN"
echo "Per-test results: $RUN/$IID/$IID.eval.json"
