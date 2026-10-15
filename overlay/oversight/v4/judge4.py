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

If another agent has already touched this file, say what is factually true of the combination:
whether the action in front of you assumes a form of the helper the other agent's version no
longer provides, or changes a form the other agent's code still depends on. A name renamed away,
a call missing an argument that became required, a result used as if the return type had not
changed.

Then apply the developer's rules to that fact. Do not bring your own view of who ought to be
responsible: which of the two agents has to give way is a policy question and the rules above
are the only answer to it. If the rules put the burden on the agent making the change, say so;
if they put it on the caller, say so.

A rule is broken by the action in front of you only when THAT action is the one doing the
forbidden thing. Knowing that someone else's code will break is not the same as this action
breaking a rule. If the rule you would cite binds callers and the action in front of you is not
a call, or it binds changes to a helper and this action does not change one, the answer is no,
however clearly you can see that a conflict exists. Say nothing and wait for the action that
actually breaks it.

A conflict between two agents has two halves, and only one of them is in front of you. Split the
repair between the two fields, and do not put the same work in both.

`fix` is what the ACTING agent can do in its own checkout. It is not "undo this". The action in
front of you is the work that agent was assigned, and telling it to abandon that work does not
repair anything, it just moves the failure to the other task. Do not offer an alias, a shim, an
overload or a kept-alive old name as the fix either, and never offer a fix the developer's rules
forbid. When the acting agent genuinely cannot do anything about this from where it stands, leave
`fix` empty and say so in `why`.

`other_fix` is the half that can only be done in the OTHER agent's checkout. When you have been
told the two versions sit in separate checkouts, the acting agent cannot write into theirs, so the
repair on their side belongs here and nowhere else. Address it to that agent in the second person,
name the file by the path given for it, and state the exact current form their call has to move to,
taken from what the acting agent actually wrote. Leave `other_fix` empty only when no other agent
is involved, or when the acting agent can finish the whole repair itself.

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
 "fix": "<what the acting agent should do in ITS OWN checkout, one sentence; never \"undo this\", never an alias or shim; \"\" if there is nothing it can do>",
 "other_fix": "<the repair only the OTHER agent's checkout can take, addressed to them in the second person, or \"\">"}"""


def _acting_path(action):
    first = (action or "").splitlines()[0].strip() if action else ""
    return first if first.startswith("/") or "/" in first else ""


def _separate(a, b):
    """True when two paths end in the same declared file but sit under different roots."""
    a, b = (a or "").lstrip("/"), (b or "").lstrip("/")
    if not a or not b or a == b:
        return False
    pa, pb = a.split("/"), b.split("/")
    tail = 0
    while tail < min(len(pa), len(pb)) and pa[-1 - tail] == pb[-1 - tail]:
        tail += 1
    return tail > 0 and (len(pa) > tail or len(pb) > tail)


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
        # Whether the two versions sit in separate checkouts is not a guess: it is read off the
        # paths. It decides which half of a repair the acting agent is able to carry out at all,
        # and so whether there is anything to put in other_fix.
        mine = _acting_path(action)
        elsewhere = [ed.get("where") for es in others.values() for ed in es if ed.get("where")]
        if mine and any(_separate(mine, w) for w in elsewhere):
            lines.append("  these are separate checkouts of the same file: the agent acting is "
                         "writing in its own and cannot write into theirs, so any repair that "
                         "has to happen in their copy is work only they can do")
        for who, edits in list(others.items())[:3]:
            for ed in edits[-2:]:
                if ed.get("where"):
                    lines.append("  %s is working in: %s" % (who[:9], ed["where"]))
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
        return dict(breaks=False, rule=None, said="", does="", why="", fix="", other_fix="",
                    source="judge")
    by_id = {p["id"]: p["rule"] for p in R.stated(tm)}
    rid = out.get("rule")
    if rid not in by_id:
        return dict(breaks=False, rule=None, said="", does="", why="cited a rule that is not in "
                    "the list: %r" % rid, fix="", other_fix="", source="invalid-citation")
    return dict(breaks=True, rule=rid, said=by_id[rid],
                does=str(out.get("does") or "")[:300], why=str(out.get("why") or "")[:300],
                fix=str(out.get("fix") or "")[:300],
                other_fix=str(out.get("other_fix") or "")[:300], source="judge")


def judge(tm, action, trigger, brief="", agent_state=None, model=MODEL):
    """Fails open: a timeout, a crash or unparseable output all mean no, and the work carries on."""
    text, err = j2.run(SYSTEM, _payload(tm, action, trigger, brief, agent_state or {}),
                       model, TIMEOUT_S)
    if err or not text:
        return dict(breaks=False, rule=None, said="", does="", why=err or "empty",
                    fix="", other_fix="", source="unavailable")
    raw = j2._extract_json(text)
    out = _validate(raw, tm) if raw else None
    if out is None:
        return dict(breaks=False, rule=None, said="", does="", why="unparseable", fix="",
                    other_fix="", source="unavailable")
    return out
