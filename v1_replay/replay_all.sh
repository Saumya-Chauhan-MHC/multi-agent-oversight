#!/bin/bash
# Step F: replay every collected run through v6, 3 runs each, 120 s quiet window. ROUND names the iteration.
S=~/research/offline_eval/swe3; ROUND=${1:-r0}
for d in $S/*/runs/*rep*; do t=$(basename $(dirname $(dirname $d))); n=$(basename $d)
  for k in 1 2 3; do o=$S/$t/replay/$ROUND/${n}_run$k.jsonl; [ -s $o ] || echo "$d $t $n $k $o"; done; done \
  | xargs -P 12 -n 5 $S/tools/replay_one.sh
