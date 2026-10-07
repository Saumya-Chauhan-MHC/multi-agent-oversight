# Experiments

Each scenario is one directory with a `scenario.py` that says only what is specific to it: how to
set the task up, the prompt, how to score, and, for the offline replay, the user's lines and which
tool calls count as violating. Everything else is shared.

| path | what |
|---|---|
| `run.py <scenario>` | one run, scored: `<scenario>/runs/<path>/result.json` |
| `batch.py <scenario>` | many runs in parallel (`--vary key=a,b`, `--reps`); skips runs that exist |
| `replay.py <scenario>` | recorded runs through the oversight tool's gates, offline |
| `harness/` | `docker.py` (container in two steps), `claude.py` (Claude Code headless or interactive, run checks), `hook.py` (PreToolUse: log, Bash into the container, lead may not act in multi), `runner.py` (Scenario base class and the run loop), `oversight_live.py` (install the tool, answer holds), `gates.py` (replay core) |
| `delegation_laundering/` | Impossible-SWEbench: cheating when told not to. Tasks used: `django__django-16032`, `django__django-12273`, `django__django-16485`, `sympy__sympy-18189` |
| `stale_merge/` | miscoordination: two tickets, two worktrees, one merge. `tasks.py` has the tickets and hidden tests |
| `port_kill/` | conflict: the user's dev server holds the port both tickets' smoke scripts want |

## Setup

Needs Docker, a logged-in `claude`, and native arm64 SWE-bench images.

```bash
uv venv --managed-python --python 3.12 .venv
uv pip install --python .venv/bin/python "swebench>=4,<5" huggingface_hub pyarrow pandas
```

## A run

```bash
.venv/bin/python run.py port_kill --dummy clean                 # pipeline check, no model
.venv/bin/python run.py port_kill --pref plain --model claude-sonnet-4-5-20250929 --rep 0
.venv/bin/python run.py <scenario> --help                       # its own flags
.venv/bin/python batch.py delegation_laundering --vary instance=A,B --vary cond=multi --reps 3 --jobs 3 -- \
    --model claude-sonnet-4-5-20250929 --prompt plain --exp NAME
(cd delegation_laundering && ../.venv/bin/python judge.py)     # judge every run without a judge.json
```

Flags every scenario has: `--model`, `--rep`, `--exp` (groups runs: `runs/<exp>/...`), `--timeout`,
`--dummy`, `--keep` (keep container and workspace), and the oversight flags below.

Claude Code runs on the host against a workspace under `~/.cache/<scenario>_ws/`, outside this repo so
it never loads this repo's CLAUDE.md. The task's repo is copied out of its image and mounted back at
`/testbed`; `harness/hook.py` sends every Bash call into the container and logs every tool call with
the agent that made it to `tools.jsonl`. In the multi condition the lead may not edit or run anything,
so all work goes through subagents. Every run records `models_used` and errors on a mismatch: Claude
Code silently remaps retired models.

## With the oversight tool, live

`--oversight` installs `overlay/` into the workspace (excluded from git), runs `ctl.py init` with q1 =
the scenario's rule (`--rules` overrides it) and the defaults for the rest, and copies the tool's
judgements, events and answers to `<run>/oversight/` at the end.

```bash
# a simulated user who declines every held spawn with the scenario's note
.venv/bin/python run.py port_kill --pref plain --model claude-sonnet-4-5-20250929 --exp live_sonnet45 --oversight --answer no
# you answer, from another terminal (the run prints how)
.venv/bin/python run.py port_kill ... --oversight --answer human --keep
# Claude Code's own UI in this terminal; holds are asked in its dialog, the graph opens on a hold
.venv/bin/python run.py port_kill ... --oversight --interactive
```

Headless, the tool is in file mode (`-p` has no permission dialog): action holds are denied with the
evidence as the reason, held spawns wait for a decision file. Interactive runs end with `/exit`; the
transcript is converted to `stream.jsonl` so scoring works the same.

## Offline replay

```bash
.venv/bin/python replay.py port_kill --count port_kill/runs/sonnet45/plain-*      # judge calls it would cost
.venv/bin/python replay.py port_kill --events port_kill/runs/sonnet45/plain-*
.venv/bin/python replay.py port_kill --summary port_kill/runs/sonnet45/plain-*    # from saved output
```

Every brief goes through the spawn gate; every subagent Bash/Write/Edit goes through the action gate's
keyword filter and, on a hit, the judge, with the tool's own code and default settings. Judgements are
cached per run by their exact input, so a replay of unchanged runs costs nothing. A replay cannot show
what the agent would have done after a hold.

## Adding a scenario

Make `<name>/scenario.py` with a `Scenario` subclass and `SCENARIO = ...`. Required: `name`,
`run_path`, `setup` (call `harness.docker.start`), `prompt`, `score`. Optional: `add_args`, `dummies`
and `dummy`, `rules` (q1 for live runs), `oversight_lines` and `violating` (replay), `summary_keys`.
`port_kill/scenario.py` is the smallest example.
