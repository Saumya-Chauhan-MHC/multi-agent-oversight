#!/usr/bin/env python3
"""UserPromptSubmit: catch what the developer types after a flag, and move the preference.

The hook that asks is not the thing that hears the answer. A PreToolUse hook returns a decision
and exits; the developer's reply arrives later, as an ordinary message to the agent. So the
preference model could never move from inside the gate, and `update_from_feedback` sat wired to
nothing but the demo and the tests.

This is v3's `note_capture.py` pattern: the gate records what it just asked about in
`control6/awaiting.json`, and the next thing the developer types becomes that flag's answer.

Whether they accepted or rejected is not guessed from their wording. It is read off the event
log: if the action the flag was about went on to run, they allowed it. Inferring it from prose
is how "yes, that's right" became a reason to weaken the very rule being upheld.
"""
import json, os, re, sys, time


def _quiet(*a):
    sys.exit(0)


try:
    data = json.load(sys.stdin)
except Exception:
    _quiet()

PROJ = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
sys.path.insert(0, PROJ)
sys.path.insert(0, os.path.join(PROJ, "oversight"))
try:
    from oversight.v6 import prefs, surface
    from oversight import align
except Exception:
    _quiet()

aw = os.path.join(surface.ctl(PROJ), "awaiting.json")
if not os.path.exists(aw):
    _quiet()
try:
    a = json.load(open(aw))
except Exception:
    _quiet()

# Too old to plausibly be about that question.
if time.time() - a.get("ts", 0) > surface.QUIET_S:
    os.remove(aw)
    _quiet()

note = (data.get("prompt") or "").strip()
if not note or note.startswith("/"):
    _quiet()
# Not everything that arrives as a prompt was typed by the developer. A subagent's report, a
# background task notice or a system reminder is delivered the same way, wrapped in a tag. The
# first live multi-agent run took a subagent's hand-back as the answer to a collusion flag; on a
# preference flag that text could have rewritten the rule. Skip it and keep waiting.
if re.match(r"<(agent-message|task-notification|system-reminder|command-|local-command|bash-)", note):
    _quiet()

# Did the action the flag was about actually run? That is the accept/reject signal, and it is
# observed rather than inferred.
# Matched by tool_use_id when the payload has one. The first version compared ov_ts (ms) with
# the flag's time (s), so every event counted as after the flag, and matched on the notice's
# display string, which never equals a file path: a held edit that went ahead was logged reject.
proceeded = False
try:
    for e in align.load_events(PROJ):
        if e.get("ov_event") != "post_tool":
            continue
        if a.get("tool_use_id"):
            hit = e.get("tool_use_id") == a["tool_use_id"]
        else:
            ti = e.get("tool_input") or {}
            hit = (float(e.get("ov_ts", 0)) / 1000.0 >= a.get("ts", 0) and bool(a.get("raw"))
                   and str(ti.get("file_path") or ti.get("command") or ti.get("prompt") or "") == a["raw"])
        if hit:
            proceeded = True
            break
except Exception:
    pass
decision = "accept" if proceeded else "reject"

msg = "oversight: noted"
if a.get("pid"):
    res = prefs.update_from_feedback(PROJ, a["pid"], decision, note)
    align.append_event(PROJ, dict(ov_event="v6_feedback", pid=a["pid"], decision=decision,
                                  note=note[:200], applied=bool(res.get("applied")),
                                  verb=res.get("verb"), why=(res.get("why") or "")[:160]))
    if res.get("applied"):
        msg = ("oversight: %s now reads \"%s\" -- changed because you said \"%s\""
               % (a["pid"], str(res.get("to"))[:110], res.get("quote")))
    else:
        msg = "oversight: noted against %s, rule unchanged (%s)" % (a["pid"], res.get("why") or
                                                                    res.get("verb") or "keep")
else:
    align.append_event(PROJ, dict(ov_event="v6_feedback", channel=a.get("channel"),
                                  decision=decision, note=note[:200], pid=None))

try:
    os.remove(aw)
except Exception:
    pass
print(json.dumps({"systemMessage": msg}))
