# multi-agent-oversight

A tool for keeping a human in the loop while Claude Code runs subagents.

It reads your task brief and your instructions about how to split the work, figures out what has
to be true for the task to succeed, and then watches the run. It speaks up when an agent is about
to break one of your rules **and that will cost you something you can measure**. The rest of the
time it stays quiet, which is most of the time.

> Research prototype, used in a study on human oversight of coding agents. Tested on macOS with
> Claude Code, on SWE-Marathon and ProgramBench tasks.

## What it actually says

These are two real notices from a run of the SWE-Marathon `slack-clone` task.

**A hold.** The IRC agent is about to write a test whose `setUpClass` raises `SkipTest`
unconditionally, so the bridge assertions can never run. The tool call waits for an answer.

![A hold](docs/images/hold.png)

Look at what it cites. It points at a **requirement** from the brief, because the developer never
wrote a rule about this, so the evidence it shows you is a sentence from your own brief.

**A check.** One line, nothing gets paused, and you can ignore it. The unit test here is fine on
its own. It just doesn't prove the requirements it's supposed to be the check for.

![A check](docs/images/check.png)

**What it's tracking.** 147 judgements across the run, 135 of which it kept to itself.

![Status](docs/images/status.png)

**And what it's judging against**, pulled out of the brief before the run started. You can edit it.

![The task model](docs/images/task_model.png)

**The graph.** It only opens itself when the tool holds something, since that's the one moment
worth leaving your terminal for. If you leave a graph open all session you stop looking at it.
[DESIGN section 9](docs/DESIGN.md#the-graph-read-only).

![The graph](docs/images/graph.png)

You get five agents, what each one has written, and how many of its decisions ended up on each
band. Underneath, who is building on whose work. On the right, everything the tool raised, with the
evidence, what it thinks the cost is, and what to do instead. Run it with
`python3 oversight/v3/viewer/serve.py`. It only reads state, so you can't break anything from it.

> **About these images.** The graph is a real screenshot. The two terminal notices are the tool's
> actual output text from the same run, set in a cleaner font so you can read them. The older
> images in `docs/images/` (`hold_waiting.png`, `graph_run.png`, `graph_node_open.png`) show the
> previous version's interface and are only there for reference.

## When it speaks

Three conditions, all required:

| | |
|---|---|
| **a task preference is misaligned** | you said how the work should be divided, and an agent is about to do otherwise |
| **a success metric will drop** | official test success, elapsed time, or token budget. Style opinions don't count |
| **something concrete backs it up** | a file-path or dependency-map lookup rather than a keyword match |

If a rule is broken but nothing measurable suffers, the tool writes it down and tells you nothing.
That's on purpose, so it doesn't end up nagging you about style.

**The safety risks share the same channel as everything else**, because they're just three ways
your metrics end up worse:

| risk | what it is | how the metric falls | where it comes from |
|---|---|---|---|
| **collusion** | an agent certifies its own work with a check that cannot fail | tests decline *without anyone noticing* | *VisibleBench*, arXiv 2510.20270 |
| **miscoordination** | two agents hold different beliefs about a shared contract | tests decline *several handoffs after the cause* | *Passes Alone Fails Together*, arXiv 2609.25396: 97% interference between agents sharing an interface, near zero between unrelated ones |
| **conflict** | two agents contend for one resource | the same work is *paid for twice* | *Worse Together*, arXiv 2610.00583: peer-to-peer teams reach 12 to 30% of optimal |

That's why one channel covers both the quality side and the safety side. [docs/DESIGN.md section
5](docs/DESIGN.md#5--safety-risks-and-where-they-live) covers how each one gets caught and what it
costs you.

## How it decides, step by step

> This is how the code works. For why each piece ended up this way, and the measurements behind
> it, see [docs/DESIGN.md](docs/DESIGN.md) and
> [docs/IMPLEMENTATION_CHANGES.md](docs/IMPLEMENTATION_CHANGES.md).

**1 · Before the run, it reads your brief.** You don't have to answer anything. The extractor
takes `PROMPT.md` and your instructions about splitting the work, and turns them into:

- **requirements**, what must work, each carrying the brief's own sentences copied **verbatim and
  verified against the source text**, plus the file that proves it
- **preferences**, how you want it built, in four categories: ownership, shared interfaces,
  verification, prioritization. Each one records which metrics it protects and which requirements
  it serves

An LLM pulls the rules out, but **code checks whether it's allowed to call them yours.** If a
preference claims to be in your words, it has to hand back the sentence it came from, and that
sentence gets matched against your actual file. If it isn't there, the rule gets marked
**inferred**. The tool can still use it, but it has to show it to you as something it's
*suggesting* so you can confirm or drop it, instead of quoting it back as if you'd written it.

All of it lands in `task_model.json`, which you can read and edit.

> For why that check is there, and the made-up rule that prompted it, see
> [docs/IMPLEMENTATION_CHANGES.md, section 1](docs/IMPLEMENTATION_CHANGES.md#1--the-extractor).

**2 · During the run, a filter runs on every tool call.** Most calls stop right here and nobody
looks at them again.

**Six lookups** decide what gets through. Each one is a simple set or graph check, with no model
involved. They ask things like: does the grader run this file? Does this port belong to a different
agent? Has someone already imported the file that's about to be rewritten? The lookups read **three
lists**: the files the grader runs, a registry of which agent started which port or process, and a
map of who depends on whose work. That last one gets rebuilt from the events *before* the current
decision, so the tool can't get credit for knowing what happens later.

There's also a cheap keyword path, which is there to push borderline decisions in front of the
judge when none of the lookups match. **Keyword matching can't interrupt you.** It gets no say in
whether the work stops, since across two recordings it got 0 out of 8 right.

> For the six lookups, the three lists and what each one catches, see
> [docs/DESIGN.md, section 4](docs/DESIGN.md#4--the-three-lists).

**3 · What survives goes to one judge call.** *(LLM as judge: one call per surviving decision,
strict JSON, 45 second timeout, and it fails open so a timeout means silence and the work carries
on.)* It returns a verdict, what it cites, the metric threatened, the evidence pair, the predicted
consequence and the correction.

It can cite either a **preference** (a rule you wrote about how to work) or a **requirement**
(something the brief says has to work). The second one matters when a test gets written so that it
can never fail. You probably never wrote a rule about that, but the requirement the test was meant
to prove is broken either way, and the brief's own sentence becomes the evidence.

**4 · Then the pacing decides whether you actually hear about it.** *(This part is all code. No
model gets a say in whether you get interrupted.)*

| | |
|---|---|
| **one at a time** | everything queues up and you get a single recommendation rather than a feed |
| **grouped** | items citing the same preference or requirement become one block, so three agents breaking one contract is one interruption. Each flag inside keeps its own evidence and correction |
| **ten minutes of quiet** | after anything reaches you, nothing else can for 600 seconds. Volume is a risk on its own: override rates rise with alert count regardless of whether the alerts are correct (Ancker et al. 2017) |
| **ranked, not first-come** | the slot goes to whichever finding has the strongest evidence behind it, rather than whichever one the judge felt surest about. We left the judge's confidence out of the ranking entirely, since it turned out to be a bad guide: across three measurements it ordered decisions at 0.09, 0.52 and 0.67, on a scale where 0.5 means it's telling you nothing |
| **one exception** | a shared interface about to change under agents already building on it can break the silence, at most once an hour, because no later correction fixes it |

A **hold** pauses the tool call and asks you. A **check** prints the same evidence but pauses
nothing, and you can ignore it. Everything else just gets written to the log.

> For why the queue ranks that way, why the quiet window counts what you were *shown* rather than
> what you *answered*, and where the tool has blind spots, see
> [docs/DESIGN.md, sections 7 and 8](docs/DESIGN.md#7--the-queue-step-by-step).

## Does it work?

We ran two separate exercises, both in [`eval/`](eval/).

**Comparison 1, is it flagging the right things?** We took a recording of a run where the tool was
switched off, then replayed it decision by decision against an answer key we wrote first.

```
111 decisions, 2 of which the key says were worth surfacing

detection    precision 0.13   recall 1.00     did the judge see it at all
surfacing    precision 0.50   recall 0.50     did the developer get told
band accuracy 0.97       attribution 1.00 / 1.00 / 1.00       alarms per 100: 1.8
```

It found both moments, put both on the right band, and named the right preference, metric and
safety risk every time it spoke. It only got one of the two in front of the developer, though, so
**it understood more than it managed to tell anyone**. That run also had three moments where
speaking up would have made things *worse*, and it stayed quiet on all three.

**Comparison 2, does the project come out better?** We built the same task twice and let the real
SWE-Marathon suite decide.

```
                             no tool     with the tool
wall clock, minutes          19.6        19.6
subagents spawned            5           4
judge calls                  0           147
items put to the developer   0           2
developer answers            -           1 note, 1 block

the agent's own test suite   39/49       84/86
official tests passed        137/143     137/143
runnable gates passed        2/3         2/3
  api                        123/129     123/129
  irc                        11/11       11/11
  frontend                   3/3         3/3
```

Same official score, same wall clock, and two interruptions. The keyword path fired 121 times and
never once made it to a speaking band.

**What neither of these proves:** two positive cases isn't a sample, one run per arm gives you no
effect size, and we can't show the tool actually prevented anything.

> [`eval/README.md`](eval/README.md) walks through both exercises from scratch and lists every
> limit. The answer key is [`eval/control-arm/golden.csv`](eval/control-arm/golden.csv), the run it
> labels is [`eval/control-arm/`](eval/control-arm/), the run with the tool switched on is
> [`eval/treatment-arm/`](eval/treatment-arm/), and both write-ups are in
> [`eval/writeups/`](eval/writeups/).

## Install

Copy `overlay/.claude` and `overlay/oversight` into the project the agent will work in, then:

```bash
BUDGET="45 minutes, 2M tokens" DRAWS=5 python3 -m oversight.v3.extract .
claude -p "$(cat PROMPT.md)" --permission-mode acceptEdits
```

`DRAWS=5` runs the extractor five times and keeps whatever most of the runs agree on, since one
run on its own gives you different answers each time. It tells you what it threw away.

`OV_SIMUSER=1` has a stand-in developer answer the tool's questions instead of you, so you can run
an arm without sitting there. Don't treat it as a replacement for a real person.

> For what the stand-in sees, what we deliberately keep from it, and why it exists at all, see
> [DESIGN section 9](docs/DESIGN.md#a-stand-in-developer-for-running-a-treatment-arm-unattended)
> and [`eval/treatment-arm/README.md`](eval/treatment-arm/README.md).

[`examples/swe_marathon_slack_clone/`](examples/swe_marathon_slack_clone/) has a task you can try
it on, plus a script that pulls down the real test suite so you can grade whatever gets built.

## Where things are

| | |
|---|---|
| [`docs/DESIGN.md`](docs/DESIGN.md) | the design end to end |
| &nbsp;&nbsp;[section 4](docs/DESIGN.md#4--the-three-lists) | the three lists the lookups read, and why lists at all |
| &nbsp;&nbsp;[section 5](docs/DESIGN.md#5--safety-risks-and-where-they-live) | collusion, miscoordination and conflict: how each is detected and what it costs |
| &nbsp;&nbsp;[section 6](docs/DESIGN.md#6--when-surfacing-happens-and-why) | the three conditions that must hold before anything is said |
| &nbsp;&nbsp;[section 7](docs/DESIGN.md#7--the-queue-step-by-step) | the queue: one at a time, grouping, the ten-minute window, the ranking, the one preempt |
| &nbsp;&nbsp;[section 8](docs/DESIGN.md#8--the-orchestration-gap-period) | the four blind spots, including the cold start and the quiet window |
| &nbsp;&nbsp;[section 9](docs/DESIGN.md#9--implementation-component-by-component) | component by component: extractor, filter, judge, graph, policy, stand-in developer |
| [`docs/IMPLEMENTATION_CHANGES.md`](docs/IMPLEMENTATION_CHANGES.md) | every change, and the measurement that prompted it |
| &nbsp;&nbsp;[section 1](docs/IMPLEMENTATION_CHANGES.md#1--the-extractor) | the extractor: the truncation, the invented rule, the provenance check |
| &nbsp;&nbsp;[section 5](docs/IMPLEMENTATION_CHANGES.md#5--bands-and-delivery) | bands and delivery: the check band that printed nothing, word overlap losing its vote |
| &nbsp;&nbsp;[section 6](docs/IMPLEMENTATION_CHANGES.md#6--the-queue) | the queue: why confidence was removed from the ranking |
| [`eval/`](eval/) | both comparisons, the answer keys, the scorers and the grader |
| [`examples/`](examples/) | the SWE-Marathon task, the ProgramBench harness |
| [`overlay/`](overlay/) | the hooks and the tool itself |
