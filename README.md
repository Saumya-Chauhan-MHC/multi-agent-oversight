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

**Alignment flags.** Two hooks fire on their own: one before a subagent is spawned, one before a
subagent runs a command. A keyword filter drops anything your rules do not mention, at no cost. What
is left goes to a judge with your rules, the brief or command, the child's own brief, and the state
of the parent. The judge returns a verdict, a confidence, and evidence that quotes your rule against
the text that conflicts with it. At 0.85 and above the work pauses and you answer. Between 0.50 and
0.65, or when no rule covers the case, you get one line and nothing pauses. Below that, nothing is
shown.

**Catch-up.** A count of what you have not seen: departures that were never shown, checks you did not
answer, repeats of a decision you declined at double weight, one point per ten files written in nodes
you have not opened, and subagents that finished while you were away. When it passes your threshold
you get one line at the next seam in the work. Nothing is paused. Any look resets it.

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

Answer holds in the terminal as they appear. Nothing else needs you.

![The session running](docs/images/cli_session_start.png)

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
be restored byte for byte. The earlier viewer, which draws data and conflict edges and a downstream
impact card, is kept at `oversight/viewer/v1_index.html`.

## Testing

```bash
python3 oversight/tests/test_align.py       # the gate end to end
python3 oversight/tests/eval_judge.py       # 12 labelled spawn cases
python3 oversight/tests/eval_judge.py actions   # 6 labelled action cases
bash demo.sh                                # a scripted run of every feature
```

## License

MIT.
