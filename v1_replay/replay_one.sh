#!/bin/bash
# One v6 replay: replay_one.sh RUN_DIR TASK NAME K OUT
d=$1; t=$2; n=$3; k=$4; o=$5; S=~/research/offline_eval/swe3
mkdir -p $(dirname $o); cd ~/research/offline_eval/replay
python3 harness.py --trajectory $d/record --prompt $d/prompt.txt --rules $S/$t/rules.json --run $k --quiet 120 --out $o > $o.log 2>&1 \
  && echo "done $t $n run$k" || echo "FAILED $t $n run$k"
