# The control arm

One run of the SWE-Marathon slack-clone task, built with **no tool active**. The hooks that were
installed only appended to a log and returned nothing, so they could not pause a tool call, inject
text, or reach the agent in any way. Verified: the recording contains zero tool judgements and zero
permission decisions.

This single run does two jobs, which is why both comparisons point at this folder.

| | |
|---|---|
| **its recording** is the subject of comparison 1 | 111 decisions, labelled by hand, then replayed through the tool |
| **its implementation** is the control of comparison 2 | graded by the real SWE-Marathon suite, 137 of 143 |

That is deliberate rather than convenient. Ground truth for comparison 1 has to come from a run the
tool never touched: if the tool had been speaking during the build, its interruptions would have
changed what the agent did next, so the answer key would describe a world the tool created. An
unobserved run is also exactly what comparison 2 needs as its control.

## The files

### What the agent did

| file | what it is |
|---|---|
| `trajectory.jsonl` | the run's event log, trimmed to what the replay reads: every decision (Write, Edit, Bash, Agent) plus the session and subagent lifecycle. `post_tool` records and reads are dropped, which takes it from 4.6 MB to 0.7 MB and reproduces all 111 decisions identically |
| `decisions_readable.txt` | the same 111 decisions in human-readable form, for reading alongside the answer key |

### The answer key

| file | what it is |
|---|---|
| `golden.jsonl` | one row per decision, nine fields each. The key comparison 1 scores against |
| `golden.csv` | the same thing, for reading in a spreadsheet. `human_confirmed` is the empty column waiting for a second reader |
| `make_golden.py` | how every label was produced. A script rather than a spreadsheet, so a label change is a diff and the reasoning is in the file |
| `check_golden.py` | validates the key mechanically, 974 checks. See the caveat below |

A row records: should the tool have spoken, on which surface, **which task preference is
misaligned**, whether the developer actually wrote that preference or it is inferred, which
requirement the misalignment undermines, which metric declines, which safety risk it is, whether a
developer would have wanted it in the moment, which real grader test later failed because of it,
whether acting would have helped, and whether they would be glad afterwards.

**What the validator does not do.** It confirms a citation **resolves**, not that it is **apt**. It
checks that `R4` is a real requirement; it cannot check that `R4` is the right requirement for that
decision. One row cited `R3` for a role-permission test and passed validation, because `R3` exists.
`R3` is "user profiles readable and updatable", which is the wrong requirement entirely. It was
caught only because the tool cited `R4` instead and the tool turned out to be right. A second reader
is the only thing that catches that class of error, which is what `human_confirmed` is for.

### What the tool did, and how it scored

| file | what it is |
|---|---|
| `task_model.json` | the preferences and requirements the extractor produced from the brief, before the run started. This is what the tool judges against |
| `results.jsonl` | one row per decision: which trigger fired, the verdict, the confidence, the band, what it cited, whether it reached the user and why not |
| `scores.json` | surfacing, detection, band accuracy, attribution, alarms per 100 |
| `scores_bands.json` | the same decisions scored on which surface they belong on, kept separate because a band error and a blindness error are different failures |
| `scores_outcome.json` | scored against what really happened: did it speak where acting would have fixed a test that actually failed |

### The task outcome

| file | what it is |
|---|---|
| `grade_report.json` | the real SWE-Marathon suite's verdict on what this run built. 137 of 143, 2 of 3 runnable gates, and the agent's own suite at 39 of 49 |

## Reproducing it

```bash
# replay the recording through the tool
PYTHONPATH=. python3 -m oversight.v3.replay trajectory.jsonl --model-dir . --out results.jsonl

# score it
python3 ../code/score.py         results.jsonl golden.jsonl scores.json
python3 ../code/score_bands.py   results.jsonl golden.jsonl scores_bands.json
python3 ../code/score_outcome.py results.jsonl golden.jsonl scores_outcome.json

# check the answer key itself
python3 check_golden.py

# rebuild the key from its source
python3 make_golden.py
```
