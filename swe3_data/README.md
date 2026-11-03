# swe3 data: rollouts and ground truth

There are 3 tasks with 8 runs each. All 24 runs were recorded with Claude Haiku in Claude Code, with no monitor running. The agent never saw the preferences.

- `rollouts/<task>/<run>/`: one recorded run.
  - `rep0`–`rep3` are single-agent runs; `multi_rep0`–`multi_rep3` are runs where the lead agent must hand the work to subagents.
  - `prompt.txt`: the user's request.
  - `record/events.jsonl`: every tool call in order, with timestamps (what v1 replays). Decision point idx N is line N+1.
  - `stream.jsonl`: the transcript (what v2 replays).
  - `final.txt`, `final.patch`, `result.json`: the agent's answer, its code changes and the test outcome.
- `ground_truth/<task>/rules.json`: the 3 preferences both tools were given.
- `ground_truth/<task>/<run>/`: the labels for one run.
  - `draws.json`: the 3 raw LLM-judge draws.
  - `gt_events.json`: the events kept by 2 of the 3 draws (G = preference, S = safety), with window, targets, preference or risk, and votes.
  - `gt_points.csv`: one row per decision point, with its preference label and safety label (FLAG / NO FLAG) and the reason.
- `ground_truth/label.py`: the labeller. `LABEL_CHANGES.md` records every change to the labelling prompt; labels were never edited by hand.

Totals: 211 decision points, 12 preference events and 1 safety event.

Note: the original home folder path was replaced with `~`, the same way everywhere, before publishing. The data is otherwise unchanged.
