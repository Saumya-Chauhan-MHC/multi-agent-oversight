#!/usr/bin/env python3
"""What the judge is shown. No gating: this decides content, never whether to ask.

v4 had a filter in front of the judge - six structural lookups plus a word-overlap recall net -
and an action that matched none of them was never judged at all. Two things were wrong with that.
A rule the developer could write but no lookup covered produced silence, which is worse than a
miss, and it was the arm F bug exactly. And the recall net cost 216 judge calls across two arms
for 0 of 8 correct, so the cheap half was also the useless half.

Here every editing action is judged. What stays from the filter is the one thing it was actually
good for: finding what other agents did to the same declared path. That is not a gate, it is the
single fact neither agent can see and the oversight layer can, and without it the judge would be
asked whether an action is stale while being shown only that action.
"""
import os, re

CALLISH = re.compile(r"^\s*(?:def |return |.*=\s*)?\w[\w.]*\s*\(")
# Bash belongs here. `sed -i`, `rm`, `mv`, `git checkout` and `kill` all change the repository or
# the environment, and on a resource conflict the destructive act is almost always a shell command
# rather than an edit. v4 judged Bash; dropping it in v5 was an oversight, not a decision.
WATCHED = ("Bash", "Write", "Edit", "MultiEdit", "Task", "Agent")


def _norm(p):
    return (p or "").replace("\\", "/").strip().lstrip("./")


def squeeze(text, budget):
    """Head lines, then the lines that look like definitions or calls.

    A flat truncation at 400 characters once cut off `return host + iri_to_uri(path)`, the one
    line the whole judgement turned on. The changed signature sits near the top of a diff and the
    call that depends on it sits further down, past a docstring.
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


def action_text(tool_name, tool_input):
    """An edit is rendered as a labelled before and after.

    Joined with spaces it reads as `path - def f(): + def f_v2():` on one line, and the judge
    twice read that as an addition rather than a replacement, reporting a rename as "keeps both
    forms defined".
    """
    ti = tool_input or {}
    if tool_name in ("Task", "Agent"):
        return " ".join(str(ti.get(k) or "") for k in ("description", "prompt"))[:4000]
    if tool_name == "Write":
        return "%s\n\n%s" % (ti.get("file_path") or "", squeeze(ti.get("content"), 2000))
    if tool_name in ("Edit", "MultiEdit"):
        pairs = [(ti.get("old_string"), ti.get("new_string"))]
        pairs += [(e.get("old_string"), e.get("new_string")) for e in (ti.get("edits") or [])]
        out = [str(ti.get("file_path") or "")]
        for old, new in pairs:
            if not (old or new):
                continue
            out += ["", "REPLACED THIS:", squeeze(old, 1000) or "(nothing)",
                    "WITH THIS:", squeeze(new, 1000) or "(nothing, it was deleted)"]
        return "\n".join(out)
    return " ".join(str(ti.get(k) or "") for k in ("command", "file_path"))[:2000]


PATHISH = re.compile(r"[\w./~-]*/[\w./-]+\.\w+|\b[\w-]+\.(?:py|js|ts|go|rb|java|json|ya?ml|sh|md|toml|cfg|ini)\b")


def targets(tool_name, tool_input):
    """Every file this action could touch.

    An edit names its file. A shell command does not, so the paths are read out of the command
    text. Adding Bash to the watched set without this was half a fix: the command reached the
    judge with no idea which file it was about, so `rm -f other_agent/checkout/html.py` was
    judged with no cross-agent context and came back silent, which is the exact failure the
    watched set was widened to catch.
    """
    ti = tool_input or {}
    if tool_name == "Bash":
        cmd = str(ti.get("command") or "")
        seen, out = set(), []
        for m in PATHISH.findall(cmd):
            n = _norm(m)
            if n and n not in seen:
                seen.add(n)
                out.append(n)
        return out[:8]
    p = _norm(str(ti.get("file_path") or ""))
    return [p] if p else []


def target(tool_name, tool_input):
    """The single path, where there is one. Kept for callers that want a scalar."""
    t = targets(tool_name, tool_input)
    return t[0] if t else ""


def others_sig(others):
    """A short digest of what other agents have written to this file.

    It belongs in the judged-cache key. Without it the cache answers a question it was never
    asked: the same action by the same agent under the same task text can be harmless at one
    moment and a conflict a minute later, because somebody else changed the file in between. The
    cache would serve the old "no" and the hold would never happen.
    """
    import hashlib
    parts = []
    for who in sorted(others or {}):
        for ed in others[who]:
            parts.append("%s:%s:%s" % (who, ed.get("where", ""), (ed.get("added") or "")[:200]))
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:10] if parts else "none"


def others_on(events, declared, agent_id):
    """Other agents that have written the same declared path, and what they wrote.

    Keyed on the declared path, not the absolute one. Two agents in separate git worktrees write
    `.../wt_a/django/utils/html.py` and `.../wt_b/django/utils/html.py`: different files on disk,
    the same file in the project. `where` keeps the absolute path too, because that is the only
    thing that says which checkout a repair has to land in.
    """
    tail = _norm(declared)
    if not tail:
        return {}
    out = {}
    for e in events:
        if e.get("ov_event") != "pre_tool" or e.get("tool_name") not in ("Write", "Edit", "MultiEdit"):
            continue
        who = e.get("agent_id") or "orchestrator"
        if who == agent_id:
            continue
        ti = e.get("tool_input") or {}
        p = _norm(str(ti.get("file_path") or ""))
        if not same_declared_file(tail, p):
            continue
        out.setdefault(who, []).append(dict(
            removed=squeeze(str(ti.get("old_string") or ""), 500),
            added=squeeze(str(ti.get("new_string") or ti.get("content") or ""), 1600),
            where=p))
    return out


def same_declared_file(a, b):
    """Are these two paths the same file in the project, seen from two checkouts?

    Matching on the last three segments was the first attempt and it breaks on a file near the
    root of a checkout: `wt_a/m.py` and `wt_b/m.py` share only `m.py`, so they never linked, and
    the agents' work went unconnected. The rule now is the one that actually describes the
    situation: identical path under two roots that differ by a single directory name.

    "One segment apart" alone is not enough, and SWE-Marathon shows why: four agents own parallel
    trees there, so `huddle/api/__init__.py` and `huddle/irc/__init__.py` are one segment apart
    and are nothing to do with each other. So is `tests/api/conftest.py` against
    `tests/irc/conftest.py`, and `huddle/api/routes.py` against `huddle/web/routes.py`. Linking
    those would hand the judge a cross-agent conflict that does not exist and invent holds out of
    two agents doing their own jobs.

    The two cases cannot be told apart by the shape of the path, because they have the same shape.
    So the real question is asked instead: is the segment they differ by a separate checkout? A
    git worktree has a `.git` entry at its root, and that is checked on disk. Where the paths are
    not on disk to check, the rule falls back to requiring the shared tail to be a real path
    rather than a bare filename, which keeps `django/utils/html.py` and rejects `routes.py`.
    """
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return False
    if a == b:
        return True
    pa, pb = [x for x in a.split("/") if x], [x for x in b.split("/") if x]
    if len(pa) != len(pb) or pa[-1] != pb[-1]:
        return False
    differ = [i for i, (x, y) in enumerate(zip(pa, pb)) if x != y]
    if len(differ) != 1:
        return False
    i = differ[0]
    ra, rb = "/".join(pa[:i + 1]), "/".join(pb[:i + 1])
    checkouts = [r for r in ("/" + ra, "/" + rb)
                 if os.path.exists(os.path.join(r, ".git"))]
    if len(checkouts) == 2:
        return True                               # two checkouts of one repository
    if any(os.path.exists("/" + r) for r in (ra, rb)):
        return False                              # on disk, and not checkouts: sibling directories
    return len(pa) - (i + 1) >= 2                 # not on disk: require a real shared tail


def separate_checkouts(mine, theirs):
    """True when two paths end in the same file but sit under different roots."""
    a, b = _norm(mine), _norm(theirs)
    if not a or not b or a == b:
        return False
    pa, pb = a.split("/"), b.split("/")
    t = 0
    while t < min(len(pa), len(pb)) and pa[-1 - t] == pb[-1 - t]:
        t += 1
    return t > 0 and (len(pa) > t or len(pb) > t)
