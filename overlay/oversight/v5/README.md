# v5, the plain tool

v5 takes two more things out of v4: the rule file, and the filter.

## What changed and why

**No rule file. The task description is the input.** v4 asked you to write `RULES.md`. A reviewer
said plainly that this is not the baseline, because you are being asked to restate your own task in
a second document, and they were right. The SWE-Marathon example settles it: that `RULES.md` was a
hand transcription of `CONTRACTS.md`, line for line, and the one line transcribed wrong gave
`start.sh` to nobody where the contract gives it to the lead. That produced a confident,
well-evidenced, completely wrong block and cost a whole run.

So `task.py` reads what the task already ships: `PROMPT.md`, falling back through `TASK.md`,
`CONTRACTS.md`, `SPEC.md` and `README.md`, or whatever `OV_TASK_FILE` names. Nothing is extracted,
summarised or rewritten on the way.

What v4 got from a hand-written file was a guarantee: a rule it cited was yours, because you wrote
it. That guarantee is kept in a different form. A yes must quote your task description word for
word, and `judge5` looks the quote up in the text, with whitespace and case flattened so a faithful
quote is not rejected over a line break. An invented or paraphrased line is turned into a no and
marked `invalid-quote`. A clash between two agents is allowed to stand without a quote, because it
is a fact about two pieces of code rather than a claim about a sentence.

**No filter.** v4 decided whether to judge at all, using six structural lookups and a word overlap
recall net. Two things were wrong with that. An action matching no lookup was never judged, so a
rule you could write but no lookup covered produced silence rather than a miss, which is exactly
how one run watched the lead write a file the contract gave to someone else and said nothing. And
the recall net cost 216 judge calls across two arms for 0 of 8 correct, so the cheap half was also
the useless half.

Every action that can change the repository is judged now. What is kept from the filter is only its
content side: finding what another agent has already written to the same file. That is not a gate.
It is the one fact neither agent can see and the oversight layer can, and without it the judge
would be asked whether an action is stale while being shown only that action.

Three gates do remain in front of the judge, and calling them "no filter" would be overstating it:
the tool must be one that can change something (a `Read` is not), there must be a task description
to quote, and a decision already taken on the same action, task text, agent and cross-agent context
is not retaken.

## What it costs

Judging everything is the expensive choice. v4's filter cut judge calls from 101 to 6 on one
recording. v5 gives that up deliberately, to buy the property that a rule you can state is a rule
the tool can act on.

## What is not in here

**The queue.** v3 had a surfacing queue with grouping, ranking and a ten minute quiet window. v4
dropped it and v5 has no trace of it. The one thing that looks like a queue is the per-agent inbox,
and it is a different object: a mailbox for a relayed correction, delivered to one named agent on
its next tool call, with no grouping and no pacing. What stands in for the queue's job of not
interrupting you twice about the same thing is one answer per topic, keyed on the quoted sentence.

The developer's view on this, to be taken up as the design is worked through:

> I think that the implementation of the queue, with higher-priority information at the top, is
> also essential. Only surfacing that information and then waiting for another hold to surface the
> others that appear at the same time makes sense too.
>
> But I will add that back sequentially and let you know as we experiment with this design.

So the queue is expected to return, ordered by priority, surfacing the top item and holding the
rest until the next hold. It is out of v5 on purpose rather than by judgement that it is wrong.

**A confidence number.** v3 banded on the judge's confidence, which across three measurements
ordered decisions at 0.09, 0.52 and 0.67, where 0.5 means it carries no information. There is no
confidence field to return.

**A middle band.** Hold or silence. v3's check band paused nothing and could be ignored.

## Step by step: what happens on one action

1. **An agent is about to act.** `PreToolUse` fires with the tool name and input.

2. **Is this an act that can change anything?** `Write`, `Edit`, `MultiEdit`, `Task`, `Bash`. A
   `Read` or `Grep` exits here.

3. **Read the task description** from the task's own file: `PROMPT.md`, falling back through
   `TASK.md` / `CONTRACTS.md` / `SPEC.md` / `README.md`. No `RULES.md`. If there is no task text,
   exit.

4. **Work out which files this touches.** An edit names its file; a shell command gets its paths
   read out of the command text.

5. **Look up what other agents already wrote to those same files.** Same file across two checkouts
   counts; sibling directories in one repo do not. This is the only thing the tool knows that
   neither agent can see.

6. **Seen this exact decision before?** Same action, same task text, same agent, same cross-agent
   context, and the old answer is reused. Otherwise ask.

7. **Ask the judge once.** It gets the task description, who is acting, the action, and what the
   others did. It answers yes or no. A yes must quote the task word for word, and the quote is
   checked against the text: an invented one becomes a no.

8. **No, and the tool is silent.** The agent never knows it is there. This is the overwhelmingly
   common case.

9. **Yes, and has the developer already answered about this sentence?** If so, reuse it. Nobody is
   interrupted twice about the same thing.

10. **Otherwise ask the developer.** Block, or let it through. They are shown the task sentence,
    what the action does, and what each answer causes.

11. **Block denies the call,** with the reason.

12. **Allow splits the correction in two.** What the acting agent can fix in its own checkout goes
    back to it on the spot. What only another agent's checkout can fix is posted to that agent's
    inbox and injected on its next tool call. If that agent has already finished, it falls back to
    the orchestrator.

## The task we run, and why

**STALE** (arXiv 2609.25396, `github.com/illinoisdata/STALE-bench`), the real-derived tier: 36
instances built from 12 Django helpers under 3 mechanisms.

Each instance is two pieces of work on one module, given to two subagents that cannot see each
other's checkout.

| | |
|---|---|
| task A | a breaking, behaviour-preserving change to a shared helper: rename it, add a required keyword-only argument, or wrap its return type |
| task B | add a new function that reuses that same helper |
| merge | both diffs applied mechanically with `git apply --3way` after the session ends |
| oracle | one held-out assertion, calling only B's new function |

The oracle never names the helper and never appears in the prompt. For `strip_tags` it is

```python
assertEqual(m.text_preview('<b>hello</b> world', 5), 'hello')
```

so it passes only if B's call still fits A's helper once the two diffs are merged. It is a coupling
check wearing the clothes of a unit test, which is why it fails three different ways: `NameError`
after a rename, `TypeError: missing 1 required keyword-only argument` after a signature change,
`AssertionError: Result(value=...) != ...` after a return type change.

**Why this task.** Three reasons, and the third is the one that rules most benchmarks out.

It is genuinely multi-agent. The failure needs two agents working at once on one thing, which is
the only shape where this tool can matter at all.

It has published evidence that a human in the loop helps. The paper's headline is an intervention
result: silent interference 105 of 108 blind, and **one oracle message recovers 89 of 108**. So
there is a measured ceiling of 82% rather than an assumption, and our tool is strictly harder than
their condition because it has to *find* the conflict rather than being handed it.

It runs without Docker, in minutes, with a held-out grader.

**What was rejected and why.** ImpossibleBench was tried first and produced 0 of 15 cheating in
both conditions: a benchmark with a zero base rate cannot show a tool preventing anything.
ClashBench fits the mechanism well and grades with per-case health checks and LLM judges inside
Docker containers, with the agent running inside the image, so it is a harness project rather than
a test suite. SWE-Marathon has a real 143-test public suite and is genuinely multi-agent, but has
no human-in-the-loop evidence in any paper, and measured 16 tests of run-to-run spread between two
runs where the tool never fired, so it cannot resolve a difference at one run per arm.

## Results

Three arms, same 36 instances, one run each. "Tests passing" is the oracle above. "Both done"
additionally requires A's change to have landed, because the oracle passes for free when the tool
simply stops A from working, and early versions of this tool scored well that way.

| | no tool | with tool | tool + user sim |
|---|---|---|---|
| tests passing | 0/36 | *running* | 7/36 |
| both done | 0/36 | *running* | 4/36 |
| A's work landed | 33/36 | *running* | 31/36 |
| interference | 33/36 | *running* | 27/36 |
| corrections relayed | 0/36 | *running* | 17/36 |

Paired McNemar on both-done: 4 wins, 0 losses, **p = 0.0625. Not significant.**

**The effect did not replicate.** An earlier run of 12 of these instances gave 4 wins, which at
that sample size looked like a third of them. Tripling to 36 gave 4 wins again, not 12. Worse, the
same 12 instances were re-run inside the 36 and **none of the four original winners won again**;
agreement across the two runs was 8 of 12, with every disagreement going from pass to fail. Wins
that move between runs are noise, not a mechanism.

Three more things cut the same way. Three of the seven passing tests had A's work missing, which is
the free-pass trap the both-done column exists to catch. The tool cost A's work twice, 31 against
33. And 17 instances had a correction relayed while only 4 came good, so the relay fires and
usually does not land.

**The honest position: the tool reliably detects these conflicts and reduces interference, 33 of 36
down to 27 of 36. There is still no evidence it improves task success.** What would settle it is
replication, two or three more arms at 36. If the rate is real it will show steadily; if it is
noise the wins will keep wandering.

## Todo

**Put the queue back, and benchmark the experience, not just the outcome.** Ordered by priority,
surfacing the top item and holding the rest until the next hold. Everything measured so far is task
success, which says nothing about whether being interrupted this way is tolerable. That needs its
own benchmark: interruptions per run, how many were worth it, and what a developer does with the
notice. See the quote under *What is not in here*.

**Go back to the DAG's design principles.** The viewer exists and was verified against live v4
data, but it was built as a record of what happened. If the queue is going to rank what reaches the
developer, the DAG is where the ranking should be legible: which agents are live, what each one is
blocked on, which holds are outstanding.

**Run v5 on a benchmark.** It has not been. Every number above describes v4.

**Decide what replaces the metric gate, or decide nothing should.** See below.

**Settle the benchmark question.** STALE is the only candidate that is multi-agent, has published
human-in-the-loop evidence, and runs without Docker, and its test suite is one assertion per
instance. ClarEval (arXiv 2603.00187) has a real unit-test suite and the largest published
intervention gap of any candidate, pass@1 8.94% ambiguous against 89.02% clarified, and no Docker,
but it is single-agent clarification. No benchmark has all four properties.

## Task metrics and surfacing

Gone, and worth being explicit about since it was central to v3.

v3 tied surfacing to metrics. Each preference carried the metrics it served, and whether a notice
reached you depended on an outdatedness score, a precision floor over the last ten decisions, and a
free slot in a ten minute quiet window. v4 kept the `metrics` field on each rule and nothing read
it. v5 has no preference objects at all, so there is nothing left to tie.

What decides whether you are interrupted now is only: does the judge say this action contradicts
your task or another agent's work, and have you already answered about that sentence. No score, no
threshold, no ranking, no pacing.

`align.py` still contains `outdatedness`, `precision`, `slot_free`, `counters` and `bump`, and
nothing in v5 calls any of them. The one align function v5 does use for timing is `credit_pause`,
which credits the judge's own latency so the tool's cost is not charged to the agent's clock.

That is a real loss as well as a simplification: with no pacing and no ranking, two holds arriving
together interrupt twice, in arrival order. That is the gap the queue is meant to close.

## State of the evidence

v5 has not been run on a benchmark. Every number reported so far describes v4.
