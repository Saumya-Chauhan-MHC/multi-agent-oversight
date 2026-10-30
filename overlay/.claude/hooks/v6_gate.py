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

# Reading breaks nothing. v5 already worked out which shell commands can change the repository
# and which cannot, so that list is reused rather than written again. Without this the first live
# run put 69 flags on the board, every one of them the word "user" appearing in a `find`.
if tool == "Bash" and context.read_only_command(ti.get("command")):
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
found["action"] = str(ti.get("command") or ti.get("file_path") or "")[:200]
align.append_event(PROJ, dict(ov_event="v6_finding", agent=who, kind=found["kind"],
                              risk=found.get("risk"), reason=found.get("reason"),
                              detail=str(found.get("detail"))[:200]))

# The SSOT's middle step: execution -> alignment check -> surfacing. Detection is deliberately
# over-inclusive, so what it produces is a candidate, not a verdict.
if found["kind"] == "preference":
    found, why = judge6.preference_check(tm, found, action_text)
    align.append_event(PROJ, dict(ov_event="v6_judged", agent=who, kind="preference",
                                  departs=bool(found), why=why,
                                  pid=(found or {}).get("pid"),
                                  said=((found or {}).get("said") or "")[:160]))
    if not found:
        sys.exit(0)
else:
    brief = ""
    try:
        brief = open(os.path.join(PROJ, "PROMPT.md")).read()
    except Exception:
        pass
    allowed, why = judge6.safety_allowed(found, action_text, brief)
    align.append_event(PROJ, dict(ov_event="v6_judged", agent=who, kind="safety",
                                  risk=found.get("risk"), allowed=allowed, why=why[:200]))
    if allowed:
        sys.exit(0)                               # the rules do give it a reason
    found["judge_why"] = why

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

print(json.dumps({"systemMessage": text,
                  "hookSpecificOutput": {"hookEventName": "PreToolUse",
                                         "permissionDecision": "ask",
                                         "permissionDecisionReason": text}}))
sys.exit(0)
