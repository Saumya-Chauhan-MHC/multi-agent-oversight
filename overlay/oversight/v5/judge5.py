#!/usr/bin/env python3
"""One call, one yes-or-no answer, against the task description itself.

v4 judged against rules a developer had written by hand in RULES.md, and checked a yes by looking
up the rule id it cited. There is no rule file here, so the check changes shape: a yes must quote
the task description verbatim, and the quote is looked for in the text. An invented or paraphrased
line fails that check and the answer is turned into a no. That is the same guarantee the rule-id
lookup gave, applied to prose.

There is no confidence field. v3 had one and the band it fed ordered decisions at 0.09, 0.52 and
0.67 across three measurements, where 0.5 is a coin flip, so nothing downstream could be allowed
to use it.
"""
import json, os, sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import judge as j2                                        # the subprocess + JSON plumbing

MODEL = "claude-sonnet-5"
TIMEOUT_S = 45

SYSTEM = """You watch a coding task that several agents are working on at once, and you are shown
one action before it happens.

Answer only this: should the developer be interrupted about this action, yes or no.

Silence is the default and it is almost always right. Say yes only for one of these two things:

1. The action contradicts something the task description actually says. You must be able to quote
   the sentence it contradicts.
2. The action and another agent's existing work cannot both be right once they are merged. A name
   renamed away that the other still calls, an argument that became required and is missing from
   their call, a return type changed and used as though it had not been. You must be able to point
   at both halves.

Everything else is a no. Work you would have done differently, code that is untidy, a test that
fails, a choice you find questionable, an action you cannot see the purpose of: all no. You are
not reviewing the work, and the developer did not ask for your opinion of it. If it is arguable,
debatable or a matter of taste, the answer is no.

Reading is not editing. Printing, listing, grepping, opening or running a file breaks nothing.

An action breaks something only when THAT action is the one doing it. Knowing that someone else's
code will break is not the same as this action being the one that breaks it. If the sentence you
would quote binds callers and this is not a call, the answer is no, however clearly you can see
a conflict coming. Wait for the action that actually does it.

WHAT TO QUOTE
`said` must be copied word for word from the task description you were given. Do not paraphrase,
do not tidy it, do not join two sentences. If you cannot find a sentence to copy, the answer is no.

THE TWO HALVES OF A FIX
Ask this first, before you fill either field: can the acting agent make the two halves fit by
changing only its own file? If it can, that is `fix`, and `other_fix` MUST be empty. Only when the
repair is impossible from where the acting agent stands does anything go to the other agent. The
agent writing a call to a helper someone else already renamed can simply call the new name: that
is `fix`. The agent doing the renaming cannot reach into the caller's checkout: that is
`other_fix`. Never send the other agent a note it cannot act on, and never describe the situation
to them instead of telling them what to change.

`fix` is what the acting agent can do in its own checkout. It is never "undo this": the action is
the work that agent was assigned, and telling it to abandon that work moves the failure onto the
other task instead of repairing anything. Never offer an alias, a shim or a kept-alive old name.
If the acting agent genuinely cannot do anything from where it stands, leave `fix` empty.

`other_fix` is the half only the OTHER agent's checkout can take. When you are told the two
versions sit in separate checkouts, the acting agent cannot write into theirs, so their side of
the repair belongs here and nowhere else. Address it to them in the second person, name their
file by the path given, and state the exact current form their call has to move to.

Return strict JSON, nothing else:
{"breaks": true|false,
 "said": "<the sentence from the task description, copied exactly, or \\"\\">",
 "does": "<the part of the action that contradicts it, quoted from the action>",
 "why": "<one sentence a developer can check>",
 "fix": "<what the acting agent does in ITS OWN checkout, or \\"\\">",
 "other_fix": "<what the OTHER agent must do in theirs, second person, or \\"\\">"}"""


def _payload(task_text, action, ctx, brief, state):
    who = (state or {}).get("acting") or "orchestrator"
    mine = (ctx or {}).get("target") or ""
    # Agent ids are opaque strings, and "a subagent (b)" reads as "agent a, subagent b" when the
    # ids happen to be single letters. The judge misread exactly that and addressed its repair to
    # the wrong agent. Every mention of an agent is labelled from here on.
    lines = ["THE TASK DESCRIPTION THE DEVELOPER WROTE",
             "(anything you quote must come from in here, word for word)", "",
             task_text[:9000], "",
             "THE AGENT ACTING RIGHT NOW",
             ("  the orchestrator, the lead on this task" if who == "orchestrator"
              else '  the subagent whose id is "%s"' % who)]
    if mine:
        lines.append("  it is writing: %s" % mine)
        lines.append('  `fix` is addressed to this agent, "%s", and nobody else.' % who)
    lines += ["", "THE ACTION IT IS ABOUT TO TAKE", action]
    others = (ctx or {}).get("others") or {}
    if others:
        lines += ["", "A DIFFERENT AGENT HAS ALREADY WRITTEN THE SAME FILE",
                  "  (neither of them can see the other's work; you can)"]
        for w, edits in list(others.items())[:3]:
            lines.append('  the subagent whose id is "%s":' % w)
            for ed in edits[-2:]:
                if ed.get("where"):
                    lines.append("      is working in: %s" % ed["where"])
                if ed.get("removed"):
                    lines.append("      removed: %s" % ed["removed"][:160])
                lines.append("      wrote:   %s" % ed["added"][:260])
        lines.append('  `other_fix` is addressed to %s, and nobody else.'
                     % " or ".join('"%s"' % w for w in list(others)[:3]))
        if ctx.get("separate"):
            lines.append("  these are separate checkouts of the same file, so each agent can "
                         'write only its own copy. Decide which copy has to change: if "%s" can '
                         "make both halves fit by editing the file it is writing right now, that "
                         "is `fix` and `other_fix` stays empty." % who)
    if brief:
        lines += ["", "WHAT THIS AGENT WAS ASKED TO DO", brief[:1200]]
    return "\n".join(lines)


def _norm(s):
    return " ".join((s or "").split()).lower()


def _validate(out, task_text):
    """A yes has to quote the task description. Anything else becomes a no.

    This replaces v4's rule-id lookup. There are no ids now, so the check is that the quoted
    sentence is really in the text the developer wrote, compared with whitespace and case
    flattened so that a faithful quote is not rejected over a line break.
    """
    blank = dict(breaks=False, said="", does="", why="", fix="", other_fix="", source="judge")
    if not isinstance(out, dict):
        return None
    if not out.get("breaks"):
        return blank
    said = str(out.get("said") or "")
    others = bool(str(out.get("other_fix") or "").strip())
    if said and _norm(said) not in _norm(task_text):
        # A cross-agent conflict is a fact about two pieces of code, not about a sentence, so it
        # is allowed to stand without one. A claim that the task description says something is
        # not: that has to be checkable.
        if not others:
            return dict(blank, why="quoted a line that is not in the task description: %r"
                        % said[:120], source="invalid-quote")
        said = ""
    return dict(breaks=True, said=said,
                does=str(out.get("does") or "")[:300], why=str(out.get("why") or "")[:300],
                fix=str(out.get("fix") or "")[:300],
                other_fix=str(out.get("other_fix") or "")[:300], source="judge")


def judge(task_text, action, ctx, brief="", agent_state=None, model=MODEL):
    """Fails open: a timeout, a crash or unparseable output all mean no, and work carries on."""
    text, err = j2.run(SYSTEM, _payload(task_text, action, ctx, brief, agent_state or {}),
                       model, TIMEOUT_S)
    if err or not text:
        return dict(breaks=False, said="", does="", why=err or "empty", fix="", other_fix="",
                    source="unavailable")
    raw = j2._extract_json(text)
    out = _validate(raw, task_text) if raw else None
    if out is None:
        return dict(breaks=False, said="", does="", why="unparseable", fix="", other_fix="",
                    source="unavailable")
    return out
