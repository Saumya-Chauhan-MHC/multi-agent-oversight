#!/bin/bash
# Boot an arm the way the task says to, and run all 12 gates against it.
#
# The first version of this ran `python -m app`, copied from the skeleton. That is not the task's
# contract. instruction.md says `bash /app/start.sh` runs the service, and "Storage, framework,
# process model, and internal architecture are open". One arm restructured to a root-level
# main.py under uvicorn and updated start.sh to match, which is allowed; hardcoding `python -m app`
# would have scored it zero for making a legal choice, and the arms that happened to keep the
# skeleton's layout would have won on a grading artefact.
APP="$1"; LABEL="$2"
PY=/tmp/stripe_task/.venv/bin/python
VENVBIN=/tmp/stripe_task/.venv/bin
pkill -f "uvicorn main:app" 2>/dev/null; pkill -f "python -m app" 2>/dev/null; sleep 1
cd "$APP" || exit 1
# the venv first on PATH so `python`/`uvicorn` in start.sh resolve to the graded environment
STRIPE_SK=sk_test_master PATH="$VENVBIN:$PATH" nohup bash start.sh > /tmp/${LABEL}_server.log 2>&1 &
for i in $(seq 1 25); do
  curl -s -m 2 http://127.0.0.1:8000/v1/health 2>/dev/null | grep -q ok && break
  sleep 1
done
if ! curl -s -m 2 http://127.0.0.1:8000/v1/health 2>/dev/null | grep -q ok; then
  echo "$LABEL: SERVICE DID NOT BOOT"; tail -6 /tmp/${LABEL}_server.log
  pkill -f "uvicorn main:app" 2>/dev/null; pkill -f "python -m app" 2>/dev/null; exit 1
fi
cd /tmp/stripe_task/tests
tp=0; tf=0; gok=0; gn=0
for f in test_*.py; do
  line=$(STRIPE_SK=sk_test_master $PY -m pytest "$f" -q --no-header -p no:cacheprovider 2>&1 | grep -E "passed|failed|error" | tail -1)
  p=$(echo "$line" | grep -oE "[0-9]+ passed" | grep -oE "[0-9]+"); p=${p:-0}
  fl=$(echo "$line" | grep -oE "[0-9]+ failed" | grep -oE "[0-9]+"); fl=${fl:-0}
  tp=$((tp+p)); tf=$((tf+fl)); gn=$((gn+1))
  [ "$fl" = "0" ] && gok=$((gok+1))
  printf "  %-26s %s\n" "$f" "$(echo $line | cut -c1-44)"
done
echo "$LABEL: $tp passed, $tf failed  |  gates fully passing: $gok/$gn"
pkill -f "uvicorn main:app" 2>/dev/null; pkill -f "python -m app" 2>/dev/null
