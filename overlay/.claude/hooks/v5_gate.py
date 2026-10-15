#!/usr/bin/env python3
"""PreToolUse for the no-filter tool: gather context, judge, hold or stay quiet.

Two things v4 had are gone.

There is no rule file. The judge is given the task description the developer already wrote, and
a yes has to quote it. A developer restating their own task in a second document was never the
baseline, and the one line I transcribed wrong from CONTRACTS.md cost a whole run.

There is no filter. v4 decided whether to judge at all with six structural lookups and a
word-overlap recall net; an action matching none of them was never judged. That meant a rule the
developer could state but no lookup covered produced silence, which is how arm F watched the lead
write a file the contract gave to someone else and said nothing. Every editing action is judged
here. What is kept from the filter is only its content side: finding what other agents did to the
same file, which is the one fact neither agent can see.

Everything fails open. A crash here must never stop an agent working.
"""
import sys, json, os, time

def _fail_open(et, e, tb):
    try:
        import traceback, tempfile
        with open(os.path.join(tempfile.gettempdir(), "oversight-v5-errors.log"), "a") as f:
            f.write("%s\n%s\n" % (time.strftime("%F %T"), "".join(traceback.format_exception(et, e, tb))))
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
    from oversight.v5 import task, context, judge5, policy5
    from oversight.v4 import relay
    from oversight import align
except Exception:
    sys.exit(0)

tool, ti = data.get("tool_name"), (data.get("tool_input") or {})
if not context.worth_judging(tool, ti):
    sys.exit(0)                                    # reading breaks nothing, and neither does a
                                                   # read-only shell command. This is not a filter
                                                   # on judgement, it is the set of acts that can
                                                   # change the repository at all

tk = task.load(PROJ)
if not task.stated(tk):
    sys.exit(0)                                    # no task description found: nothing to judge

events = align.load_events(PROJ)
who = data.get("agent_id") or "orchestrator"
action = context.action_text(tool, ti)

# Context, not gating. Every action below this line reaches the judge.
# Every path this action could touch, which for a shell command means the paths named in it.
paths = context.targets(tool, ti)
others, sep = {}, False
for mine in paths:
    for w, eds in context.others_on(events, mine, who).items():
        others.setdefault(w, []).extend(eds)
    sep = sep or any(context.separate_checkouts(mine, ed.get("where"))
                     for eds in others.values() for ed in eds)
ctx = dict(others=others, separate=sep, target=(paths[0] if paths else ""), targets=paths)

key = policy5.cache_key(action, task.signature(tk), who, context.others_sig(others))
cached = policy5.cache_get(PROJ, key)
if cached is not None and cached.get("band") != "hold":
    sys.exit(0)                                    # identical action, same task text, already a no

brief = ""
try:
    _, parent = align.parent_status(PROJ, data.get("agent_id"))
    brief = parent.get("brief") or ""
except Exception:
    pass

t0 = time.time()
verdict = judge5.judge(tk["text"], action, ctx, brief, {"acting": who})
judge_s = round(time.time() - t0, 1)
try:
    align.credit_pause(PROJ, judge_s)
except Exception:
    pass

band = policy5.decide(verdict)
rid = "%s-%d" % (key[:8], int(time.time() * 1000))
flag = dict(rid=rid, ts=policy5.now(), agent=who, tool=tool, action=action[:300],
            target=mine, others=sorted(others), others_n=sum(len(v) for v in others.values()),
            separate=sep, band=band, judge_s=judge_s, task_files=tk["files"],
            **{k: verdict.get(k) for k in ("breaks", "said", "does", "why", "fix",
                                           "other_fix", "source")})
policy5.cache_put(PROJ, key, dict(band=band, breaks=verdict.get("breaks")))
align.append_event(PROJ, dict(ov_event="v5_judgement", **flag))

if band != "hold":
    sys.exit(0)


def _lower1(t):
    return (t[:1].lower() + t[1:]) if t else t


def _notice(flag):
    """What the developer reads. Every line is either their own task text or the agent's action."""
    return "\n".join([
        "[oversight] %s -> %s" % (who, flag["action"][:90].replace("\n", " ")),
        '  your task says: "%s"' % (flag.get("said") or "(a clash between two agents)"),
        "  this does:      %s" % (flag.get("does") or "?"),
        "  why:            %s" % (flag.get("why") or ""),
        "  instead:        %s" % (flag.get("other_fix") or flag.get("fix") or ""),
    ])


tp = policy5.topic(verdict)
prior = policy5.answer_for(PROJ, tp)
if prior is not None:
    if prior["decision"] == "block":
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny",
            "permissionDecisionReason": "the developer already said no to this: "
                                        + (prior.get("note") or flag.get("said") or "")}}))
    else:
        # Already answered for this topic, so the developer is not asked again. The agents still
        # are told: the other agent's checkout gets the half only it can do, and this agent gets
        # its own half, which it would otherwise never hear on a repeat.
        to = relay.send(PROJ, verdict, ctx, who, rid)
        if flag.get("fix") and not to:
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PreToolUse", "permissionDecision": "allow",
                "permissionDecisionReason": "Go ahead with this, and you also need to: "
                                            + flag["fix"]}}))
    sys.exit(0)

SIM = os.environ.get("OV_SIMUSER") == "1"
if not SIM:
    reason = _notice(flag)
    print(json.dumps({"systemMessage": reason,
                      "hookSpecificOutput": {"hookEventName": "PreToolUse",
                                             "permissionDecision": "ask",
                                             "permissionDecisionReason": reason}}))
    sys.exit(0)

from oversight.v5 import simuser5
decision, why = simuser5.ask(flag, task=(brief or tk["text"][:900]),
                             asked_n=len(policy5.asked(PROJ) or []))
policy5.record_answer(PROJ, tp, decision, why)
align.append_event(PROJ, dict(ov_event="v5_user", rid=rid, decision=decision, reason=why,
                              topic=tp, simulated=True))

if decision == "block":
    print(json.dumps({"systemMessage": _notice(flag) + "\n  DEVELOPER: stop. " + why,
                      "hookSpecificOutput": {
                          "hookEventName": "PreToolUse", "permissionDecision": "deny",
                          "permissionDecisionReason": (why or "the developer stopped this")
                                                      + "  " + (flag.get("fix") or "")}}))
    sys.exit(0)

# Not blocked, so the action goes ahead and the clash is about to be real in the merged tree.
# The half only the other agent's checkout can take goes to that agent.
to = relay.send(PROJ, verdict, ctx, who, rid)
if flag.get("fix") or to:
    note = _notice(flag)
    if to:
        note += "\n  relayed to:     %s" % ", ".join(to)
    go = "Go ahead with this"
    if to:
        go += (". Do not undo it and do not leave a second copy of the old form behind. The other "
               "agent working on this file has been told separately, in its own checkout, to "
               + _lower1((verdict.get("other_fix") or "").rstrip("."))
               + ", so you do not need to reach into their checkout and should not try.")
    elif flag.get("fix"):
        go += ", and you also need to: " + flag["fix"]
    print(json.dumps({"systemMessage": note,
                      "hookSpecificOutput": {
                          "hookEventName": "PreToolUse", "permissionDecision": "allow",
                          "permissionDecisionReason": go + (("  " + why) if why else "")}}))
sys.exit(0)
