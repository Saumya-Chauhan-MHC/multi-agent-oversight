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

## The shape of one decision

1. An agent is about to act. `PreToolUse` fires.
2. Can this act change anything? `Write`, `Edit`, `MultiEdit`, `Task`, `Bash`. A `Read` exits here.
3. Read the task description. No task text, no tool.
4. Work out which files the action touches. An edit names its file; a shell command has its paths
   read out of the command text.
5. Look up what other agents already wrote to those same files.
6. Decided this exact thing before, in the same context? Reuse it.
7. Ask the judge once. Yes or no, and a yes must quote the task.
8. No, and the agent never knows the tool is there. This is almost every action.
9. Yes, and you have already answered about that sentence: reuse your answer.
10. Otherwise you are asked. Block, or let it through.
11. Block denies the call, with your reason.
12. Allow splits the correction. What this agent can fix in its own checkout goes back to it now.
    What only another agent's checkout can fix is posted to that agent and injected on its next
    tool call; if that agent has finished, it falls back to the orchestrator.

## State of the evidence

v5 has not been run on a benchmark. Every number reported so far describes v4.
