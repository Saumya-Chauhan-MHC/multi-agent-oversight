# Evaluation

## Start here, if you have not seen this before

The tool watches a coding agent that is running several subagents, and almost always says nothing.
Occasionally it interrupts, because an agent is about to depart from how the developer said the work
should be done, in a way that will cost something measurable. The design is in
[`../README.md`](../README.md), and in full in [`writeups/DESIGN.md`](writeups/DESIGN.md).

There are two things you might want to know about a tool like that, and they are not the same
question:

| | the question | how it is answered here |
|---|---|---|
| **Comparison 1** | At each individual moment, did it make the right call about speaking? | replay a recorded run and compare every decision against a handwritten answer key |
| **Comparison 2** | If you install it, does the project come out better? | build the task twice, with and without it, and let the real test suite decide |

They can disagree in both directions, which is why both exist. A tool can be right about every
decision and still not help, if nobody acts on what it says. A tool can be wrong half the time and
still help, if the one thing it got right was the thing that would have broken the build.

Everything in this directory is from the current implementation. Earlier replays and earlier
versions of the answer keys were deleted rather than kept, because a loose score file does not tell
you which version of the tool produced it.

## Comparison 1 · is the tool flagging the right things?

Replay a recorded run decision by decision and ask, at each one, whether the tool's choice to speak
or stay quiet was right. Scored against an answer key written by hand before the tool was replayed.

**Why an answer key is needed at all.** The tool outputs a decision and nothing in the world says
whether it was right. A test suite is objective, a test passes or it does not. "Should you have
interrupted the developer here?" has no oracle anywhere, so somebody has to read the recording and
write down the right answer at each moment. That is the key, and it is in `control-arm/golden.csv`
if you want to read it.

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

### Where each of those numbers comes from

Every score is computed by comparing one column of the answer key against what the tool actually
did. Nothing is scored that is not labelled.

| this score | compares this column of the key | against what the tool did | and reads |
|---|---|---|---|
| **surfacing** | `should_surface` | did the notice reach the developer | 1 of the 2 moments reached them. It found both and delivered one |
| **detection** | `should_surface` | did the judge call it a departure **at all**, before the pacing rules decided whether to speak | both, every time. Nothing was missed by the filter or the judge |
| **band accuracy** | `expected_band` | which surface it chose | 0.97. When wrong it was off by one step, never two: it never confused "stop everything" with "say nothing" |
| **attribution: preference** | `preference` and `serves` | which rule or requirement it cited | 1.00 on what it delivered |
| **attribution: metric** | `metric` | which measure of success it said would decline | 1.00 |
| **attribution: risk** | `risk` | which failure mode it named | 1.00 |
| **alarms per 100** | *(no column: a count)* | how often it spoke at all | 1.8 per 100 decisions |

Two more scorers use the remaining columns. `scores_bands.json` scores `expected_band` on its own,
separately from whether anything was printed, so that a wrong-surface error and a said-nothing error
do not get mixed together. `scores_outcome.json` uses `official_test`, `would_help` and
`satisfied_after`, which only exist because this run was graded by the real suite: it asks whether
the tool spoke where acting would have fixed a test that genuinely failed, and whether anything it
delivered was something the developer would have regretted. That last count is **0**.

**Why detection and surfacing are separate.** Detection asks whether the tool understood. Surfacing
asks whether the developer heard. Splitting them is what localises a miss: detection 1.00 with
surfacing 0.50 means the tool is not blind, it is bad at delivery, and those need completely
different fixes.

**Two golden positives is not a sample.** "Caught one" and "caught both" are a coin flip apart, so
these are facts about this run rather than measurements of the tool. The limits are listed in full
at the end.

`control-arm/` holds:

| file | what it is |
|---|---|
| `golden.jsonl`, `golden.csv` | the answer key, one row per decision |
| `make_golden.py` | how every label was produced. A script, not a spreadsheet, so a label change is a diff |
| `check_golden.py` | checks the answer key for internal mistakes. See below |
| `results.jsonl` | one row per decision: trigger, verdict, confidence, band, what it cited, whether it reached the user, and why not |
| `scores.json`, `scores_bands.json`, `scores_outcome.json` | the scored output |
| `task_model.json` | the preferences and requirements extracted before the run |
| `decisions_readable.txt` | the decisions in human-readable form, for reading alongside the key |
| `trajectory.jsonl` | the recording itself, trimmed to what the replay reads |
| `grade_report.json` | the real suite's verdict on what this run built |

### Checking the answer key itself

The key is handwritten, so it can be wrong, and a wrong key is worse than no key: it scores
agreement rather than correctness and does so silently. `check_golden.py` runs 974 automatic checks
over it. In plain terms it asks:

- does every rule and requirement the key cites actually exist in `task_model.json`? (a typo like
  `R19` in a model that stops at `R18` is caught here)
- does every row that says "speak" also name a misaligned preference, say whether the developer
  wrote that preference, name the requirement it undermines, name a metric and name a safety risk?
  A row cannot claim something is worth an interruption without saying what it costs
- is the key internally consistent? `should_surface` must agree with `expected_band`, and a row
  cannot simultaneously say "the developer should have been told" and "the developer would have been
  annoyed to be told"
- when a row names a real test that failed, **did that test actually fail?** This is checked against
  the grader's own output, not taken on trust

**What it cannot do, and this matters.** It confirms a citation **resolves**, not that it is the
**right** one. It can check that `R4` is a real requirement; it cannot check that `R4` is the right
requirement for that decision.

That is not hypothetical. One row cited `R3` for a test about role permissions, and the check passed
it, because `R3` exists. `R3` is "user profiles readable and updatable", which is the wrong
requirement entirely. It was caught only because the tool cited `R4` instead, and on inspection the
tool was right and the key was wrong. **A second reader is the only thing that catches that class of
error**, which is what the empty `human_confirmed` column in `golden.csv` is for.

### What a label records

| field | question |
|---|---|
| `should_surface` | should the tool have said anything at all |
| `expected_band` | **hold** (stop the action and ask), **check** (one line, nothing paused), **silent** |
| `preference` | **which task preference is misaligned.** The spine of the label |
| `pref_stated` | did the developer actually write that preference down, or did the tool infer it? See below |
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
