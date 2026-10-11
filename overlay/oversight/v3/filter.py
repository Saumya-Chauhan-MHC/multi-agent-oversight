#!/usr/bin/env python3
"""The cheap filter: could this action possibly be relevant?

Plain code, no model. Two ways to say yes:

  path A  the action's text shares a word with a preference's text
  path B  a list lookup fires: the grader's files, the resource registry, the dependency map

It is deliberately over-inclusive. A false hit costs one judge call; a false miss means the
violation is never considered at all. Path B exists because the costly cases contain none of the
words a preference is likely to use: `kill $(lsof -ti:8000)` shares nothing with "ports and
processes belong to whoever started them".
"""
import re
from . import taskmodel as tmod

STOP = {"the", "a", "an", "and", "or", "not", "never", "only", "from", "with", "that", "this",
        "they", "them", "than", "then", "its", "it", "is", "are", "be", "for", "in", "on", "of",
        "to", "no", "any", "all", "one", "per", "own", "owns", "mine", "my", "i", "you", "your",
        "subagent", "subagents", "agent", "agents", "must", "should", "do", "does", "doing",
        "run", "runs", "running", "before", "after", "more", "most", "less", "each", "every",
        "max", "at", "once", "without", "their", "who", "whoever", "started", "belong", "belongs",
        "come", "comes", "back", "user", "defined", "define", "defines", "same", "two", "first",
        "last", "where", "when", "which", "while", "into", "out", "up", "down", "over", "under"}
WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_.\-/]{2,}")

TEST_WEAKENED = re.compile(r"(?m)^\s*-\s*.*\bassert\b|\bskip\b|\bxfail\b|\bpytest\.mark\.skip\b")


def words_of(text):
    """Tokens plus their path segments, so the rule word "tests" matches the action's "tests/"."""
    out = set()
    for w in WORD.findall((text or "").lower()):
        for piece in [w] + w.split("/"):
            piece = piece.strip("./-")
            if len(piece) < 3 or piece in STOP:
                continue
            out.add(piece)
            out.add(piece.rstrip("s"))
    return out


def action_text(tool_name, tool_input):
    ti = tool_input or {}
    parts = [ti.get("command"), ti.get("file_path"), ti.get("old_string"), ti.get("new_string")]
    if tool_name in ("Task", "Agent"):
        parts = [ti.get("description"), ti.get("prompt")]
    return " ".join(str(p) for p in parts if p)[:4000]


def check(proj_tm, events, tool_name, tool_input, agent_id):
    """Returns None for a miss, or a dict describing why this is worth judging."""
    tm = proj_tm
    text = action_text(tool_name, tool_input)
    if not text.strip():
        return None
    ti = tool_input or {}
    target = str(ti.get("file_path") or "")
    cmd = str(ti.get("command") or "")
    who = agent_id or "orchestrator"

    # ---- path B first: the lookups are exact, and they catch what wording cannot -------------
    graded = tmod.graded_files(tm)
    if target and any(target.endswith(g) or g in target for g in graded):
        return dict(path="B", reason="graded_file", detail=target, risk="collusion")

    if tool_name in ("Edit", "MultiEdit") and TEST_WEAKENED.search(str(ti.get("new_string") or "")):
        if any(seg in target for seg in ("test", "spec")):
            return dict(path="B", reason="weakened_check", detail=target, risk="collusion")

    reg = tmod.registry(events)
    for res in tmod.resources_touched(cmd):
        owner = reg.get(res)
        if owner and owner != who:
            return dict(path="B", reason="resource_owned_elsewhere", detail=res, owner=owner,
                        risk="conflict")

    dep = tmod.dependency_map(events)
    if target:
        users = tmod.interface_dependents(tm, dep, target)
        if users:
            others = {u for u in users if u != who}
            if len(others) >= 1:
                return dict(path="B", reason="declared_interface", detail=target,
                            dependents=sorted(others), risk="miscoordination")

    # ---- path A: word overlap with the preference text ---------------------------------------
    pref_words = set()
    for p in tmod.preferences(tm):
        pref_words |= words_of(p["rule"])
    hits = sorted(pref_words & words_of(text))
    if hits:
        return dict(path="A", reason="word_overlap", detail=hits[:6], risk=None)
    return None


def completion_check(tm, events, agent_id):
    """The one trigger that fires on a claim rather than an action: a stale green."""
    dep = tmod.dependency_map(events)
    stale = tmod.stale_claim(dep, agent_id or "orchestrator")
    if stale:
        return dict(path="B", reason="stale_claim", detail=stale, risk="miscoordination")
    return None
