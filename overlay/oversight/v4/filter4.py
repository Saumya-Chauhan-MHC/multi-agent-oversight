#!/usr/bin/env python3
"""The filter, with one lookup v3 does not have: file ownership.

Arm F found the gap. The developer's RULES.md said "do NOT write start.sh or a supervisor" and
"never edit a file you don't own", the lead agent wrote both start.sh and bin/supervisor.py, and
the tool said nothing. Those writes matched no structural lookup, so they fell through to the
recall net, which in v4 never reaches the judge.

That is worse than a miss. It means RULES.md can hold a rule the filter has no way to enforce, so
the developer writes a rule down and gets silence. Every rule shape the file permits needs a
lookup behind it, and ownership was the shape with nothing behind it.

The lookup itself is deliberately dumb: is this path in the ownership table at all. Whether the
agent acting is the owner is a question about identity, which the judge answers from the brief,
because agent ids are opaque strings and the table is written in human names.
"""
import os, re
from ..v3 import filter as f3


def _norm(p):
    return (p or "").replace("\\", "/").strip().lstrip("./")


CALLISH = re.compile(r"^\s*(?:def |return |.*=\s*)?\w[\w.]*\s*\(")


def _squeeze(text, budget):
    """Keep the head, then the lines that look like definitions or calls.

    A flat head-truncation at 400 characters lost the one line that mattered. In a real diff the
    changed signature is near the top and the call site that depends on it is further down, past
    a docstring, so the judge was shown the change and not the thing the change breaks.
    """
    t = text or ""
    if len(t) <= budget:
        return t
    lines = t.splitlines()
    head, rest = lines[:12], lines[12:]
    picked = [l for l in rest if CALLISH.match(l)]
    out = "\n".join(head)
    if picked:
        out += "\n... \n" + "\n".join(picked)
    return out[:budget]


def owner_of(tm, target):
    """(owner, pattern) for the first ownership entry matching this path, or (None, None)."""
    t = _norm(target)
    if not t:
        return None, None
    best = (None, None, -1)
    for owner, pats in (tm.get("ownership") or {}).items():
        for pat in pats:
            p = _norm(pat).rstrip("*").rstrip("/")
            if not p:
                continue
            hit = t == p or t.endswith("/" + p) or ("/" + p + "/") in ("/" + t + "/")
            if not hit and p.endswith((".py", ".sh", ".md", ".js", ".ts")):
                hit = t.endswith("/" + p) or t == p
            if hit and len(p) > best[2]:
                best = (owner, pat, len(p))
    return best[0], best[1]


def others_on(events, pattern, agent_id):
    """Other agents that have already written the same declared path, and what they wrote.

    The declared path is the key, not the absolute one. Two agents working in separate git
    worktrees write `.../wt_a/django/utils/html.py` and `.../wt_b/django/utils/html.py`, which
    are different files on disk and the same file in the project. v3's `same_file` says they are
    unrelated, so the dependency map never links them and the interface trigger never fires.

    `where` keeps the absolute path as well as the declared one. The declared path is what links
    the two agents; the absolute path is the only thing that says which checkout the repair has to
    land in, and a repair in the wrong checkout is not picked up by the merge.

    This is the one thing the oversight layer has that neither agent has. The agents are isolated
    from each other on purpose; the tool sees both. Without this the judge is asked whether an
    action is stale while being shown only that action.
    """
    pat = _norm(pattern).rstrip("*").rstrip("/")
    out = {}
    for e in events:
        if e.get("ov_event") != "pre_tool":
            continue
        if e.get("tool_name") not in ("Write", "Edit", "MultiEdit"):
            continue
        who = e.get("agent_id") or "orchestrator"
        if who == agent_id:
            continue
        ti = e.get("tool_input") or {}
        if not _norm(str(ti.get("file_path") or "")).endswith(pat):
            continue
        body = str(ti.get("new_string") or ti.get("content") or "")
        prev = str(ti.get("old_string") or "")
        out.setdefault(who, []).append(dict(removed=_squeeze(prev, 500),
                                            added=_squeeze(body, 1600),
                                            where=_norm(str(ti.get("file_path") or ""))))
    return out


def check(tm, events, tool_name, tool_input, agent_id):
    """Ownership first, because it is the most specific thing we can say about a path.

    Returns the same shape as v3's filter so everything downstream is unchanged.
    """
    ti = tool_input or {}
    if tool_name in ("Write", "Edit", "MultiEdit"):
        owner, pat = owner_of(tm, str(ti.get("file_path") or ""))
        if owner:
            others = others_on(events, pat, agent_id or "orchestrator")
            return dict(path="B", reason="owned_file", detail=pat, owner=owner,
                        others=others,
                        risk="miscoordination" if others else
                             ("conflict" if owner != "nobody" else "collusion"))
    return f3.check(tm, events, tool_name, tool_input, agent_id)


def action_text(tool_name, tool_input):
    """v3's version, except that an edit is rendered as a labelled before and after.

    v3 joins the parts with spaces, so an Edit reaches the judge as
    `path - def strip_tags(v): + def strip_tags_v2(v):` on one line. Twice in testing the judge
    read that as an addition rather than a replacement and reported a rename as "keeps both forms
    defined alongside each other", which is the opposite of what happened. The field it then fills
    is the one the agent is told to act on, so a misread diff becomes a wrong instruction.

    v3's own function is left alone on purpose: it is what every earlier measurement was taken
    with, and changing it would make those numbers incomparable.
    """
    ti = tool_input or {}
    if tool_name in ("Edit", "MultiEdit"):
        pairs = [(ti.get("old_string"), ti.get("new_string"))]
        pairs += [(e.get("old_string"), e.get("new_string")) for e in (ti.get("edits") or [])]
        out = [str(ti.get("file_path") or "")]
        for old, new in pairs:
            if not (old or new):
                continue
            out += ["", "REPLACED THIS:", f3._salient(old, f3.BUDGET // 2) or "(nothing)",
                    "WITH THIS:", f3._salient(new, f3.BUDGET // 2) or "(nothing, it was deleted)"]
        return "\n".join(out)
    return f3.action_text(tool_name, tool_input)
