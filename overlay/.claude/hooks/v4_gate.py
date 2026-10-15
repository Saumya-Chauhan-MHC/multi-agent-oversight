#!/usr/bin/env python3
"""PreToolUse for the simplified tool: filter, cache, judge, hold or stay quiet.

Everything fails open. A crash here must never stop an agent working.
"""
import sys, json, os, time

def _fail_open(et, e, tb):
    try:
        import traceback, tempfile
        with open(os.path.join(tempfile.gettempdir(), "oversight-v4-errors.log"), "a") as f:
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
    from oversight.v4 import rules, policy4, judge4
    from oversight.v4 import filter4 as filt
    from oversight import align
except Exception:
    sys.exit(0)

tm = rules.load(PROJ)
if not rules.stated(tm):
    sys.exit(0)                                    # no rules written: nothing to check against

events = align.load_events(PROJ)
who = data.get("agent_id") or "orchestrator"
tool, ti = data.get("tool_name"), (data.get("tool_input") or {})

trigger = filt.check(tm, events, tool, ti, who)
if not trigger:
    sys.exit(0)                                    # the common case: free, nothing recorded

# The recall net never reaches the judge in this version. In v3 it was judged and then capped at
# silence, which bought a measurement and nothing else: 216 judge calls across two arms, all 216
# silent, 0 of 8 right where it was the only trigger. Here it is recorded unjudged, so the blind
# spot is still visible in the log and costs nothing.
if trigger.get("path") != "B":
    align.append_event(PROJ, dict(ov_event="v4_unjudged", agent=who, tool=tool,
                                  trigger=trigger.get("reason")))
    sys.exit(0)

action = filt.action_text(tool, ti)
key = policy4.cache_key(action, rules.signature(tm), who)
cached = policy4.cache_get(PROJ, key)
if cached is not None and cached.get("band") != "hold":
    sys.exit(0)                                    # already judged under these rules, and benign

brief, state = "", {}
try:
    _, parent = align.parent_status(PROJ, data.get("agent_id"))
    brief = parent.get("brief") or ""
    state = {k: parent.get(k) for k in ("name", "files_written", "children", "running_children")}
except Exception:
    pass
state["acting"] = who

t0 = time.time()
verdict = judge4.judge(tm, action, trigger, brief, state)
judge_s = round(time.time() - t0, 1)
try:
    align.credit_pause(PROJ, judge_s)
except Exception:
    pass

band = policy4.decide(verdict, PROJ)
rid = "%s-%d" % (key[:8], int(time.time() * 1000))
flag = dict(rid=rid, ts=policy4.now(), agent=who, tool=tool, action=action[:300],
            trigger=trigger.get("reason"), risk=trigger.get("risk"),
            dependents=trigger.get("dependents") or [], owner=trigger.get("owner"),
            band=band, judge_s=judge_s,
            **{k: verdict.get(k) for k in ("breaks", "rule", "said", "does", "why", "fix",
                                           "source")})
policy4.cache_put(PROJ, key, dict(band=band, breaks=verdict.get("breaks")))
align.append_event(PROJ, dict(ov_event="v4_judgement", **flag))

if band != "hold":
    sys.exit(0)


def _notice(flag):
    """What the developer reads. Every line is either their own rule or the agent's own action."""
    return "\n".join([
        "[oversight] %s -> %s" % (who, flag["action"][:90]),
        '  you wrote (%s): "%s"' % (flag.get("rule"), flag.get("said")),
        "  this does:    %s" % (flag.get("does") or "?"),
        "  why:          %s" % (flag.get("why") or ""),
        "  instead:      %s" % (flag.get("fix") or ""),
    ])


# Asked once per rule. The developer's answer about a rule stands for the rest of the run, so an
# agent retrying the same violation five times costs one interruption, not five.
prior = policy4.answer_for(PROJ, flag.get("rule"))
if prior is not None:
    if prior["decision"] == "block":
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny",
            "permissionDecisionReason": "the developer already said no to this rule being broken: "
                                        + (prior.get("note") or flag.get("said") or "")}}))
    sys.exit(0)

SIM = os.environ.get("OV_SIMUSER") == "1"
if SIM:
    from oversight.v4 import simuser4
    decision, why = simuser4.ask(flag)
    policy4.record_answer(PROJ, flag["rule"], decision, why)
    align.append_event(PROJ, dict(ov_event="v4_user", rid=rid, decision=decision, reason=why,
                                  rule=flag.get("rule"), trigger=flag.get("trigger"),
                                  simulated=True))
    if decision == "block":
        print(json.dumps({"systemMessage": _notice(flag) + "\n  DEVELOPER: stop. " + why,
                          "hookSpecificOutput": {
                              "hookEventName": "PreToolUse", "permissionDecision": "deny",
                              "permissionDecisionReason": (why or "the developer stopped this")
                                                          + "  " + (flag.get("fix") or "")}}))
    sys.exit(0)

reason = _notice(flag)
print(json.dumps({"systemMessage": reason,
                  "hookSpecificOutput": {"hookEventName": "PreToolUse",
                                         "permissionDecision": "ask",
                                         "permissionDecisionReason": reason}}))
sys.exit(0)
