# Demo guide

Two ways to show the alignment layer: a scripted run that takes two minutes and always does the same
thing, and a live run with a real agent, which is what you want on camera.

---

## A. The scripted demo (two minutes, deterministic)

```bash
cd ~/research/multi-agent-oversight
./demo.sh                      # uses ~/research/marathon_slack/task
DEMO_PAUSE=0.2 ./demo.sh       # faster, for a sanity check rather than a recording
```

It drives the real hook with real judge calls in a throwaway copy of the task. Nine steps:

| Step | What it shows |
|---|---|
| 1 | the five questions, and the lines they become in your words |
| 2 | q1 to q3 go to the agent, q4 and q5 stay with the tool |
| 3 | a spawn that fits: silent, no question |
| 4 | a spawn that breaks your line: **held**, with evidence pairs quoting you |
| 5 | your answer becomes a new line, and the note goes to that parent |
| 6 | the same decision is not asked twice |
| 7 | a compliant re-plan runs silently: the loop closing |
| 8 | a decision your lines do not cover: a check, nothing held |
| 9 | catch-up counters, status, and every judgement |

---

## B. The live demo (for recording)

### Before you hit record

```bash
# 1. a fresh task folder with the tool in it
WORK=~/research/demo_run
rm -rf $WORK && mkdir -p $WORK
cp -R ~/research/marathon_slack/task/. $WORK/
cp -R ~/research/multi-agent-oversight/overlay/. $WORK/
cp ~/research/marathon_slack/PROMPT.md $WORK/
cd $WORK
printf '{\n "permissions": {"allow": ["Bash"]}\n}\n' > .claude/settings.local.json   # no permission prompts on camera
```

### On camera

**1. Answer the five questions** (this is the A1 screen):

```bash
python3 oversight/ctl.py init
```

Answers that make a hold likely, because the agent will reach for these files early:

| Question | Answer to type |
|---|---|
| 1 rules | `only I create or edit run.sh; subagents never touch tests/` |
| 2 division | `a` |
| 3 verification | `a` |
| 4 involvement | `a` |
| 5 catch-up | `b` |

Then show what it saved: `python3 oversight/ctl.py lines`

**2. Start the agent** in the same terminal:

```bash
claude --permission-mode acceptEdits "$(cat PROMPT.md)"
```

**3. What to expect, in order**

- The agent reads the docs and plans. Nothing from the tool: silence is the normal state.
- Its first spawns are judged. Each judgement takes about three seconds and most are silent.
- When a brief touches `run.sh` or `tests/`, or skips its own tests, the spawn is **held** and you
  see the notice followed by Claude Code's own prompt.
- Answer `1` to allow, `2` to allow everything from that parent, `3` to decline. After declining,
  **type your reason as your next message**: it goes to that parent only, and becomes a new line.

**4. Show the loop closing**, in a second terminal (or after you stop the agent):

```bash
python3 oversight/ctl.py lines        # your new line is at the bottom, in your words
python3 oversight/ctl.py judgements   # every decision, its band and what it cited
python3 oversight/ctl.py status       # counters, and what is waiting
python3 oversight/ctl.py catchup      # the catch-up line
```

### If you would rather answer from a second terminal

Switch the surface and run the watcher. Useful when you want the questions off the agent's screen,
or when a hold would otherwise sit behind Claude Code's prompt:

```bash
python3 - <<'PY'
import json; p="oversight/memory/settings.json"; s=json.load(open(p)); s["surface_mode"]="file"; json.dump(s,open(p,"w"),indent=1)
PY
python3 oversight/ctl.py watch        # notices appear here, you answer 1 / 2 / 3 and type the note
```

### Suggested ten-minute shape

| Time | What you are showing |
|---|---|
| 0:00 | the five questions, answered live |
| 1:00 | `ctl.py lines`: your words, not ours |
| 1:30 | the agent starts; silence while it reads and plans |
| 3:00 | the first held spawn: evidence pairs, your line quoted, the agent waiting |
| 4:00 | you decline and type the reason |
| 5:00 | `ctl.py lines` again: the new line; the agent re-plans and is not asked again |
| 7:00 | a check appears for something your lines never covered; nothing is held |
| 8:30 | `ctl.py status` and `catchup`: what piled up while you were working |
| 9:30 | `ctl.py judgements`: the whole session as a table |

### Forcing a particular moment

- **A hold:** put a file the agent needs early into q1 (`run.sh` works; so does `compile.sh`).
- **A check:** answer q2 with the shortest possible rule set, or skip q1 and q2 and only answer q3.
  A check appears when your lines say nothing about how work should be divided.
- **"Not asked twice":** decline a spawn, then let the agent retry the same thing.

---

## What is not built yet

- The viewer still shows the old DAG. The link in a notice points at it, but there is no
  "since you last looked" mode, no ToM panel and no accept / no buttons there yet. All of that is in
  the design (section 4.6) and is the next piece of work.
- Merge and reassignment decisions are only caught when the orchestrator declares them; today the
  tool sees spawns.
- The catch-up line counts unanswered checks and unshown departures; unseen files are counted but
  the per-subtree version is still rough.
