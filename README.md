# multi-agent-oversight

A tool for keeping a human in the loop while Claude Code runs subagents. It reads five rules you
write at the start, judges every delegation and every subagent action against them, and stops the
work only when it is confident one of your rules is being broken. The rest of the time it stays
quiet and counts what you have not seen.

![The graph after a run](docs/images/graph_run.png)

*After a run: the orchestrator and the subagent it spawned, the rules in your own words, nothing
waiting for you.*

> Research prototype, used in a study on human oversight of coding agents. Tested on macOS with
> Claude Code 2.1.287, on SWE Marathon and ProgramBench tasks.

## The two components

**Alignment flags**

| | |
|---|---|
| fires on | a delegation, or a tool call whose text matches a word in your rules |
| cost when it does not fire | none, the match is a string check |
| the judge is given | your rules, the brief or command, the child's own brief, the parent's state |
| it returns | a verdict, a confidence, and evidence quoting your rule against the conflicting text |
| departs at 0.85 or more | the work pauses and you answer |
| departs at 0.50 to 0.85 | one line, nothing pauses |
| no rule covers it | one line, nothing pauses |
| fits, or the judge failed | nothing, the node is marked |
| never | interrupts on a fit, or asks twice about the same decision |

**Catch-up**

| | |
|---|---|
| fires on | a subagent finishing |
| cost | none, it is arithmetic over counters |
| counts | departures never shown (1 each), checks not answered (1), repeats of a decision you declined (2), files written in nodes you have not opened (1 per 10), subagents finished while you were away (1) |
| your threshold | 3, 5 or 8, from q5 |
| past the threshold | one line on the next tool result |
| resets | any look at the graph |
| never | pauses anything |

The band thresholds, the four exceptions to them, and the catch-up formula are in
[docs/DESIGN.md](docs/DESIGN.md).

## What the terminal shows, and what the graph shows

| | terminal | graph |
|---|---|---|
| a decision that fits | nothing | a mark on the node |
| a check | one line, nothing paused | an item you can answer later |
| a hold | the evidence, three choices, the agent waits | opens on that node |
| catch-up | one line with the counts | the items behind those counts |

The graph opens by itself only on a hold. Click a node to see what it owns, the decision that started
it, and what it did that departed:

![A node opened](docs/images/graph_node_open.png)

## Quick start

```bash
mkdir ~/task_run && cd ~/task_run
cp -R <this repo>/overlay/.claude <this repo>/overlay/oversight .
cp <your task instruction> PROMPT.md

python3 oversight/ctl.py init          # five questions, about a minute
python3 oversight/ctl.py lines         # check the rules registered
python3 oversight/viewer/serve.py 4173 &
claude --permission-mode acceptEdits "$(cat PROMPT.md)"
```

Answer holds in the terminal as they appear. Nothing else needs you. What the tool shows afterwards,
from one real run:

```
$ python3 oversight/ctl.py status
lines        5 (q1a, q1b, q1c, q2, q3)
involvement  ask   catch-up threshold 3   surface ask
counters     outdatedness 0 = 0 departures + 0 unanswered checks + 0 repeats x2
             + 0 (0 unseen edits, 1 per 10) + 0 finished while away
judgements   9  {'silent': 9}

$ python3 oversight/ctl.py judgements 3
  silent fits      0.90  orchestrator                 -> Build Huddle SPA frontend
  silent departs   0.60  Build Huddle SPA frontend    -> web/tests/mock_server.py   q1c
  silent fits      0.60  Build Huddle SPA frontend    -> timeout 300 python3 web/tests/ui_test.py

$ python3 oversight/ctl.py lines
  q1a: "no subagent installs packages" (init, confirmed)
  q1b: "launchers and anything in bin/ are mine" (init, confirmed)
  q1c: "a subagent never edits a file it does not own" (init, confirmed)
  q2:  "one subagent per package or component" (init, confirmed)
  q3:  "each subagent runs its own tests before reporting done" (init, confirmed)
```

A full worked example, including the rules used and the task text, is in
[examples/swe_marathon_slack_clone](examples/swe_marathon_slack_clone).

## Terminal control

```bash
python3 oversight/ctl.py lines         # the rules, in your words, as they grow
python3 oversight/ctl.py status        # bands, counts, precision, catch-up score
python3 oversight/ctl.py judgements 10 # the last ten decisions and their verdicts
python3 oversight/ctl.py catchup       # what piled up since your last look
python3 oversight/ctl.py pending       # anything waiting for an answer
python3 oversight/ctl.py answer <id> yes|no "<note>"
python3 oversight/ctl.py accept-all <parent>   # stop being asked about one parent
python3 oversight/ctl.py declare --kind merge --what "..." --why "..."
```

## Docs

- [docs/DESIGN.md](docs/DESIGN.md) what triggers each component, what the terminal and the graph
  show, and how to run it on a SWE Marathon task
- [docs/CALIBRATION.md](docs/CALIBRATION.md) every decision from one live run, which calls were
  right, which were wrong, what we changed, and the re-test
- [examples/swe_marathon_slack_clone](examples/swe_marathon_slack_clone) the task used in that run

## Also in the box

The recorder writes every prompt, tool call, subagent start and stop, subagent brief, and file read
or written to `oversight/events.jsonl`, with content hashes. File checkpoints (`cNNN`) are taken
before every file change and workspace checkpoints (`wNNN`) at every human decision, so any state can
be restored byte for byte.

## Testing

```bash
python3 oversight/tests/test_align.py       # the gate end to end
python3 oversight/tests/eval_judge.py       # 12 labelled spawn cases
python3 oversight/tests/eval_judge.py actions   # 6 labelled action cases
bash demo.sh                                # a scripted run of every feature
```

## License

MIT.
