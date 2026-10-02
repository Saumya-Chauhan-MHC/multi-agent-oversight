#!/usr/bin/env python3
"""UserPromptSubmit: catch the note the user types after declining a spawn.

With Claude Code's own prompt carrying the question, a "no" arrives as an ordinary message rather
than a structured field. The spawn that was declined is recorded in awaiting_answer.json, so the
next thing the user types becomes that decision's note: it goes to the parent and becomes a line in
the user's own words.
"""
import sys, json, os, time
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
proj = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
sys.path.insert(0, os.path.join(proj, "oversight"))
try:
    import memory, align
except Exception:
    sys.exit(0)

aw = os.path.join(align.ctl(proj), "awaiting_answer.json")
if not os.path.exists(aw):
    sys.exit(0)
try:
    a = json.load(open(aw))
except Exception:
    sys.exit(0)
if time.time() - os.path.getmtime(aw) > 600:      # too old to be about that question
    align.clear(aw)
    sys.exit(0)

text = (data.get("prompt") or "").strip()
if not text or text.startswith("/"):
    sys.exit(0)

memory.append_answer(text, a.get("lines") or [], source="answer (no, typed)", rid=a.get("rid"))
align.send_to_agent(proj, a.get("caller"),
                    "[oversight] About your spawn \"%s\": %s" % (a.get("child"), text))
align.record_answer(os.path.join(align.ctl(proj), "answered.jsonl"),
                    dict(dkey=a.get("dkey"), rid=a.get("rid"), answer="no", note=text,
                         ts=align.now_ms()))
align.reset_look(proj, "answered a notice")
align.clear(aw)
print(json.dumps({"systemMessage": "oversight: noted, and sent to %s" % a.get("parent", "the parent")}))
