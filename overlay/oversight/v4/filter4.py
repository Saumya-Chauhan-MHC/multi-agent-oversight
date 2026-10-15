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
import os
from ..v3 import filter as f3


def _norm(p):
    return (p or "").replace("\\", "/").strip().lstrip("./")


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


def check(tm, events, tool_name, tool_input, agent_id):
    """Ownership first, because it is the most specific thing we can say about a path.

    Returns the same shape as v3's filter so everything downstream is unchanged.
    """
    ti = tool_input or {}
    if tool_name in ("Write", "Edit", "MultiEdit"):
        owner, pat = owner_of(tm, str(ti.get("file_path") or ""))
        if owner:
            return dict(path="B", reason="owned_file", detail=pat, owner=owner,
                        risk="conflict" if owner != "nobody" else "collusion")
    return f3.check(tm, events, tool_name, tool_input, agent_id)


action_text = f3.action_text
