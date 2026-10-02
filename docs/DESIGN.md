# Design

Both components read one thing: the rules you write at init, in your words.

## Component 1: alignment flags

A confidence is produced only when the judge runs, and the judge runs on three events:

1. **A delegation.** Every `Task` call, before the subagent exists. Skipped if you hold a standing
   approval for that parent, if you already answered the same decision, or if there are no rules yet.
2. **A tool call that touches your rules' words.** Any `Bash`, `Write` or `Edit` by a subagent or by
   the orchestrator. Words from your rules are matched against the command and path. No overlap, no
   judge call. A hit means one call, cached by command and rules.
3. **A declared event.** `ctl.py declare` for a merge, reassignment or re-division, which fire no hook.

Reads, searches, `ls`, repeats of an identical action and subagent finishes are never judged.

The judge gets your rules, the brief or command, the child's own brief, and the parent's state. It
returns a verdict, a confidence, and evidence that quotes your rule against the text that conflicts
with it.

When something is shown:

| | |
|---|---|
| departs, confidence 0.85 or more | work pauses, you answer |
| departs, confidence 0.50 to 0.85 | one line, nothing pauses |
| no rule covers the case | one line, nothing pauses |
| fits, or the judge failed | nothing |

Four exceptions: a subagent's own action holds only at 0.85 or more and is otherwise silent; the
orchestrator's own actions never hold; after five answered holds, if you accepted more than 30 percent
of them, holds become checks; if you answered q4 with "never", holds become catch-up items.

## Component 2: catch-up

A count of what you have not seen: departures never shown, checks not answered, repeats of a decision
you declined at double weight, one point per ten files written in nodes you have not opened, and
subagents that finished while you were away. q5 sets the threshold at 3, 5 or 8. The count is taken
when a subagent finishes. The line prints on the next tool result, because Claude Code does not
display SubagentStop output. Nothing pauses. Any look resets the count.

## Terminal and graph

| | terminal | graph |
|---|---|---|
| fits | nothing | a mark on the node |
| check | one line | an item to answer later |
| hold | evidence, three choices, agent waits | opens on that node |
| catch-up | one line with the counts | the items behind them |

The graph opens by itself only on a hold.

![graph](images/graph_run.png)

A node opens to show what it owns, the decision that started it, and what it did that departed:

![node](images/graph_node_open.png)

## Run it on a SWE Marathon task

See [examples/swe_marathon_slack_clone](../examples/swe_marathon_slack_clone) for the task used in
[CALIBRATION.md](CALIBRATION.md), with the rules it was judged against.

```bash
mkdir ~/task_run && cd ~/task_run
cp -R <repo>/overlay/.claude <repo>/overlay/oversight .
cp <repo>/examples/swe_marathon_slack_clone/PROMPT.md .

python3 oversight/ctl.py init           # five questions
python3 oversight/ctl.py lines          # check they registered
python3 oversight/viewer/serve.py 4173 &
claude --permission-mode acceptEdits "$(cat PROMPT.md)"
```

Answer holds as they appear. During or after: `ctl.py status`, `judgements`, `catchup`, `lines`.

Judgements are in `oversight/judgements/`, events in `oversight/events.jsonl`, answers in
`oversight/control/interventions.jsonl`.
