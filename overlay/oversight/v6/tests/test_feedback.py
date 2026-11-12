#!/usr/bin/env python3
"""v6_feedback.py, run as Claude Code runs it: what counts as the developer's answer to a flag,
and whether the flagged action went ahead. No judge is called: the safety channel never asks
one, and an accepted preference flag returns before it does."""
import json, os, shutil, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
OVERLAY = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
HOOK = os.path.join(OVERLAY, ".claude", "hooks", "v6_feedback.py")

ok = bad = 0


def check(name, cond):
    global ok, bad
    ok, bad = ok + bool(cond), bad + (not cond)
    print(("  ok:   " if cond else "  FAIL: ") + name)


def project(awaiting, events):
    d = tempfile.mkdtemp()
    shutil.copytree(os.path.join(OVERLAY, "oversight"), os.path.join(d, "oversight"),
                    ignore=shutil.ignore_patterns("__pycache__", "tests"))
    os.makedirs(os.path.join(d, "control6"))
    json.dump(awaiting, open(os.path.join(d, "control6", "awaiting.json"), "w"))
    with open(os.path.join(d, "oversight", "events.jsonl"), "w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")
    json.dump(dict(preferences=[dict(id="P11", category="P4", rule="Change only app.py.")]),
              open(os.path.join(d, "oversight", "task_model.json"), "w"))
    return d


def answer(d, prompt):
    subprocess.run([sys.executable, HOOK], input=json.dumps(dict(prompt=prompt, cwd=d)),
                   capture_output=True, text=True, env=dict(os.environ, CLAUDE_PROJECT_DIR=d))
    fb = [json.loads(l) for l in open(os.path.join(d, "oversight", "events.jsonl"))
          if '"v6_feedback"' in l]
    return fb[-1] if fb else None, os.path.exists(os.path.join(d, "control6", "awaiting.json"))


now = time.time()
ms = lambda t: int(t * 1000)
flag = dict(channel="safety", key="risk:collusion:graded_file", pid=None,
            target="tests/test_app.py", tool_use_id="toolu_A", raw="/p/tests/test_app.py", ts=now)

# A subagent's report arrives through UserPromptSubmit too. It is not the developer's answer.
d = project(flag, [])
fb, still = answer(d, '<agent-message from="a2e">\n[Subagent hand-back] done, tests pass')
check("a subagent's report is not taken as the answer", fb is None)
check("and the flag keeps waiting for the developer", still)
fb, _ = answer(d, '<task-notification>\n<task-id>x</task-id>')
check("nor is a background task notice", fb is None)

# The flagged call ran: its post_tool carries the same tool_use_id.
d = project(flag, [dict(ov_event="post_tool", tool_use_id="toolu_A", ov_ts=ms(now + 2),
                        tool_input=dict(file_path="/p/tests/test_app.py"))])
fb, still = answer(d, "fine, adding a test is ok")
check("the developer's reply is recorded", fb is not None and fb["note"].startswith("fine"))
check("a held call that went ahead is an accept", fb and fb["decision"] == "accept")
check("and the flag is closed", not still)

# Something else ran, the flagged call did not.
d = project(flag, [dict(ov_event="post_tool", tool_use_id="toolu_B", ov_ts=ms(now + 2),
                        tool_input=dict(file_path="/p/app.py"))])
fb, _ = answer(d, "no, leave the tests alone")
check("a held call that never ran is a reject", fb and fb["decision"] == "reject")

# Without a tool_use_id: the same file, but written before the flag, is not this call.
f2 = dict(flag, tool_use_id=None)
d = project(f2, [dict(ov_event="post_tool", ov_ts=ms(now - 60),
                      tool_input=dict(file_path="/p/tests/test_app.py"))])
fb, _ = answer(d, "no")
check("an earlier write to the same file is not this call (ms vs s)", fb and fb["decision"] == "reject")
d = project(f2, [dict(ov_event="post_tool", ov_ts=ms(now + 2),
                      tool_input=dict(file_path="/p/tests/test_app.py"))])
fb, _ = answer(d, "ok")
check("a later write to the same file is", fb and fb["decision"] == "accept")

# Preference flag, accepted: recorded against the preference, rule unchanged, no judge needed.
d = project(dict(flag, channel="preference", key="pref:P11", pid="P11"),
            [dict(ov_event="post_tool", tool_use_id="toolu_A", ov_ts=ms(now + 2),
                  tool_input=dict(file_path="/p/tests/test_app.py"))])
fb, _ = answer(d, "yes go ahead")
check("an accepted preference flag leaves the rule as it was",
      fb and fb["pid"] == "P11" and fb["decision"] == "accept" and not fb["applied"])

print("%d passed, %d failed" % (ok, bad))
sys.exit(1 if bad else 0)
