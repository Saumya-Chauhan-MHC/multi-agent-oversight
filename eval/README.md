# Evaluation

Everything here is from the current implementation. Nothing in this directory predates the changes
in `docs/IMPLEMENTATION_CHANGES.md`: earlier replays and earlier versions of the answer keys were
removed rather than kept, because several of their figures were superseded and a reader cannot tell
which snapshot a loose score file belongs to.

Two separate exercises, answering different questions.

## Comparison 1 · is the tool flagging the right things?

Replay a recorded run decision by decision and ask, at each one, whether the tool's choice to speak
or stay quiet was right. Scored against an answer key written by hand before the tool was replayed.

The recording comes from a run with **no tool active**, hooks that append to a log and return
nothing, so they cannot pause a tool call, inject text or reach the agent. Ground truth has to come
from an unobserved run: if the tool had been speaking during the build, the key would describe a
world the tool created.

| | `control-arm/` |
|---|---|
| decisions | 111 |
| golden positives | 2 |
| detection, precision / recall | 0.13 / **1.00** |
| surfacing, precision / recall | 0.50 / 0.50 |
| band accuracy | 0.97 |
| attribution: preference / metric / risk | 1.00 / 1.00 / 1.00 |
| alarms per 100 decisions | 1.8 |

**These figures have not reproduced.** A second recording replayed through the same code gave
surfacing 0.00 and attribution 0.00. Its data is not in this repo, because its trajectory came from
an earlier generation of hooks that injected preference lines into the agent's opening context, so
it was never a clean control. The non-replication stands as a limit on the figures above regardless,
and with two golden positives it is what you would expect: **nothing here is a rate.**

`control-arm/` holds:

| file | what it is |
|---|---|
| `golden.jsonl`, `golden.csv` | the answer key, one row per decision |
| `make_golden.py` | how every label was produced. A script, not a spreadsheet, so a label change is a diff |
| `check_golden.py` | validates the key mechanically. Every citation resolves, every speaking row names the misaligned preference and its provenance and the requirement it undermines and a metric and a risk, `annoyed` never coexists with `should_surface`, every named failing test really did fail |
| `results.jsonl` | one row per decision: trigger, verdict, confidence, band, what it cited, whether it reached the user, and why not |
| `scores.json`, `scores_bands.json`, `scores_outcome.json` | the scored output |
| `task_model.json` | the preferences and requirements extracted before the run |
| `decisions_readable.txt` | the decisions in human-readable form, for reading alongside the key |
| `trajectory.jsonl` | the recording itself, trimmed to what the replay reads |
| `grade_report.json` | the real suite's verdict on what this run built |

### What a label records

| field | question |
|---|---|
| `should_surface` | should the tool have said anything at all |
| `expected_band` | **hold** (stop the action and ask), **check** (one line, nothing paused), **silent** |
| `preference` | **which task preference is misaligned.** The spine of the label |
| `pref_stated` | did the developer *write* that preference, or is it **inferred**? An inferred rule must be proposed for confirmation, never quoted as theirs |
| `serves` | which requirement(s) the misalignment undermines. This is the *path* from the preference to the metric |
| `metric` | official test success, elapsed time, or token budget |
| `risk` | collusion, miscoordination, conflict |
| `want_interrupt` | 1 to 5, judged **in the moment** |
| `official_test` | which real grader test later failed because of this |
| `would_help` | had the developer acted here, would that test have passed |
| `satisfied_after` | glad / neutral / annoyed, judged **after** the grader's verdict |

The last three exist only on `control-arm/`, because only that run was graded by the real suite.
Before that, `metric: tests` was a prediction nobody could check.

## Comparison 2 · does the project come out better with the tool?

Build the same task twice and let the real SWE-Marathon suite decide. Individual judgements do not
count here; the grader does not know the tool exists.

```
                             control, no tool   treatment, tool active
wall clock, minutes          19.6               19.6
judge calls                  0                  147
items put to the developer   0                  2
developer answers            -                  1 note, 1 block
the agent's own suite        39/49              84/86
official tests passed        137/143            137/143
runnable gates passed        2/3                2/3
```

`treatment-arm/` holds that run's task model, its 149 judgement and developer-answer records, and
its grade report. The control's grade report is in `control-arm/`, because the control of
comparison 2 and the recording labelled by comparison 1 are **the same run**: one build of the task
with no tool active, doing both jobs.

Two of the five correctness gates, `crash` and `chaos`, walk `/proc` to find the process holding a
port, so they cannot run on macOS. They are recorded as **void, not failed**, which is why only
three gates are compared and the official binary reward is undeterminable here.

The treatment arm was answered by a **stand-in developer** (`OV_SIMUSER=1`), because a run with
nobody to ask raised six holds and eleven checks that all went nowhere and reproduced the control
exactly: it measured the cost of oversight when ignored, not its effect. The stand-in is shown the
action, the rule in the developer's own words or the brief's own sentence, the provenance including
an explicit note when a rule was inferred, the conflicting part, the predicted cost and the
correction. It is **not** shown the confidence or the band. It is not a human study.

## What is honest to say from this

| | |
|---|---|
| **the judgement layer works** | on the clean recording it found both genuine preference misalignments, named the right metric and the right safety risk every time it spoke, and its chain from preference to metric was verified against tests that really failed |
| **delivery is the bottleneck** | half of what it correctly understood did not reach the developer. That is a precision and queueing problem, not a comprehension one |
| **it does not cry wolf** | under 2 alarms per 100 decisions, and nothing it delivered was labelled as something the developer would have regretted |
| **it passed the trap** | three moments in the clean recording would have made the run *worse* if acted on, including one where the apparent violation is what kept the run healthy. It raised none of them |

And what is not:

| | |
|---|---|
| two golden positives is not a sample | "caught one" and "caught both" are a coin flip apart |
| the strongest machinery barely ran | no shared interface rewritten under live dependents, no resource conflicts, and across 111 decisions no subagent ever wrote a file it did not own |
| one run per arm means no effect size | comparison 2 measures the absence of an obvious cost, not a benefit |
| nothing was prevented | the stand-in blocked one real thing and the official score was unchanged |
| the key and the system share an author | `human_confirmed` is empty on all 184 rows |

## Layout

| folder | what is in it |
|---|---|
| `control-arm/` | the run with no tool: its recording, the answer key, the replay, the scores, and its grade |
| `treatment-arm/` | the run with the tool active: its model, its judgements, and its grade |
| `code/` | the replay harness, three scorers, the label-derivation check, the grader |
| `writeups/` | both comparisons, short and in full, plus the design |

Every folder has its own README.

## Code

`code/` holds the replay harness, the three scorers, the label-derivation check and the grader.

```
# replay a recording through the tool
PYTHONPATH=. python3 -m oversight.v3.replay trajectory.jsonl --model-dir . --out results.jsonl

# score it
python3 code/score.py results.jsonl golden.jsonl scores.json
python3 code/score_bands.py results.jsonl golden.jsonl scores_bands.json
python3 code/score_outcome.py results.jsonl golden.jsonl scores_outcome.json

# grade an implementation against the real suite
python3 code/grader/run_gates.py <impl> --tests <official tests> --python <venv> --out <dir>
```

`--verdicts <an earlier results.jsonl>` replays the policy stage only, reusing the judgements, so a
threshold change can be scored without paying for a full judge pass.
