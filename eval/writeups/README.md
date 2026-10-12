# The write-ups

Two exercises, each written up twice: once short, once in full.

| file | what it is |
|---|---|
| `BRIEF_COMPARISON_1.md` | comparison 1 in one page: the numbers and what they mean |
| `COMPARISON_1_FULL.md` | comparison 1 in full: the labelled sample, every label explained, the procedure, and what the results say about the tool |
| `BRIEF_COMPARISON_2.md` | comparison 2 in one page |
| `COMPARISON_2_FULL.md` | comparison 2 in full, including why a developer would want this tool at all |
| `DESIGN.md` | the design end to end: the three lists, the queue, the orchestration gap, and where each safety risk lives |

## The short version of both

**Comparison 1** asks whether the tool flagged the right things, decision by decision, against an
answer key. It found both of the run's surfacing-worthy moments, put both on the right surface, and
named the right preference, metric and safety risk every time it spoke. It delivered one of the two.
Its understanding is ahead of its delivery.

**Comparison 2** asks whether the project came out better, judged by the real test suite. Identical
result at identical wall clock, with two interruptions across 147 judge calls. It measures the
absence of an obvious cost, not a benefit.

## What neither establishes

Two golden positives is not a sample. The figures did not reproduce on a second recording. There is
one run per arm, so there is no effect size. Nothing was demonstrably prevented: the stand-in
developer blocked one real thing and the official score did not move. And the answer key shares an
author with the system being graded.
