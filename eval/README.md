# Offline eval

Replay a recorded trajectory back through the tool, decision by decision, and score it against a
golden set. This is how a threshold change becomes measurable instead of arguable.

    python3 -m oversight.v3.extract .                                   # task model from the PRD
    python3 -m oversight.v3.replay traj.jsonl --model-dir . --out results.jsonl
    python3 oversight/v3/score.py results.jsonl golden.jsonl scores.json

`--verdicts <earlier results.jsonl>` replays the policy stage only, reusing the judgements, so a
threshold change costs no model calls.

Two rules make a replay mean something. At decision i the port registry and the dependency map are
rebuilt from events before i only, so the tool cannot flag an interface rewrite for a dependency
the run had not created yet. And the quiet window, the queue and the hourly preempt are advanced by
the trajectory's own clock, so shown means shown then.

`golden.jsonl` labels each decision on five axes: should_surface, the preference it departs from,
the metric it threatens, the safety risk, and want_interrupt 1 to 5. The labels are reference
annotations with their evidence in each row, not a person's, and carry an empty human_confirmed
column for adjudication.

What it found on the slack-clone trajectory, 73 decisions: every flag from a structural lookup was
correct and attributed correctly, and every false positive came from the word-overlap path.
