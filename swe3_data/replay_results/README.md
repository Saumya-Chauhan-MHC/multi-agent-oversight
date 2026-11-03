# Replay results (1 replay per tool, all 24 rollouts)

- `v1/<task>/<run>_run1.jsonl`: my tool (v6). One line per decision point:
  - `idx`: the line of `record/events.jsonl`
  - `stage`: where the tool stopped (filtered, no finding, judge cleared, queued, shown, still open)
  - `found`: what it detected
  - `shown`: what reached the user (file + preference id, or safety risk; `still_open` marks a repeated reminder)
- `v2/<task>/<run>/monitor_A.json`, `monitor_B.json`: Monitor A and Monitor B, given the same 3 preferences (`AB_PREFS=1`). Each result is one judged step, with its score `p`; a hold is `p >= threshold`. For scoring, A and B count together as one tool.
- `scores/scores_compare.json`: TP / FP / FN / TN for both tools against the ground truth.
  - Keys: `tool|view|task`. `pref` is per step and `pref_event` is per event; `safety` and `safety_event` are v1 only.
- `scores/ab_pref_map.json`: which preference each Monitor A/B hold was about. A fixed LLM judge decided this (majority of 3); it is needed because v2 writes free text.

Headline (preference events): v1 precision 82% and recall 85% per step, 65% and 92% per event; v2 precision 39% and recall 12% per step, 39% and 58% per event.

The home folder path is replaced with `~`.
