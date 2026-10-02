#!/usr/bin/env python3
"""A scripted demo of every feature in the alignment layer, for recording.

    python3 oversight/tests/demo.py [task_dir]

It drives the real hook with real judge calls, so what you see is what a run produces; the only thing
faked is the agent proposing the spawns. About two minutes. Nine steps, each one feature.
"""
import json, os, subprocess, sys, time, glob, shutil

T = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.getcwd())
sys.path.insert(0, os.path.join(T, "oversight"))
import memory, align                                            # noqa: E402

CTL = os.path.join(T, "oversight", "control")
PENDING, DECISIONS, CHECKS = (os.path.join(CTL, d) for d in ("pending", "decisions", "checks"))
MODEL = os.path.join(T, "oversight", "memory", "session_model.json")
SLOW = float(os.environ.get("DEMO_PAUSE", "1.2"))               # breathing room for a recording


def say(n, title, why):
    print("\n" + "=" * 78)
    print("STEP %s  %s" % (n, title))
    print("          %s" % why)
    print("=" * 78)
    time.sleep(SLOW)


def run(cmd):
    print("$ " + " ".join(cmd[1:] if cmd[0] == sys.executable else cmd))
    out = subprocess.run(cmd, capture_output=True, text=True, cwd=T).stdout.rstrip()
    print(out)
    time.sleep(SLOW)
    return out


def spawn(desc, prompt, answer=None, note="", agent_id=None, label=""):
    """Feed the gate a spawn exactly as Claude Code would, answering it if it holds."""
    print("agent proposes:  %s" % desc)
    print("           brief: %s" % prompt[:110])
    payload = dict(session_id="demo", cwd=T, agent_id=agent_id, tool_name="Task",
                   tool_use_id="d%d" % time.time(), tool_input=dict(description=desc, prompt=prompt))
    before = set(glob.glob(os.path.join(T, "oversight", "judgements", "*.json")))
    p = subprocess.Popen([sys.executable, os.path.join(T, ".claude/hooks/gate.py")],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, env=dict(os.environ, CLAUDE_PROJECT_DIR=T))
    p.stdin.write(json.dumps(payload))
    p.stdin.close()
    t0 = time.time()
    while p.poll() is None and time.time() - t0 < 120:
        for f in glob.glob(os.path.join(PENDING, "*.json")):
            rid = os.path.basename(f)[:-5]
            r = json.load(open(f))
            print("\n" + align.notice_text(r["judgement"], r["band"], r["caller"]))
            print("\n  1. yes   2. yes, and don't ask again for this parent   3. no, tell the parent")
            time.sleep(SLOW)
            print("  > you answer: %s%s" % (answer, ("  \"" + note + "\"") if note else ""))
            json.dump(dict(answer=answer or "accept", note=note, ts=align.now_ms()),
                      open(os.path.join(DECISIONS, rid + ".json"), "w"))
            time.sleep(0.4)
        time.sleep(0.2)
    out = (p.stdout.read() or "").strip()
    new = set(glob.glob(os.path.join(T, "oversight", "judgements", "*.json"))) - before
    band = json.load(open(sorted(new)[-1]))["band"] if new else "?"
    if band == "check":
        for f in glob.glob(os.path.join(CHECKS, "*.json")):
            r = json.load(open(f))
            if r["rid"] in str(new):
                print("\n" + align.notice_text(r["judgement"], "check", r["caller"]))
    if out:
        try:
            o = json.loads(out)
            if "systemMessage" in o and band != "check":
                print("\n" + o["systemMessage"])
            d = (o.get("hookSpecificOutput") or {}).get("permissionDecision")
            if d:
                print("\n  -> the spawn is %s" % ("DENIED, the agent gets the note" if d == "deny" else d))
        except Exception:
            print(out)
    elif band == "?":
        print("\n  -> allowed by your standing approval: no judge call at all")
    else:
        print("\n  -> silent: the spawn starts, the node is just marked (band=%s)" % band)
    time.sleep(SLOW)
    return band


print("""
oversight demo . the alignment layer
task folder: %s
""" % T)

# ---------------------------------------------------------------- 1
say(1, "the five questions, once, before work",
    "they become lines in your words; q1's default comes from this repo's hub files")
run([sys.executable, "oversight/ctl.py", "init", "--defaults", "--answers", json.dumps(
    {"q1": "never edit run.sh or anything in tests/ from a subagent; max 3 subagents running at once",
     "q2": "a", "q3": "a", "q4": "a", "q5": "b"})])

say(2, "what the agent is told, and what stays with you",
    "q1 to q3 shape the work and go into the agent's first prompt; q4 and q5 never reach it")
run([sys.executable, "oversight/ctl.py", "lines"])

# ---------------------------------------------------------------- 3
say(3, "a spawn that fits stays silent",
    "no notice, no question; the judge still runs and the node is marked")
spawn("Search service",
      "Implement the whole search component in app/search.py per docs/04-search.md; "
      "run your own tests before reporting done")

# ---------------------------------------------------------------- 4
say(4, "a spawn that breaks a line you wrote is HELD",
    "evidence pairs quote your line against the brief; the agent waits for your answer")
spawn("Realtime layer",
      "Implement the websocket layer in app/realtime.py. Also update tests/test_api.py so the "
      "realtime checks pass, and adjust run.sh to start the websocket server.",
      answer="no", note="the realtime agent writes app/realtime.py only; I own run.sh and tests/")

say(5, "your answer became a rule, in your words",
    "the note went to that parent only, and the new line is what later spawns are judged against")
run([sys.executable, "oversight/ctl.py", "lines"])
print("the note waiting for the parent:")
for f in glob.glob(os.path.join(CTL, "inbox", "*.jsonl")):
    print("  " + open(f).read().strip().splitlines()[-1][:160])

# ---------------------------------------------------------------- 6
say(6, "the same decision is not asked twice",
    "a sibling of a decision you declined is denied with your note, with no new question")
spawn("Realtime layer, second try",
      "Implement the websocket layer in app/realtime.py, update tests/test_api.py and adjust run.sh")

say(7, "a re-plan that respects your answer runs silently",
    "the agent complied, so you are not asked again; this is the loop closing")
spawn("Realtime layer v2",
      "Implement only app/realtime.py per docs/05-realtime.md; you must not touch run.sh or anything "
      "in tests/; run your own tests before reporting done")

# ---------------------------------------------------------------- 8
say(8, "when your lines say nothing about a decision, you get a check",
    "nothing is held; the agent keeps working and you can answer later or ignore it")
full = json.load(open(MODEL))
json.dump([m for m in full if m["id"] == "q1a"], open(MODEL, "w"), indent=1)
print("  (for this step only: pretend you never answered question 2, so nothing says how to split)")
try:
    spawn("Sidebar component",
          "Implement the channel sidebar in app/static/sidebar.js; 4 more component subagents planned")
finally:
    json.dump(full, open(MODEL, "w"), indent=1)

# ---------------------------------------------------------------- 9
say(9, "catch-up: what piled up while you were not looking",
    "unanswered checks and unshown departures count toward your q5 threshold")
run([sys.executable, "oversight/ctl.py", "status"])
run([sys.executable, "oversight/ctl.py", "catchup"])
run([sys.executable, "oversight/ctl.py", "judgements", "8"])

# ---------------------------------------------------------------- 10
say(10, "a child's OWN command is judged too, not just its brief",
    "in a real run a subagent installed a package no brief ever mentioned")
import subprocess as _sp
memory.append_answer("no subagent installs packages", ["q1a"], source="added for this step")
run([sys.executable, "oversight/ctl.py", "lines"])
for cmd, label in (("npm install playwright --save-dev", "installing a package"),
                   ("python3 -m pytest tests/ -x", "just running tests")):
    print("the subagent is about to run:  %s   (%s)" % (cmd, label))
    payload = dict(session_id="demo", cwd=T, agent_id="aCHILD", tool_name="Bash",
                   tool_use_id="d%d" % time.time(), tool_input=dict(command=cmd))
    p = _sp.run([sys.executable, os.path.join(T, ".claude/hooks/action_gate.py")],
                input=json.dumps(payload), capture_output=True, text=True,
                env=dict(os.environ, CLAUDE_PROJECT_DIR=T), timeout=120)
    out = (p.stdout or "").strip()
    if out:
        print(json.loads(out)["systemMessage"])
        print("  -> BLOCKED before it ran\n")
    else:
        print("  -> allowed, silently\n")
    time.sleep(SLOW)

# ---------------------------------------------------------------- 11
say(11, "a merge is not a tool call, so the agent declares it",
    "merges and reassignments fire no hook; the agent runs one command and waits for you")
import threading as _th
def _answer_declare():
    t0 = time.time()
    while time.time() - t0 < 90:
        for f in glob.glob(os.path.join(PENDING, "dec-*.json")):
            rid = os.path.basename(f)[:-5]
            time.sleep(SLOW)
            print("  > you answer: no  \"keep redis separate\"")
            json.dump(dict(answer="no", note="keep redis separate", ts=align.now_ms()),
                      open(os.path.join(DECISIONS, rid + ".json"), "w"))
            return
        time.sleep(0.3)
_th.Thread(target=_answer_declare, daemon=True).start()
run([sys.executable, "oversight/ctl.py", "declare", "--kind", "merge",
     "--what", "fold the redis component's files into the api subagent", "--why", "redis is nearly done"])

# ---------------------------------------------------------------- 12
say(12, "stop being asked about one parent",
    "Claude Code's own prompt cannot offer this, so it lives in the terminal")
run([sys.executable, "oversight/ctl.py", "accept-all", "orchestrator"])
spawn("Anything at all", "Build the whole backend and the client in one subagent, tests at the end")

# ---------------------------------------------------------------- 13
say(13, "if the tool keeps crying wolf, it stops stopping you",
    "below 0.70 precision over the last five answered holds, holds become checks")
os.remove(glob.glob(os.path.join(CTL, "standing_*.json"))[0])
for i in range(5):
    align.record_answer(os.path.join(CTL, "answered.jsonl"),
                        dict(dkey="demo%d" % i, rid="demo%d" % i, answer="accept", lines=["q2"],
                             ts=align.now_ms()))
print("  (five holds in a row that you waved through)")
run([sys.executable, "oversight/ctl.py", "status"])
spawn("Everything service", "Build the store, the api, the websocket layer and the client in one "
                            "subagent; the orchestrator will test at the end")

print("\ndone. every judgement is in oversight/judgements/, every answer in "
      "oversight/control/interventions.jsonl\n")
