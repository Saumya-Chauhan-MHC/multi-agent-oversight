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

band = policy.band(verdict, PROJ)
rid = "%s-%d" % (key[:8], int(time.time() * 1000))
flag = dict(rid=rid, ts=policy.now(), agent=who, tool=tool, action=action[:300],
            trigger=trigger.get("reason"), risk=trigger.get("risk"),
            dependents=trigger.get("dependents") or [], owner=trigger.get("owner"),
            band=band, judge_s=judge_s,
            **{k: verdict.get(k) for k in ("verdict", "confidence", "prefs", "evidence",
                                           "metric", "consequence", "correction", "cost",
                                           "if_accepted", "source")})
policy.cache_put(PROJ, key, dict(band=band, verdict=verdict.get("verdict"),
                                 confidence=verdict.get("confidence")))
align.append_event(PROJ, dict(ov_event="v3_judgement", **flag))

if band == "silent":
    sys.exit(0)

block = policy.enqueue(PROJ, flag)
due = policy.due(PROJ)

if band == "hold" and due is not None and due["label"] == block["label"]:
    if due.get("preempted"):
        policy.consume_preempt(PROJ)      # only a real interruption spends the hourly budget
    lines = ["[oversight] %s -> %s" % (who, action[:90]),
             "  departs from %s  confidence %.2f" % (", ".join(flag["prefs"] or []),
                                                     flag.get("confidence") or 0)]
    for e in (flag.get("evidence") or [])[:2]:
        lines.append('  you said (%s): "%s"' % (e.get("pref_id"), str(e.get("said"))[:110]))
        lines.append("  this does:      %s" % str(e.get("proposed"))[:110])
    if flag.get("consequence"):
        lines.append("  cost if it proceeds (%s): %s" % (flag.get("metric"), flag["consequence"]))
    if flag.get("correction"):
        lines.append("  instead: %s  [%s]" % (flag["correction"], flag.get("cost") or "unknown cost"))
    others = [m for m in block["members"] if m["rid"] != rid]
    for m in others:
        lines.append("  also in this block: %s -> %s" % (m["agent"], m["action"][:70]))
    reason = "\n".join(lines)
    print(json.dumps({"systemMessage": reason,
                      "hookSpecificOutput": {"hookEventName": "PreToolUse",
                                             "permissionDecision": "ask",
                                             "permissionDecisionReason": reason}}))
    sys.exit(0)

# a check, or a hold that the quiet window is holding back: recorded, nothing paused
sys.exit(0)
