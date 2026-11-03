# v2 replay (Monitor A/B)

Yule's offline replay of Monitor A and Monitor B, copied from the `monitor-ab` branch (7cc9f53), in the same layout (`experiments/` next to `overlay/oversight/`) so it runs as-is.

| Path | What it is |
|---|---|
| `experiments/replay.py` | entry point: replays recorded runs through Monitor A or B |
| `experiments/harness/monitor_a.py` | steps through `stream.jsonl` and asks judge A or B at each action that changes files |
| `experiments/harness/*` | the rest of the harness (runner, gates, docker; also used for recording) |
| `experiments/swechat`, `real_divergence`, `delegation_laundering` | task (scenario) definitions: mkdocs_warning; astropy and django |
| `overlay/oversight/va`, `vb` | the Monitor A and Monitor B judges |
| `overlay/oversight/v5`, `judge.py`, `memory.py`, ... | shared code the judges and harness import |

Run (from `experiments/`):
```
AB_PREFS=1 python replay.py real_divergence RUN_DIR ... --tool A
AB_PREFS=1 python replay.py swechat RUN_DIR ... --tool B-action
```
A and B are scored together as one tool (`v1_replay/score_compare.py`).

Changes from `monitor-ab` (21 lines):
- `harness/monitor_a.py`, `replay.py`: with `AB_PREFS=1`, the same 3 preferences v1 gets (`RUN/prefs.txt`) are added to the request, and the results go to `*_prefs.json`.
- `harness/claude.py`, `harness/runner.py`: with `IB_RECORD` set, hooks record every tool call (used to make the 24 no-monitor rollouts).
