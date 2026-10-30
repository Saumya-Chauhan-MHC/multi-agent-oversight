#!/usr/bin/env python3
"""The preference model, and the one thing v3 never had: it changes when the developer answers.

v3 built `task_model.json` from the task description and then held it fixed for the whole run.
Every answer the developer gave was recorded next to the decision it was about and went nowhere
else, so the same preference could be argued down five times and still be on its original
wording the sixth. The SSOT asks for the opposite: an answer is evidence about the preference,
not only about the action, and the model should move.

Two rules keep that from turning into drift:

  1. Only an answered flag can move a preference, and only the preference that flag cited. A
     preference nobody was asked about is never rewritten.
  2. The judge is given the original wording and the developer's words, and is allowed exactly
     three outcomes: keep, narrow, or replace. It may not invent a preference, and a revision
     that does not quote the developer is refused and logged as `unquoted`, the same guarantee
     the verbatim check gives elsewhere.

Every revision is appended to the preference's own history, so "your preferences are changing"
is something the tool can show rather than assert: the original PRD wording, what it became, and
the sentence the developer said that moved it.
"""
import json, os, sys, time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import judge as j2
from v3 import taskmodel as tmod
from v3 import from_task

MODEL = os.environ.get("OV_JUDGE_MODEL", "claude-sonnet-5")
TIMEOUT_S = 45

# The four categories are fixed. Only the task-specific rules under them come from the PRD.
CATEGORIES = {
    "P1": "Ownership / decomposition. Prevent duplicated work, conflicting assignments, "
          "and unnecessary waiting.",
    "P2": "Shared interfaces. Prevent incompatible changes between dependent agents.",
    "P3": "Verification. Prevent accepting work that has not demonstrated the required behavior.",
    "P4": "Prioritization. Prevent optional work from delaying required behavior.",
}

SYSTEM = """A developer was shown one agent action that departed from a stated preference, and
they answered. Decide what their answer means for the preference itself, not for the action.

You get: the preference as it currently stands, where it came from, and exactly what the
developer said.

Answer with JSON and nothing else:

  {"verb": "keep" | "narrow" | "replace", "rule": "", "quote": "", "why": ""}

  keep     the answer was about this action only. Nothing about the preference changes. This is
           the right answer most of the time, including whenever they simply agreed with the flag.
  narrow   the preference still holds, but they named a case it should not cover. `rule` is the
           original wording with that exception added, changed as little as possible.
  replace  they stated a different rule. `rule` is that rule, in their terms.

`quote` must be copied word for word from what the developer said, and must be the part that
carries the change. If you cannot copy a sentence that does, the verb is `keep`.

Do not widen a preference. Do not tidy wording you are not changing. Do not infer a general
policy from one concrete answer: "not in this file" is a narrow, not a replace.
"""


def build(proj, text=None, source_file="instruction.md"):
    """Deterministic: the PRD's own bullets become the P1-P4 preference set. No model."""
    return from_task.write(proj) if text is None else from_task.build(text, source_file)


def history(tm, pid):
    for p in tmod.preferences(tm):
        if p.get("id") == pid:
            return p.get("history") or []
    return []


def changed(tm):
    """Every preference that has moved since the PRD, for showing the developer."""
    out = []
    for p in tmod.preferences(tm):
        h = p.get("history") or []
        if h:
            out.append(dict(id=p.get("id"), category=p.get("category"),
                            original=h[0].get("from"), now=p.get("rule"),
                            moved=len(h), because=h[-1].get("quote")))
    return out


def _ask(pref, decision, note):
    user = json.dumps(dict(
        preference=pref.get("rule"), category=pref.get("category"),
        source=pref.get("source", "PRD"),
        developer_answer=decision, developer_said=note or ""), indent=1)
    text, err = j2.run(SYSTEM, user, MODEL, TIMEOUT_S)
    if err or not text:
        return dict(verb="keep", why="judge unavailable: %s" % (err or "empty"))
    try:
        return j2._extract_json(text) or dict(verb="keep", why="unparseable")
    except Exception:
        return dict(verb="keep", why="unparseable")


def update_from_feedback(proj, pid, decision, note, tm=None):
    """Apply one answer to one preference. Returns what happened, for the event log.

    `decision` is accept or reject of the flag; `note` is whatever the developer typed. A revision
    is applied only when the judge can quote them, so an empty note can never move anything.
    """
    tm = tm if tm is not None else tmod.load(proj)
    pref = next((p for p in tmod.preferences(tm) if p.get("id") == pid), None)
    if pref is None:
        return dict(applied=False, why="no such preference: %s" % pid)

    # Agreement cannot weaken a preference. Asked to interpret "yes, that's right, it shouldn't
    # touch that", the judge narrowed the rule to "...except that resource family" -- it read a
    # confirmation as an exception and carved out exactly the case that had just been upheld.
    # The prompt already said to keep on agreement and it did not hold, so the rule is enforced
    # here instead: accepting a flag confirms the preference and can never change it. Changing a
    # preference requires rejecting the flag and saying what the rule should be.
    if str(decision).lower() in ("accept", "accepted", "agree", "yes"):
        return dict(applied=False, verb="keep", why="accepted: agreement confirms the preference")

    out = _ask(pref, decision, note)
    verb = (out.get("verb") or "keep").lower()
    if verb not in ("narrow", "replace"):
        return dict(applied=False, verb="keep", why=out.get("why", ""))

    quote = (out.get("quote") or "").strip()
    rule = (out.get("rule") or "").strip()
    # The same guarantee used everywhere else: a change the developer did not say does not happen.
    if not quote or quote.lower() not in (note or "").lower():
        return dict(applied=False, verb=verb, why="unquoted", attempted=rule)
    if not rule or rule == pref.get("rule"):
        return dict(applied=False, verb=verb, why="no change")

    pref.setdefault("history", []).append(
        dict(at=time.strftime("%F %T"), verb=verb, **{"from": pref.get("rule")},
             to=rule, quote=quote, decision=decision))
    pref["rule"] = rule
    pref["source"] = "human"
    tmod.save(proj, tm)
    return dict(applied=True, verb=verb, pid=pid, to=rule, quote=quote)
