# The measurement code

None of this is the tool. The tool lives in `overlay/`. This is what measures it, and it was wrong
often enough during the evaluation to be worth separating clearly: four of the defects found in the
last round were in here rather than in the thing being measured, and each one produced a plausible
number.

| file | what it does |
|---|---|
| `replay.py` | runs a recorded trajectory back through the tool, one decision at a time |
| `score.py` | did the developer get told, and did the judge see it at all. These are kept apart so a miss localises to a stage |
| `score_bands.py` | which surface each decision belongs on, scored separately from whether anything was printed |
| `score_outcome.py` | scored against what really happened: did it speak where acting would have fixed a test that actually failed |
| `derive_labels.py` | the labelling rule written as code, so there is one rule to argue with instead of 111 opinions |
| `grader/run_gates.py` | boots an implementation and runs the real SWE-Marathon correctness gates against it |

## Two rules the replay obeys

**No lookahead.** At decision 50 the tool may only see what existed at decision 49. The port
registry and the dependency map are rebuilt from events before the current one, every time. Without
this the tool would look smarter than it is: it would flag an interface rewrite for a dependency
that had not been created yet.

**The trajectory's own clock.** The quiet window, the queue and the preempt budget advance by the
recorded timestamps, so "shown" means shown *then*, not shown eventually.

## Things that were wrong in here, and are worth not repeating

- **the replay did not model the land stage.** The live hook drops an item from the queue once its
  action has happened. The replay did not, so the top-ranked block was one whose action had already
  landed, which can never be the current decision, and nothing was ever shown again
- **grounds were dropped in the verdict-reuse path**, so every queued item was labelled `?`, they
  all collapsed into one block, and showing any member credited every other: a recall of 1.00 that
  meant nothing
- **block delivery was not credited.** The design shows a *block*, so a member of a shown block has
  reached the user. Scoring only the exact decision index produced a false miss
- **the grader had no lock.** Two grading runs tore down each other's cluster and it looked exactly
  like the tool having wrecked a run. It takes a machine-wide lock now, and a gate killed by a
  signal records as **void rather than failed**

## Running them

```bash
PYTHONPATH=. python3 -m oversight.v3.replay trajectory.jsonl --model-dir . --out results.jsonl
python3 score.py results.jsonl golden.jsonl scores.json
python3 grader/run_gates.py <impl> --tests <official tests> --python <venv python> --out <dir>
```

`--verdicts <an earlier results.jsonl>` replays the policy stage only and reuses the judgements, so
a threshold change can be scored without paying for a full judge pass.
