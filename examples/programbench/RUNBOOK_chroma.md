# Runbook: chroma task in local Claude Code with the oversight viewer (T0, 90-minute cap)

Task: alecthomas__chroma.8d04def. One session today, session 2 later with `claude --resume`.
Every phase says what to run, what you should see, and what to do if you do not see it.

## Phase 0: install what is needed (once), and where every file comes from

### 0.1 Docker Desktop (runs the ProgramBench task image; the reference binary lives in it)
- Get it: https://www.docker.com/products/docker-desktop/ , pick "Mac with Apple chip" or "Mac with Intel chip",
  open the .dmg, drag to Applications, open Docker, accept the terms, wait for "Docker Desktop is running"
  (whale icon in the menu bar stops animating).
- Apple Silicon only: Docker menu > Settings > General > tick "Use Rosetta for x86_64/amd64 emulation
  in Apple Virtual Machine Framework" > Apply & restart. If the tick box is greyed out, install Rosetta first:
  `softwareupdate --install-rosetta --agree-to-license`.
- Check, in Terminal:

      docker --version                                            # prints "Docker version ..."
      docker run --rm --platform linux/amd64 alpine uname -m      # prints x86_64

  If the second command prints an error about the platform, the Rosetta setting is off.
- File sharing: Docker can mount folders under /Users by default. Keep the project under your home folder.

### 0.2 Claude Code (the agent under study)
- Get it: https://docs.claude.com/en/docs/claude-code/overview (the install command on that page, e.g. the
  native installer `curl -fsSL https://claude.ai/install.sh | bash` or `npm install -g @anthropic-ai/claude-code`).
- Check:

      claude --version        # prints a version
      claude                  # first run asks you to log in; log in, then type /exit

### 0.3 python3 (runs the hooks, the viewer, the smoke check)
- macOS ships it. Check: `python3 --version` (3.9 or newer). No packages needed; everything is standard library.

### 0.4 programbench (only for grading, can be installed later)
- Either `pip3 install programbench` (check: `programbench --help`)
- or install uv (https://docs.astral.sh/uv/ , `curl -LsSf https://astral.sh/uv/install.sh | sh`); grade.sh then runs `uvx programbench`.
- The hidden tests are downloaded by programbench from HuggingFace at grading time (dataset
  programbench/ProgramBench-Tests). Nothing to fetch by hand. To pre-download: `programbench blob sync alecthomas__chroma.8d04def`.

### 0.5 The files, and where each comes from
| File | Where it comes from | How you get it |
|---|---|---|
| pb_exact.zip (setup.sh, grade.sh, overlay/, README, CHANGES) | written by me in this chat | download from the chat, put it under your home folder |
| the task image programbench/alecthomas_1776_chroma.8d04def:task_cleanroom_v6 | Docker Hub, org "programbench" | setup.sh pulls it |
| the reference binary and the bundled docs | inside that image at /workspace | setup.sh copies them into task/ |
| the task's rules and instructions (CLAUDE.md, PROMPT.md) | mini-swe-agent, src/minisweagent/config/benchmarks/programbench.yaml (github.com/SWE-agent/mini-swe-agent) | already in overlay/, adapted as listed in CHANGES.md |
| task metadata (repo, commit, language, hidden test names) | github.com/facebookresearch/programbench, src/programbench/data/tasks/alecthomas__chroma.8d04def/ | only for reading; nothing to download |
| hidden tests | HuggingFace programbench/ProgramBench-Tests | programbench eval fetches them |
| our tool: hooks (.claude/), viewer and smoke cases (oversight/) | in pb_exact.zip under overlay/ | setup.sh copies them into task/ |

## Phase 1: set up the task folder

    cd ~                     # or any folder under your home
    mkdir -p research && cd research
    unzip ~/Downloads/pb_exact.zip
    cd pb_exact
    chmod +x setup.sh grade.sh
    ./setup.sh alecthomas__chroma.8d04def

What you should see, in order:
- `== 1/6 pulling programbench/alecthomas_1776_chroma.8d04def:task_cleanroom_v6` and Docker's layer progress (a few minutes).
- `== 2/6 starting reference container pb_ref`
- `== 3/6 copying the official workspace out of the image`, then an `ls -la` of task/ showing `executable` and the docs the image ships.
- `== 4/6 installing the reference wrapper`
- `== 5/6 copying the study overlay (CLAUDE.md, PROMPT.md, hooks, viewer)`
- `== 6/6 probing toolchains in the grading image`
- `== smoke test of the reference wrapper:` then the first lines of chroma's --help (usage line, flags like --list, -l/--lexer, -f/--formatter, -s/--style).
- `Done. Task folder: /Users/<you>/research/pb_exact/task`

If it stops:
- "task already exists": `mv task task_old`, rerun.
- "no ./executable in /workspace": instance id misspelled.
- platform error on pull or run: Rosetta setting (0.1) is off.
- smoke test prints nothing: `docker ps` (is pb_ref listed?), then `docker exec pb_ref /workspace/executable --help`. Send me the output.

What is now in task/ (`ls -a task`):
- `executable` (wrapper to the real binary), the bundled docs, `CLAUDE.md`, `PROMPT.md`
- `oracle/reference` (same wrapper, stable name), `oracle/toolchains.txt`
- `oversight/` (cap_minutes, instance_id, viewer/, tests/; the log files appear once Claude Code runs)
- `.claude/settings.json`, `.claude/hooks/record.py cap.py guard.py`

## Phase 2: test the task (2 minutes, no Claude Code)

    cd ~/research/pb_exact/task
    ./executable --list | head -20                     # lexer list: ABAP, ABNF, ActionScript, ...
    echo 'package main' | ./executable -l go -f json   # JSON token list
    printf 'x = 1\n' > t.py && ./executable t.py; rm t.py   # coloured output; proves file paths reach the container
    ./oracle/reference --version                       # version string
    cat oracle/toolchains.txt                          # must list go
    grep -n "minutes\|Linux x86_64" PROMPT.md          # the two filled-in lines: toolchains, "about 90 minutes"
    cat oversight/cap_minutes                          # 90

If `oracle/toolchains.txt` has no `go` line, stop and tell me.

## Phase 3: test the viewer and hooks with a 3-minute dry run

Terminal 2 (leave it running for the whole day):

    cd ~/research/pb_exact/task && python3 oversight/viewer/serve.py
    # prints: oversight viewer: http://localhost:4173

Open http://localhost:4173 in a browser: "0 events", empty panels.

Terminal 1:

    cd ~/research/pb_exact/task && claude

- "Do you trust the files in this folder?" -> yes.
- Type `/hooks` and enter: hooks listed under SessionStart, UserPromptSubmit, PreToolUse, PostToolUse,
  SubagentStart, SubagentStop, PreCompact, Stop, SessionEnd. Empty list = you started claude outside task/.
- Dry-run prompt (not PROMPT.md):
  `List the files in this folder, run ./executable --list | head -5, then use a subagent to count how many lexers ./executable --list reports.`
  Allow the permission prompts.
- Guard test: `Fetch https://example.com and tell me its title.` -> the tool call is denied with
  "No internet access in this task ...".
- `/exit`

Check:

    wc -l oversight/events.jsonl            # > 10
    cat oversight/session_no.txt            # 1
    python3 oversight/viewer/summary.py     # "session 1: ... tool calls, 1 subagents ..." and the prompt lines

Refresh the browser: S1 in the sidebar, coloured rectangles in the overview, orchestrator node and (if the
subagent ran) one node under it; click a node -> history fills.

If events.jsonl does not exist, test a hook by hand from task/:

    python3 .claude/hooks/record.py session_start <<< '{"session_id":"t","source":"startup"}'
    cat oversight/events.jsonl              # one line

Send me any error text.

Reset the log so the real run starts clean:

    cd ~/research/pb_exact/task
    rm -rf oversight/events.jsonl oversight/checkpoints.txt oversight/session_no.txt oversight/cap_start_*.txt oversight/snap
    ls                                       # remove anything the dry run created (a notes file, say)

Refresh the browser: back to 0 events.

## Phase 4: the real session (90 minutes)

    cd ~/research/pb_exact/task && claude --permission-mode acceptEdits

- Paste the whole of PROMPT.md as the first message (open it, select all, copy). Note the time.
- Do not steer. Only allow permission prompts (choose "always allow" for Bash when offered).
- Watch the viewer: first purple Write (core started), first blue spawn (first subagent), side-by-side
  nodes (parallel), orange (compaction). Note the minute of each.
- 80 min: tool results carry the low-time block; the agent may write AGENT_REPORT.md.
- 90 min: every tool call denied with "Session time cap (90 min) reached"; the agent stops and summarises.
- `/exit`

## Phase 5: check the result

    cd ~/research/pb_exact/task
    ./compile.sh                                  # builds the agent's program; ./executable is now its build
    python3 oversight/tests/run_diff.py           # k/10 cases match the reference (oracle/reference)
    python3 oversight/viewer/summary.py           # tool calls, subagents + files, compactions
    # screenshot the viewer

Optional official score (slow under emulation):

    cd ~/research/pb_exact && ./grade.sh          # or ./grade.sh pack and eval run/ on a Linux x86_64 machine

Send me: oversight/events.jsonl, oversight/checkpoints.txt, the screenshot, summary.py output, eval.json if graded.

## Phase 6: session 2 (later, same folder)

    docker ps                                     # pb_ref listed? if not: docker start pb_ref
    cd ~/research/pb_exact/task && python3 oversight/viewer/serve.py     # terminal 2
    cd ~/research/pb_exact/task && claude --resume                         # terminal 1, pick the session

New 90-minute cap, second column in the viewer. Do not paste PROMPT.md again; say nothing, or "continue" if it waits.
Afterwards summary.py adds the handoff line (session-1 files that session 2 read and re-wrote).

## Reset for a fresh run

    cd ~/research/pb_exact
    docker rm -f pb_ref
    mv task task_run1
    ./setup.sh alecthomas__chroma.8d04def
