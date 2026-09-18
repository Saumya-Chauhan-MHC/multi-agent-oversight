# What was changed relative to the official ProgramBench setup, and why

The "official" setup is what the ProgramBench authors ran and score: the mini-swe-agent config
`src/minisweagent/config/benchmarks/programbench.yaml` (the prompts), the runner
`run/benchmarks/programbench.py` (how the container is launched and the submission collected),
and the grader `programbench eval` in facebookresearch/programbench (how the submission is built and
tested). Everything below is a delta from those three files. Nothing about the task content changes:
same image, same reference binary, same docs, same rules text, same hidden tests, same grader.

## A. Things that are identical to the official setup

| Official | Here |
|---|---|
| Docker image `programbench/<owner>_1776_<repo>.<hash>:task_cleanroom_v6` | same image, pulled by `setup.sh` |
| Workspace `/workspace` = reference binary `./executable` (execute-only) + bundled docs | copied out of the same image with `docker cp`, so `task/` holds exactly those files |
| System prompt (task statement + `<RULES>`) | verbatim in `task/CLAUDE.md` (Claude Code reads it at every launch, which is what a system prompt is for) |
| Instance prompt ("Task context / Your task / Independent implementation / Recommended workflow") | verbatim in `task/PROMPT.md`, minus the mini-swe-agent-only parts listed in B4 |
| Deliverable: `./compile.sh` that produces `./executable` in the workspace root | same wording, same contract, same grader |
| Container has no network (`--network none`) | reference container has `--network none`; the agent's own network is blocked by a hook (B6) |
| Hidden tests: fixed suites from HuggingFace, run by `programbench eval` | `grade.sh` packs `task/` the way the official runner does (`tar -czf … -C /workspace .`) and calls the same `programbench eval` |
| Low-time message 10 min before the limit, asking for `AGENT_REPORT.md` for "the next agent" | same text, injected by the `cap.py warn` hook (B7) |
| No mention of subagents, planning or orchestration anywhere | unchanged; whether Claude Code spawns subagents stays organic |

## B. The adaptations

### B1. The agent runs on your laptop, the reference binary runs in the container
Official: the whole agent (mini-swe-agent, bash-only) runs inside the Linux/amd64 container.
Here: Claude Code runs on your Mac in `task/`, and the reference binary, which is linux/amd64 and
execute-only, stays in the container `pb_ref`. `./executable` in `task/` is a 10-line wrapper:

    exec docker exec -i -w /work/<your cwd> pb_ref /workspace/executable "$@"

`task/` is bind-mounted at `/work`, so `./executable somefile.json` inside the container sees the
same file, stdin/stdout are passed through, and exit codes come back unchanged. To the agent it
behaves like a local binary.
Why: Claude Code with hooks, the viewer, your editor and fast native builds are all on the Mac;
running Claude Code inside an emulated amd64 container is possible (see README, variant B) but slow
and awkward. The trade-off is B2 and B5.

### B2. A stable second name for the reference: `./oracle/reference`
Official: the agent is told to make `compile.sh` write `./executable`, i.e. its own build
overwrites the reference. Agents cope by `mv`-ing the reference first (it cannot be `cp`'d: mode 111).
Here: `setup.sh` also installs the wrapper as `./oracle/reference`, and `CLAUDE.md` says so in one line.
Why: two things need the reference after the agent has overwritten `./executable`: session 2 (the
official run never has one) and our own smoke check `oversight/tests/run_diff.py`. Without this,
whether session 2 can still query the reference would depend on whether the session-1 agent happened
to `mv` it. The rules apply to it identically (it is the same wrapper).

### B3. Rules text moved into `CLAUDE.md`, instance text into `PROMPT.md`
Official: system template + instance template are two prompts sent by the runner.
Here: `CLAUDE.md` = the system template (Claude Code loads it automatically at every launch, so it
is present in session 2 as well); `PROMPT.md` = the instance template that you paste as the first message.
Why: this is the only faithful mapping onto Claude Code's prompt structure; nothing was reworded.

### B4. Removed from the instance prompt (mini-swe-agent mechanics that do not exist in Claude Code)
The "Command Execution Rules" section (one bash call per turn, subshell semantics, the
`COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT` command), the sed / heredoc "Useful command examples", the
`<system_information>` block, and the tmux note for TUIs. Claude Code has its own tools and its own
way of ending a session, so this text would only confuse. The reference to "the full rules in the system
prompt above" became "in CLAUDE.md".

### B5. Two lines added to the instance prompt
(a) "`compile.sh` will be run on a Linux x86_64 machine without internet, where these toolchains are
installed: …" (list probed from the image by `setup.sh`).
Why: officially the agent discovers toolchains by running `which` in the same container that grades
it. On the Mac, `which go` would report your laptop's toolchains, and the agent could pick a language
the grading image lacks. This line closes that gap; it adds no information the official agent could not get.
(b) "You have about N minutes in this session. The work can be continued in a later session …".
Why: the official run is one 6-hour session with a step limit; our protocol is two capped sessions.
The agent needs to know the budget so its pacing is comparable across conditions.

### B6. No-internet guard as a hook (`.claude/hooks/guard.py`)
Official: `--network none` on the container makes the rule physically true.
Here: your laptop has network, so a PreToolUse hook denies `WebFetch`/`WebSearch` and Bash commands
that download or install (`curl`, `wget`, `git clone`, `go get`, `pip install`, `cargo install`,
`npm install`, `brew`, `apt-get`). The deny reason repeats the rule. It does not block `go build`,
`cargo build` of dependency-free code, or anything local.
Why: keeps the "only the binary and the docs" condition true without running the agent in the
container. It is a coarse filter, not a sandbox: check `oversight/events.jsonl` afterwards for
anything that slipped through.

### B7. Session time cap as a hook (`.claude/hooks/cap.py`)
Official: 6 h wall clock and 1,000 steps; the last 10 minutes carry the "running low on time, write
AGENT_REPORT.md" block in every observation.
Here: `oversight/cap_minutes` (default 90) per launch. `cap.py warn` injects the same block as
additional context on every tool result and prompt in the last 10 minutes; `cap.py gate` denies every
tool once the cap is reached, with a reason telling the agent to stop. You then quit Claude Code.
Why: this is our protocol's fixed item ("session 1 ends at the cap, session 2 resumes"), enforced the
same way for every run rather than by watching the clock.

### B8. Recording hooks and the viewer (`.claude/hooks/record.py`, `oversight/`)
Official: the runner writes `<instance>.traj.json` (every command + observation, one agent).
Here: `record.py` appends every Claude Code hook event (prompts, tool calls with inputs, subagent
start/stop with agent ids, compactions, session start/end) to `oversight/events.jsonl` and snapshots
files before edits. `oversight/viewer/serve.py` draws the work DAG per launch;
`oversight/viewer/summary.py` prints the same numbers as text.
Why: the trajectory file cannot show subagents or sessions; the DAG check needs both. The hooks never
block or change anything (exit 0, no output), so they do not alter the agent's behaviour.

### B9. One column per launch, not per Claude session id
`record.py` counts launches (`SessionStart` with source `startup` / `resume` / `clear`) into
`oversight/session_no.txt` and stamps every event with `ov_session_no`; the viewer groups by that.
Why: `claude --resume` may keep the same session id, and the DAG must still show session 1 and
session 2 as separate columns with handoff edges between them.

### B10. Packaging and grading (`grade.sh`)
Official: runner tars `/workspace` from inside the container; `programbench eval` wipes `/workspace`,
extracts the tar, deletes any shipped `./executable`, runs `./compile.sh` with DNS blocked, then runs
each hidden test branch.
Here: `grade.sh` tars `task/` the same way but excludes our study files (`oversight/`, `.claude/`,
`oracle/`, `CLAUDE.md`, `PROMPT.md`) and the wrapper `./executable`; then runs the same
`programbench eval` and `programbench info`.
Why: the excluded files are not the agent's work, and `oracle/reference` is a wrapper that shells
out to a binary, which the grader's judge could read as "wrapping the reference".

### B11. Smoke check for you (`oversight/tests/run_diff.py`, `cases_chroma.txt`, `cases_gron.txt`)
Not in the official setup, not shown to the agent, not used for scoring. It compares the agent's
`./executable` with `./oracle/reference` on ten hand-written cases (picked by instance id) so you can see progress after a
session without waiting for the full eval. For another task, write your own cases file
(one `ARGS ||| STDIN` line per case) from the docs.

### B12. Delegation guidance in the task prompt (`CLAUDE.md`, `PROMPT.md`)
Official: the ProgramBench prompt says nothing about subagents; mini-swe-agent is single-agent, so
the question does not arise.
Here: `CLAUDE.md` gains a "Working method: subagents" section telling the agent to delegate
independent pieces in parallel, keep file ownership disjoint, brief each subagent self-containedly,
and own integration itself; `PROMPT.md` gains step 4 pointing at it.
Why: requested for this study, so runs exercise the work-DAG machinery.
**Caveat, and it matters for interpretation:** Q1 in `analyze.py` asks "did the harness split the
work at all?". With this section present you are no longer measuring *spontaneous* delegation, you
are measuring instruction-following. Runs made with this text are NOT comparable to runs made
without it. If you want the spontaneous-delegation baseline, delete the "Working method: subagents"
section from `CLAUDE.md` and step 4 from `PROMPT.md`, and record which variant each run used.

### B13. The recorder now sees file I/O done inside Bash (`.claude/hooks/record.py`)
Problem: the recorder only logged `Read`/`Write`/`Edit`/`MultiEdit` tool calls. Agents routinely
write files with `cat > f <<EOF`, `python3 - <<EOF`, `sed -i`, `go build -o`, and read them with
`cat`/`head`/`grep`. Observed run: the agent created `src/chroma.py`, `compile.sh` and
`AGENT_REPORT.md` entirely through Bash, and the analysis reported `wrote []`, `first_write: None`,
`first_read: None`. Every file-level metric (writes, reads, data edges, write overlap, handoff) was
blind to that work, which empties the DAG the viewer exists to draw.
Now: `pre_tool` on Bash stores a stat manifest of the workspace (excluding `.git/`, `oversight/`,
`.claude/`, `node_modules/`, `__pycache__/`, `.venv/`, `target/`); `post_tool` diffs it and records
the created/modified paths as `ov_bash_writes`. `ov_bash_reads` lists workspace paths appearing
literally in the command string — a heuristic, kept in its own field, never merged into `Read`.
`analyze.py` folds both into each node's writes/reads.

### B14. Internal auxiliary agents are no longer counted as delegation (`record.py`, `analyze.py`)
Claude Code fires `SubagentStop` for its own internal helper calls (session summary, next-step
suggestion). These arrive with an empty `agent_type`, no matching `SubagentStart`, and an
`agent_transcript_path` that does not exist on disk; they share a `prompt_id` with the preceding
`Stop`, so they track *turns*, not delegations. An observed 15-minute run with zero `Task` calls
produced two of them. `record.py` now tags every subagent event with `ov_subagent_real`, and
`analyze.py` ignores the false ones. Anyone counting `subagent_stop` straight out of
`events.jsonl` must filter on `ov_subagent_real` or they will over-report subagents.

### B15. Verdict is computed on the first launch that did something (`analyze.py`)
`analyze.py` took the lowest launch number as "session 1". A Claude Code restart (e.g. accepting an
in-app update) produces a launch with a `session_start`/`session_end` one second apart and zero tool
calls, which then hijacked the verdict: an observed run reported "first write at None min, end at
0.0 min: the core was still being written when the cap hit" while describing the empty launch, not
the real one. The verdict and the handoff comparison now use the first launch with at least one tool
call, and print a note naming the launches they skipped. The "cap hit" wording is gone: an agent that
stops on its own is not the same as one cut off, and the log cannot tell them apart from write counts.

### B16. Steering is reported (`analyze.py`)
T0 expects exactly one human prompt per launch. The verdict now prints a `Steering:` line listing any
prompt after the first, so an intervention cannot pass unnoticed into the results.

### B17. Concurrent subagents and Bash write attribution (`record.py`, `analyze.py`)
The workspace-diff approach of B13 is ambiguous the moment subagents run in parallel: agent A's
pre/post window contains agent B's writes. A four-subagent test reproduced it — a Go-lexer subagent
that only ran a probe was credited with `lexers/bash.py` written 293 ms earlier by the Bash-lexer
subagent, producing a conflict edge and a 0.5 Jaccard overlap that did not exist. That is a false
positive in exactly the metric Q2 reports.
Now, in three layers:
1. the stat manifest is per acting agent (`oversight/.manifest_<agent_id>.json`), not global;
2. a changed path is attributed only if the command names it (path or basename); when a command
   names none, the raw diff is kept but tagged `ov_bash_writes_ambiguous`;
3. `analyze.py` refuses to attribute an ambiguous diff while any subagent is alive, and prints it
   as `unattributed write @<min> (agent ..., concurrent)` instead of guessing.
Verified: same task re-run gives each subagent exactly its own `lexers/<lang>.py`, 4 data edges
from the shared `core/tokens.py`, 0 conflict edges, and the node writes match the files on disk.
Residual limitation: a command that writes a file without naming it, while other agents run, is
reported as unattributed rather than assigned. That is deliberate — the log genuinely cannot say
whose write it was.

### B18. Subagent completions are not human steering (`analyze.py`)
Claude Code delivers subagent results to the orchestrator as `UserPromptSubmit` events, so the
B16 steering counter read a clean 4-subagent run as "5 human prompts". Prompts that begin with
`<task-notification>` (or carry a `<task-id>`) are now excluded and counted separately as
`system_prompts`.

## C. What is NOT changed but is worth knowing
- Grading needs linux/amd64 Docker. On Apple Silicon, Docker Desktop runs the image under emulation;
  it works for CLI tools like gron/scc but the eval is slow. A Linux x86_64 box (or `./grade.sh pack`
  and copy `run/` there) is the reliable path.
- The eval judge for "wrapping / reusing the reference" is automatic; a `compile.sh` that merely copies
  a prebuilt binary scores 0 even if the tests pass.
- `programbench eval` downloads the hidden test archives from HuggingFace on demand (`programbench
  blob sync <instance_id>` pre-downloads them). Your laptop can reach HuggingFace even though this
  sandbox could not.
