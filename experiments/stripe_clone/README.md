# stripe-clone arms

SWE-Marathon's `stripe-clone`, used instead of `slack-clone` because it grades better here.
slack-clone has five gates and two of them (crash, chaos) need `/proc` and never ran on this
machine, so 40% of its suite was dark. stripe-clone has twelve gates, all twelve run natively,
and the reference solution scores 82 of 83, so the ceiling is known.

| file | what it does |
|---|---|
| `setup_arm.py` | builds an arm and runs it. `--tool` wires v5, `--tool --v3` wires the version on main, `--model` sets the agents' model |
| `grade.sh` | boots the arm with `bash start.sh` and runs all twelve gates |
| `preflight.py` | checks an arm before its numbers are believed |

## Run it

```
python3 setup_arm.py h1_notool --model claude-haiku-4-5-20251001 --minutes 60
python3 setup_arm.py h2_v3 --tool --v3 --model claude-haiku-4-5-20251001 --minutes 60
python3 setup_arm.py h3_v5 --tool      --model claude-haiku-4-5-20251001 --minutes 60
python3 preflight.py h1_notool h2_v3 h3_v5      # must pass before grading
./grade.sh h1_notool h1
```

## Why the agents run on a weaker model

With Sonnet the control scored 82 of 83, the same as the reference solution. A tool cannot show
an improvement on a task the baseline already solves completely, so every comparison was dead
before it started. Haiku lowers the baseline and makes the question real. The judge and the
stand-in developer stay on sonnet in every arm, so oversight quality is held constant and the
only thing varying is the agent doing the work.

## Why preflight exists

Two bugs so far were found by reading code, not by anything failing, and both quietly favoured a
particular answer.

A judgement was dropped for any action naming no file. `flag = dict(target=mine, ...)` read a
loop variable bound only inside `for mine in paths`, a Task spawn carries no path, and the
NameError was swallowed by the gate's fail-open handler. One arm recorded 44 judgements with 0 of
them Task, against five subagent spawns: every spawn in a multi-agent run was judged and thrown
away.

The grader hardcoded `python -m app`, copied from the skeleton. The task says `bash /app/start.sh`
runs the service and that "storage, framework, process model, and internal architecture are open".
One control arm restructured to a root-level `main.py` under uvicorn and updated `start.sh` to
match, which is allowed. The old grader would have scored it zero for a legal choice while both
tool arms, which happened to keep the skeleton layout, booted fine.

`preflight.py` checks the harness rather than the tool: that `start.sh` is not the untouched
skeleton, that the hooks named in `settings.json` are wired and present, that judgements reconcile
against the tool calls recorded (the check that catches the dropped-judgement class), and that the
fail-open crash log is empty. A failure is a reason to fix and rerun, not to annotate the result.
