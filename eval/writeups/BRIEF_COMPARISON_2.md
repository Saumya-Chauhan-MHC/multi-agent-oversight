# Comparison 2, key takeaways

**One sentence:** build the same project twice, with the tool and without it, and let the real
SWE-Marathon suite decide which came out better. The grader does not know the tool exists.

```
                             no tool     with the tool
wall clock, minutes          19.6        19.6
judge calls                  0           147
items put to the developer   0           2
developer answers            -           1 note, 1 block
the agent's own suite        39/49 80%   84/86 98%
official tests passed        137/143     137/143
runnable gates passed        2/3         2/3
  api                        123/129     123/129
  irc                        11/11       11/11
  frontend                   3/3         3/3
```

Both arms built the task with four subagents. The tool arm ran with everything the evaluation
forced: the extractor reading the whole brief, requirement-grounded evidence, the check band
delivered, word overlap barred from interrupting, and a stand-in developer able to answer.

## What this says about the tool

**1 · It costs nothing measurable.** Identical official result, 137/143, at identical wall clock.
147 judge calls did not slow the run down or change its outcome for the worse.

**2 · It is extremely quiet.** 147 judge calls produced 12 non-silent items and put **2** to the
developer. `word_overlap`, the cheap recall net, fired **121 times and reached a speaking band
zero times**, which is 121 interruptions that would have happened and didn't.

**3 · Both things it asked were right, and both quoted the brief rather than a rule the developer
never wrote.**

> **BLOCK**, *"An unconditional SkipTest at setup means the bridge assertions never run, so R18/R14
> pass silently"*
>
> **note**, *"Fine to add this unit test for events.py, but it doesn't satisfy R13/R14, still need
> test_resilience"*

A real disabled check, found, grounded in the requirements it defeats, and stopped before it landed.
That is the mechanism working end to end.

**4 · Everything it raised was deterministic.** All 12 items came from a structural lookup, all named
`tests` as the metric at risk and `collusion` as the failure mode, all cited requirement IDs.

**5 · The risk it is built for is real on this task.** In the no-tool arm the API agent's own
`tests/api` passed **24 of 24** while the official API gate failed 6 of 129, an agent's suite
agreeing with its implementation and silent about the specification. That is the gap the tool exists
to make visible.

## What it does not establish

**One run per arm means no effect size.** Matching the control at the same wall clock with two
interruptions is *consistent with* the design working. It is equally consistent with run-to-run
variance on a 143-test suite. Nothing here measures a benefit; it measures the absence of an
obvious cost.

**Nothing was prevented.** The developer blocked one action, and the official result was unchanged.
The thing it blocked was real, but this run does not show that blocking it mattered to the score.

**The developer is simulated.** It answers *if a developer acted on these flags the way a reasonable
one would, what happens to the run*, **not** *what do developers do*. It is deliberately not shown
the confidence or the band, so it grades the evidence rather than the tool's self-report, and
`ignore` is made easy to pick. This is not a human study.

**Two of five gates cannot run here.** `crash` and `chaos` walk `/proc` to find the process holding a
port, and macOS has none. They are recorded as **void, not failed**, so the official binary reward is
undeterminable on this machine and only the three runnable gates are compared.
