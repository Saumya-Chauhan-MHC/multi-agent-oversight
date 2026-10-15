#!/usr/bin/env python3
"""One call, one yes-or-no answer.

v3's judge returned a verdict plus a confidence, and the policy split that confidence into three
bands. Two things killed that design. The confidence carried no band information (it ordered
decisions at 0.09, 0.52 and 0.67 across three measurements, where 0.5 is a coin flip), and the
middle band it fed was a notice nobody had to act on.

So this judge answers the only question a hold-or-silence tool needs: does this action break one
of the rules the developer wrote, yes or no. There is no confidence field to ask for, because
nothing downstream would be allowed to use it.
"""
import json, os, sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import judge as j2                                        # the subprocess + JSON plumbing

MODEL = "claude-sonnet-5"
TIMEOUT_S = 45

SYSTEM = """You check one action against rules a developer wrote by hand.

Answer only this: does this action break one of those rules, yes or no.

Silence is the default and it is almost always right. Say yes only when you can point at the rule
and at the part of the action that contradicts it, and a reasonable developer reading both would
agree. If it is arguable, debatable, a matter of taste, or merely untidy, the answer is no.

Reading is not editing. Printing, listing, grepping, opening or running a file does not break a
rule about editing it. A test that fails is not a broken rule; a test that cannot fail is.

If another agent has already changed this file, work out which of the two will be WRONG once
both changes are combined, and answer about the action in front of you on that basis.

An agent that changes a helper and updates its own call sites is self-consistent: its work is
correct on its own and correct after the merge. Stopping it only loses that work. Answer no.

An agent whose code calls the helper in a form the other agent's version no longer provides is
the one that breaks: a name that was renamed away, a call missing an argument that became
required, a result used as if the return type had not changed. That is the action to stop, even
though the agent could not have known, and that is exactly why someone outside both agents has
to say so.

A rule is broken by the action in front of you only when THAT action is the one doing the
forbidden thing. Knowing that someone else's code will break is not the same as this action
breaking a rule. If the rule you would cite binds callers and the action in front of you is not
a call, or it binds changes to a helper and this action does not change one, the answer is no,
however clearly you can see that a conflict exists. Say nothing and wait for the action that
actually breaks it.

When you answer yes here, `fix` must tell the agent the CURRENT form of the helper, taken from
what the other agent actually wrote, so it can correct itself in one step.

The orchestrator is the lead. A rule addressed to component agents does not bind the lead, and
a path the table gives to the lead is the lead's to write.

Only cite a rule by the id given. Never invent a rule, never paraphrase one into something
stronger, and never cite a rule that does not appear in the list.

Return strict JSON, nothing else:
{"breaks": true|false,
 "rule": "<the id, or null>",
 "said": "<the rule, copied exactly>",
 "does": "<the part of the action that contradicts it, quoted from the action>",
 "why": "<one sentence a developer can check>",
 "fix": "<what to do instead, one sentence>"}"""


def _payload(tm, action, trigger, brief, state):
    from . import rules as R
    lines = ["RULES THE DEVELOPER WROTE"]
    for p in R.stated(tm):
        lines.append("  %s: %s" % (p["id"], p["rule"]))
    if not R.stated(tm):
        lines.append("  (none)")
    who = (state or {}).get("acting") or "orchestrator"
    lines += ["", "WHO IS ACTING",
              ("  the orchestrator, which is the lead on this task" if who == "orchestrator"
               else "  a subagent (%s)" % who)]
    lines += ["", "WHY THIS ACTION WAS PICKED OUT",
              "  %s: %s" % (trigger.get("reason"), trigger.get("detail")),
              "", "THE ACTION", action]
    if trigger.get("owner"):
        lines.append("  (the resource is registered to %s)" % trigger["owner"])
    if trigger.get("dependents"):
        lines.append("  (already built on by %s)" % ", ".join(trigger["dependents"]))
    others = trigger.get("others") or {}
    if others:
        lines += ["", "WHAT OTHER AGENTS HAVE ALREADY DONE TO THIS SAME FILE",
                  "  (they cannot see each other's work; you can)"]
        for who, edits in list(others.items())[:3]:
            for ed in edits[-2:]:
                if ed.get("removed"):
                    lines.append("  %s removed: %s" % (who[:9], ed["removed"][:160]))
                lines.append("  %s wrote:   %s" % (who[:9], ed["added"][:260]))
    if brief:
        lines += ["", "WHAT THIS AGENT WAS ASKED TO DO", brief[:1200]]
    if state:
        lines += ["", "AGENT STATE", json.dumps(state)[:600]]
    return "\n".join(lines)


def _validate(out, tm):
    """A yes must name a real rule and quote it. Anything else is turned into a no."""
    from . import rules as R
    if not isinstance(out, dict):
        return None
    if not out.get("breaks"):
        return dict(breaks=False, rule=None, said="", does="", why="", fix="", source="judge")
    by_id = {p["id"]: p["rule"] for p in R.stated(tm)}
    rid = out.get("rule")
    if rid not in by_id:
        return dict(breaks=False, rule=None, said="", does="", why="cited a rule that is not in "
                    "the list: %r" % rid, fix="", source="invalid-citation")
    return dict(breaks=True, rule=rid, said=by_id[rid],
                does=str(out.get("does") or "")[:300], why=str(out.get("why") or "")[:300],
                fix=str(out.get("fix") or "")[:300], source="judge")


def judge(tm, action, trigger, brief="", agent_state=None, model=MODEL):
    """Fails open: a timeout, a crash or unparseable output all mean no, and the work carries on."""
    text, err = j2.run(SYSTEM, _payload(tm, action, trigger, brief, agent_state or {}),
                       model, TIMEOUT_S)
    if err or not text:
        return dict(breaks=False, rule=None, said="", does="", why=err or "empty",
                    fix="", source="unavailable")
    raw = j2._extract_json(text)
    out = _validate(raw, tm) if raw else None
    if out is None:
        return dict(breaks=False, rule=None, said="", does="", why="unparseable", fix="",
                    source="unavailable")
    return out
