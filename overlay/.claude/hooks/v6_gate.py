#!/usr/bin/env python3
"""PreToolUse for the SSOT tool: preferences from the PRD, safety on its own channel.

The order is the SSOT's. Code settles the fact first, then the judge is asked the one thing code
cannot, then the queue decides whether the developer is interrupted now or later. A safety
finding and a preference finding take different paths from that point on and are never ranked
against each other.

Everything fails open. A crash here must never stop an agent working.
"""
import sys, json, os, time


def _fail_open(et, e, tb):
    try:
        import traceback, tempfile
        with open(os.path.join(tempfile.gettempdir(), "oversight-v6-errors.log"), "a") as f:
            f.write("%s\n%s\n" % (time.strftime("%F %T"),
                                  "".join(traceback.format_exception(et, e, tb))))
    except Exception:
        pass
    sys.exit(0)


sys.excepthook = _fail_open

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)

PROJ = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
sys.path.insert(0, PROJ)
sys.path.insert(0, os.path.join(PROJ, "oversight"))
try:
    from oversight.v6 import safety, surface, prefs, judge6
    from oversight.v5 import context
    from oversight.v3 import taskmodel as tmod
    from oversight import align
except Exception:
    sys.exit(0)

tool, ti = data.get("tool_name"), (data.get("tool_input") or {})
if tool not in ("Bash", "Write", "Edit", "MultiEdit", "Task", "Agent"):
    sys.exit(0)

# Still open (swe3 round 2). A shown notice stays visible, without interrupting again, on every later
# action until the run ends: the user sees the agent keep working while the concern is unanswered.
# One interruption per item is unchanged; this only repeats the line next to later actions.
OPEN = os.path.join(surface.ctl(PROJ), "open.json")
if os.path.exists(OPEN):
    try:
        _open = json.load(open(OPEN))
    except Exception:
        _open = []
    if _open:
        align.append_event(PROJ, dict(ov_event="v6_still_open", items=_open))
        _STILL = "Still open: " + " | ".join("%s on %s" % (o.get("pid") or o.get("risk") or o.get("kind"), o.get("action")) for o in _open)
    else:
        _STILL = None
else:
    _STILL = None

# Reading breaks nothing. v5 already worked out which shell commands can change the repository
# and which cannot, so that list is reused rather than written again. Without this the first live
# run put 69 flags on the board, every one of them the word "user" appearing in a `find`.
if tool == "Bash" and context.read_only_command(ti.get("command")):
    if _STILL:
        print(json.dumps({"systemMessage": _STILL}))
    sys.exit(0)

tm = tmod.load(PROJ)
if not tm or not tmod.preferences(tm):
    sys.exit(0)                                   # no task model: nothing to compare against

events = align.load_events(PROJ)
who = data.get("agent_id") or "orchestrator"

found = safety.check_action(tm, events, tool, ti, who)
if not found:
    sys.exit(0)

found["agent"] = who
action_text = json.dumps({k: v for k, v in ti.items() if isinstance(v, str)})[:1800]
found["action"] = safety.action_target(tool, ti)
align.append_event(PROJ, dict(ov_event="v6_finding", agent=who, kind=found["kind"],
                              risk=found.get("risk"), reason=found.get("reason"),
                              detail=str(found.get("detail"))[:200]))

# The SSOT's middle step: execution -> alignment check -> surfacing. Detection is deliberately
# over-inclusive, so what it produces is a candidate, not a verdict.
if found["kind"] == "preference":
    found, why = judge6.preference_check(tm, found, action_text)
    align.append_event(PROJ, dict(ov_event="v6_judged", agent=who, kind="preference",
                                  departs=bool(found), why=why,
                                  pid=(found or {}).get("pid"), pids=(found or {}).get("pids"),
                                  said=((found or {}).get("said") or "")[:160]))
    if not found:
        sys.exit(0)
else:
    brief = ""
    try:
        brief = open(os.path.join(PROJ, "PROMPT.md")).read()
    except Exception:
        pass
    if safety.gated(found):
        allowed, why = judge6.safety_allowed(found, action_text, brief)
        align.append_event(PROJ, dict(ov_event="v6_judged", agent=who, kind="safety",
                                      risk=found.get("risk"), allowed=allowed, why=why[:200]))
        if allowed:
            sys.exit(0)                           # the rules do give it a reason
        found["judge_why"] = why
    else:
        # The SSOT's one always-surfaces finding. No permission question stands in front of it.
        align.append_event(PROJ, dict(ov_event="v6_judged", agent=who, kind="safety",
                                      risk=found.get("risk"), allowed=False, why="never gated"))

surface.enqueue(PROJ, found)
item = surface.next_to_show(PROJ)
if item is None:
    sys.exit(0)                                   # something is queued, but the run is inside a
                                                  # quiet window: it waits, it is not dropped

text = surface.notice(item)
surface.mark_shown(PROJ, item["channel"])
surface.pop(PROJ, item["channel"], item["key"])
align.append_event(PROJ, dict(ov_event="v6_surfaced", channel=item["channel"], key=item["key"],
                              combined=len(item["members"]), depths=surface.depths(PROJ)))

# Record what was just asked, so the next thing the developer types can be paired with it.
# Without this the answer has nowhere to land and the preference model never moves.
head = item["members"][0]
try:
    _cur = json.load(open(OPEN)) if os.path.exists(OPEN) else []
except Exception:
    _cur = []
_cur.append(dict(key=item["key"], kind=head.get("kind"), pid=head.get("pid"), pids=head.get("pids"), risk=head.get("risk"),
                 category=head.get("category"), action=head.get("action"), detail=str(head.get("detail") or "")[:200]))
json.dump(_cur, open(OPEN, "w"))
# tool_use_id ties the answer to this exact call: its post_tool event appears only if it ran.
# `raw` is the fallback for payloads without one.
json.dump(dict(channel=item["channel"], key=item["key"], pid=head.get("pid"),
               target=head.get("action"), tool_use_id=data.get("tool_use_id"),
               raw=str(ti.get("file_path") or ti.get("command") or ti.get("prompt") or ""),
               ts=time.time()),
          open(os.path.join(surface.ctl(PROJ), "awaiting.json"), "w"))

print(json.dumps({"systemMessage": text,
                  "hookSpecificOutput": {"hookEventName": "PreToolUse",
                                         "permissionDecision": "ask",
                                         "permissionDecisionReason": text}}))
sys.exit(0)
