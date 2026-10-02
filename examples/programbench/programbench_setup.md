# pb_exact: run an exact ProgramBench task in Claude Code and record the work DAG

Main task: `alecthomas__chroma.8d04def` (syntax highlighter, Go), 90-minute sessions.
Fallbacks with the same commands: `boyter__scc.515f91c` (code counter), `tomnomnom__gron.88a6234` (small; pipeline smoke test only).

Contents

    setup.sh      one-time setup for one task instance (docker pull, reference container, task/ folder)
    grade.sh      pack task/ as a submission and run the official hidden tests
    overlay/      what setup.sh copies into task/: CLAUDE.md, PROMPT.md, .claude/ (hooks), oversight/ (viewer, smoke cases)
    CHANGES.md    every difference from the official ProgramBench setup, and why
    task/         created by setup.sh; the folder you open Claude Code in

Requirements: macOS (or Linux), Docker Desktop running (Apple Silicon: Settings > General > "Use Rosetta
for x86_64/amd64 emulation" on), Claude Code, python3. For grading also `pip install programbench`
(or have `uv`; `grade.sh` then uses `uvx programbench`).

## Session 1, step by step

1. Set up (once per instance; a few minutes, mostly the image pull)

       unzip pb_exact.zip && cd pb_exact
       chmod +x setup.sh grade.sh
       ./setup.sh alecthomas__chroma.8d04def

   Last lines: a smoke test where `./executable --help` answers from inside the container (you should
   see chroma's usage text with --list, --lexer, --formatter, --style), and the path of task/.
   To change the cap: `CAP_MINUTES=60 ./setup.sh ...`.

2. Look at what the agent will see (1 minute)

       cd task
       ls                          # executable (wrapper), the bundled docs, CLAUDE.md, PROMPT.md, oracle/, oversight/, .claude/
       ./executable --list | head  # the real binary listing its lexers, styles, formatters
       cat PROMPT.md               # the exact first message; cat oracle/toolchains.txt for what the grader can compile

3. Viewer, in a second terminal

       cd task && python3 oversight/viewer/serve.py      # http://localhost:4173 ; refresh the page to re-read the log

4. Start the session

       cd task && claude

   Paste the whole of PROMPT.md as the first message. Then do not steer (T0): no hints, no questions.
   Only answer permission prompts with "allow" (or launch with `claude --permission-mode acceptEdits`
   and allow Bash once) so the run is never blocked on you.
   The timer starts at launch. At 80 minutes every tool result carries the official low-time block
   (write AGENT_REPORT.md); at 90 minutes every tool call is denied and the agent stops.

5. End the session: `/exit`. Then in task/:

       ./compile.sh && python3 oversight/tests/run_diff.py    # 10 smoke cases against the reference (cases_chroma.txt)
       python3 oversight/viewer/summary.py                    # tool calls, subagents, files per session
       # and refresh the viewer

6. Grade with the official hidden tests (531 for chroma; slow on a Mac under emulation)

       cd .. && ./grade.sh            # or ./grade.sh pack, then programbench eval on a Linux x86_64 box

   Result: run/alecthomas__chroma.8d04def/*.eval.json and the `programbench info` table (% tests passed).

7. Send: task/oversight/events.jsonl, task/oversight/checkpoints.txt, a viewer screenshot, and the eval.json if graded.

## Session 2 (same task/ folder)

- harness-native handoff (default): `claude --resume`, pick the session. The resume hook starts a new
  90-minute cap and the viewer opens a second column.
- file-only handoff (control): `claude` fresh, first message:
  "Continue the task described in PROMPT.md. Read AGENT_REPORT.md and the workspace first."

After session 2, `summary.py` prints the handoff line: how many session-1 files session 2 read and re-wrote.

## What to expect in the viewer and what causes it

- Sessions (A): one entry per launch with tool-call count, subagent count, files changed.
- Overview strip: one rectangle per event in time order (black prompt, light blue Read, green Bash,
  purple Edit/Write, blue spawn, orange compaction, grey stop). Expected shape for chroma: Reads of the
  docs, Bash probes (`--list`, `-l go -f json ...`), then Writes (a Go module: registry, lexer engine,
  formatters), then build/probe/fix loops.
- Work DAG (C): a node under "orchestrator S1" means Claude Code called the Agent tool and a subagent
  started; the box shows its type, the first line of its prompt, files written (w:) and read (r:).
  Side-by-side nodes = parallel subagents. Blue edge = a node read a file another node wrote.
  Red dashed edge = a node re-wrote a file another node wrote earlier.
  For chroma the natural split is per language ("probe X with -f json, write its lexer") and per
  formatter; if that happens you see several sibling nodes each writing its own lexer file and all
  reading the shared token-type / registry files.
- History (D): click a node or rectangle. In T0 nothing opens automatically (no impact notice yet).
- Denials in the terminal: "No internet access in this task ..." (guard) and, at 90 minutes,
  "Session time cap (90 min) reached" (cap).
- No subagent at all is also a result: the orchestrator did everything itself. Note when it happened
  (how far into the session) before deciding whether to run the seeded variant.

## Reset for another run

    docker rm -f pb_ref; mv task task_run1; ./setup.sh <instance_id>

## Variant B: Claude Code inside the container (Linux x86_64 hosts)

    docker run -it --platform linux/amd64 --name pb_in -w /workspace programbench/alecthomas_1776_chroma.8d04def:task_cleanroom_v6 bash
    # inside: install node + claude, copy overlay/ in, skip the wrapper (the real ./executable is right there), then `claude` as above.
