#!/usr/bin/env python3
"""The task description, read from whatever the task already ships.

v4 asked the developer to write RULES.md. A reviewer called that out: it is not the baseline,
because the developer is being asked to restate the task in a second document. The SWE-Marathon
example proved the point - its RULES.md was a hand-transcription of CONTRACTS.md, line for line,
and the one line I transcribed wrong produced a confident, completely wrong block that cost a
whole run.

So there is no second document. The tool reads the task description the developer already wrote
and hands it to the judge. Nothing is extracted, summarised or rewritten on the way: whatever the
judge cites, it has to quote verbatim, and judge5 checks the quote is really in this text.
"""
import hashlib, os

# In preference order. The first that exists wins, unless OV_TASK_FILE names one.
NAMES = ("PROMPT.md", "TASK.md", "CONTRACTS.md", "SPEC.md", "README.md")


def path(proj):
    named = os.environ.get("OV_TASK_FILE")
    if named:
        p = named if os.path.isabs(named) else os.path.join(proj, named)
        return p if os.path.exists(p) else None
    for n in NAMES:
        p = os.path.join(proj, n)
        if os.path.exists(p):
            return p
    return None


def load(proj):
    """The task text, plus every file that contributed to it.

    CONTRACTS.md is read alongside PROMPT.md when both exist: a task that pins its seams in a
    second file is still one task description, and the agents are given both.
    """
    parts, used = [], []
    primary = path(proj)
    if primary:
        parts.append(open(primary, errors="ignore").read())
        used.append(os.path.basename(primary))
    if not os.environ.get("OV_TASK_FILE"):
        for n in ("CONTRACTS.md",):
            p = os.path.join(proj, n)
            if os.path.exists(p) and os.path.basename(p) not in used:
                parts.append(open(p, errors="ignore").read())
                used.append(n)
    return dict(text="\n\n".join(parts), files=used)


def stated(tk):
    return bool((tk or {}).get("text", "").strip())


def signature(tk):
    """Changes when the task text changes, so a cached answer never outlives its reason."""
    return hashlib.sha1((tk or {}).get("text", "").encode()).hexdigest()[:12]
