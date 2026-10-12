#!/usr/bin/env python3
"""PreToolUse: the filter, the cache, the judge, and the policy, in that order.

Everything fails open. A crash here must never stop an agent working.
"""
import sys, json, os, time

def _fail_open(et, e, tb):
    try:
        import traceback, tempfile
        with open(os.path.join(tempfile.gettempdir(), "oversight-v3-errors.log"), "a") as f:
            f.write("%s\n%s\n" % (time.strftime("%F %T"), "".join(traceback.format_exception(et, e, tb))))
    except Exception:
        pass
    sys.exit(0)


sys.excepthook = _fail_open

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
TOOLS = ("Bash", "Write", "Edit", "MultiEdit", "Task", "Agent")
if data.get("tool_name") not in TOOLS:
    sys.exit(0)

PROJ = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
sys.path.insert(0, PROJ)
sys.path.insert(0, os.path.join(PROJ, "oversight"))
try:
    from oversight.v3 import taskmodel as tmod, filter as filt, policy, judge3
    from oversight import align
except Exception:
    sys.exit(0)

tm = tmod.load(PROJ)
if not tmod.preferences(tm):
    sys.exit(0)                                    # no model to align to yet

events = align.load_events(PROJ)
who = data.get("agent_id") or "orchestrator"
tool, ti = data.get("tool_name"), (data.get("tool_input") or {})

trigger = filt.check(tm, events, tool, ti, who)
if not trigger:
    sys.exit(0)                                    # the common case: free, nothing recorded

action = filt.action_text(tool, ti)
key = policy.cache_key(action, tmod.rules_signature(tm), who)
cached = policy.cache_get(PROJ, key)
if cached and cached.get("band") != "hold":
    sys.exit(0)                                    # already judged under these rules, and benign

brief = ""
try:
    _, parent = align.parent_status(PROJ, data.get("agent_id"))
    brief = parent.get("brief") or ""
    state = {k: parent.get(k) for k in ("name", "files_written", "children", "running_children")}
except Exception:
    state = {}

t0 = time.time()
verdict = judge3.judge(tm, action, trigger, brief, state)
judge_s = round(time.time() - t0, 1)
try:
    align.credit_pause(PROJ, judge_s)
except Exception:
    pass

band = policy.band(verdict, PROJ, trigger=trigger.get("reason"))
rid = "%s-%d" % (key[:8], int(time.time() * 1000))
flag = dict(rid=rid, ts=policy.now(), agent=who, tool=tool, action=action[:300],
            trigger=trigger.get("reason"), risk=trigger.get("risk"),
            dependents=trigger.get("dependents") or [], owner=trigger.get("owner"),
            band=band, judge_s=judge_s,
            **{k: verdict.get(k) for k in ("verdict", "confidence", "prefs", "reqs", "grounds",
                                           "evidence", "metric", "consequence", "correction",
                                           "cost", "if_accepted", "source")})
policy.cache_put(PROJ, key, dict(band=band, verdict=verdict.get("verdict"),
                                 confidence=verdict.get("confidence")))
align.append_event(PROJ, dict(ov_event="v3_judgement", **flag))

if band == "silent":
    sys.exit(0)

block = policy.enqueue(PROJ, flag)
due = policy.due(PROJ)

# OV_SIMUSER=1 answers on the developer's behalf, for running a treatment arm unattended. It also
# turns on check-band delivery, because a medium-confidence item that nobody can see is the same
# as silence and the first treatment run showed exactly that.
SIM = os.environ.get("OV_SIMUSER") == "1"


def _brief(flag, allow_block):
    """What the developer is shown. The same text either way, simulated or not."""
    lines = ["[oversight] %s -> %s" % (who, action[:90]),
             "  departs from %s" % ", ".join(flag.get("grounds") or flag.get("prefs") or [])]
    for e in (flag.get("evidence") or [])[:2]:
        _src = e.get("pref_id") or e.get("req_id")
        _lead = "you said" if e.get("pref_id") else "the brief says"
        lines.append('  %s (%s): "%s"' % (_lead, _src, str(e.get("said"))[:110]))
        lines.append("  this does:      %s" % str(e.get("proposed"))[:110])
    if flag.get("consequence"):
        lines.append("  cost if it proceeds (%s): %s" % (flag.get("metric"), flag["consequence"]))
    if flag.get("correction"):
        lines.append("  instead: %s  [%s]" % (flag["correction"], flag.get("cost") or "unknown cost"))
    for m in [m for m in block["members"] if m["rid"] != rid]:
        lines.append("  also in this block: %s -> %s" % (m["agent"], m["action"][:70]))
    if not allow_block:
        lines.append("  (nothing is paused; this is a mention)")
    return "\n".join(lines)


def _simulated(flag, allow_block):
    """Ask the stand-in developer, record what it said, and act on it."""
    from oversight.v3 import simuser
    decision, why = simuser.ask(flag, allow_block=allow_block)
    align.append_event(PROJ, dict(ov_event="v3_user", rid=rid, band=band,
                                  allow_block=allow_block, decision=decision, reason=why,
                                  prefs=flag.get("prefs"), metric=flag.get("metric"),
                                  risk=flag.get("risk"), trigger=flag.get("trigger"),
                                  simulated=True))
    note = "[oversight] the developer says: %s" % why if why else ""
    if decision == "block" and allow_block:
        print(json.dumps({"systemMessage": _brief(flag, True) + "\n  DEVELOPER: stop. " + why,
                          "hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                 "permissionDecision": "deny",
                                                 "permissionDecisionReason":
                                                     (why or "the developer stopped this") +
                                                     "  " + (flag.get("correction") or "")}}))
    elif decision == "note":
        print(json.dumps({"systemMessage": note or _brief(flag, allow_block),
                          "hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                 "permissionDecision": "allow",
                                                 "permissionDecisionReason": note}}))
    sys.exit(0)

if band == "hold" and due is not None and due["label"] == block["label"]:
    if due.get("preempted"):
        policy.consume_preempt(PROJ)      # only a real interruption spends the hourly budget
    if SIM:
        _simulated(flag, True)
    reason = _brief(flag, True)
    policy.mark_shown(PROJ, rid)
    print(json.dumps({"systemMessage": reason,
                      "hookSpecificOutput": {"hookEventName": "PreToolUse",
                                             "permissionDecision": "ask",
                                             "permissionDecisionReason": reason}}))
    sys.exit(0)

if band == "check" and due is not None and due["label"] == block["label"]:
    # The medium band, delivered. This is the fix the clean recording forced: the tool was putting
    # both of that run's surfacing opportunities in the check band, correctly, with the right
    # preference, metric and risk -- and printing neither, because this branch used to be a bare
    # `sys.exit(0)`. Surfacing scored 0.00 against a golden set the band scorer said it had got
    # right. Nothing is paused here and ignoring it is a valid answer, which is the entire point
    # of a band between a hold and silence.
    if SIM:
        _simulated(flag, False)
    print(json.dumps({"systemMessage": _brief(flag, False),
                      "hookSpecificOutput": {"hookEventName": "PreToolUse",
                                             "permissionDecision": "allow",
                                             "permissionDecisionReason": _brief(flag, False)}}))
    policy.mark_shown(PROJ, rid)
    sys.exit(0)

# a hold the quiet window is holding back, or a check behind another block in the queue
sys.exit(0)
