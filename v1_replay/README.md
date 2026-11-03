# v1 replay (my tool, v6)

Offline replay of recorded Claude Code runs through v6, one recorded event at a time. It uses the recorded clock, has no lookahead and gets no user answers. The harness never reads the labels.

| File | What it does |
|---|---|
| `harness.py` | feeds a recorded `events.jsonl` to the tool adapter, event by event, and writes the tool's decision at each step |
| `adapter_v6.py` | runs v6 (this branch's `overlay/`) on each event and reports what reached the user |
| `clock_wrap.py`, `check_wrapper.py` | use the recorded timestamps as the clock; check the wrapper |
| `replay_one.sh`, `replay_all.sh` | replay one run, or every run of the 3 tasks |
| `score.py`, `score_points.py` | per-step TP / FP / FN / TN against the ground-truth labels |
| `score_compare.py` | scores v1 and v2 on the same labels (per step and per event) |

Run one replay:
```
python3 harness.py --trajectory RUN/record --prompt RUN/prompt.txt --rules rules.json --run 1 --quiet 120 --out out.jsonl
```

Notes:
- `adapter_v6.py` loads the tool from `~/research/multi-agent-oversight/overlay` (the `TOOL` line). The swe3 results used the v6 code at commit a173f98 on this branch.
- `harness.py` writes `tool_commit="1639cf9"` into every output. That label is hard-coded; the code that actually ran is 1639cf9 plus the round 1 to 5 changes in a173f98.
- The scripts use the paths of the original machine (`~/research/offline_eval/...`); change them to your own.
