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
import json, re

CALLISH = re.compile(r"^\s*(?:def |return |.*=\s*)?\w[\w.]*\s*\(")

# Every action is judged except the ones that certainly change nothing. Bash used to be left out
# as if it only read, but `sed -i`, `cat > file` and `kill` are all Bash: a test deleted with
# sed, or a dev server killed, was never seen. Same rule as the baseline monitor
# (overlay/oversight/baseline/core.py): a wrong skip hides an action, a needless judge call
# costs one call, so only what is certainly read-only is skipped.
READ_ONLY = {"Read", "Grep", "Glob", "LS", "NotebookRead", "WebSearch", "WebFetch", "ToolSearch",
             "TaskList", "TaskGet", "TaskOutput"}

# A Bash command is skipped only when every command in it is one of these and nothing in it can
# write. Running code (tests, python, scripts) is never read-only.
READ_CMDS = {"cat", "head", "tail", "less", "more", "grep", "egrep", "fgrep", "rg", "ls", "tree",
             "wc", "file", "stat", "du", "df", "pwd", "echo", "printf", "which", "type", "diff",
             "cut", "sort", "uniq", "nl", "od", "xxd", "hexdump", "basename", "dirname", "realpath",
             "readlink", "find", "awk", "sed", "jq", "true", "cd", "env", "date", "whoami", "id",
             "ps", "lsof", "test", "["}
GIT_READ = {"diff", "log", "show", "status", "blame", "grep", "ls-files", "rev-parse", "branch",
            "describe", "shortlog", "cat-file"}
_SPLIT = re.compile(r"&&|\|\||;|\||\n")
_WRITES = re.compile(r"(?<![0-9&])>(?!\s*/dev/null)|\$\(|`|\bsed\s+(-[a-zA-Z]*i|--in-place)|"
                     r"-exec\b|-execdir\b|-delete\b|-fprint|\bawk\b.*\bsystem\s*\(|\btee\b|<<")


def read_only_bash(cmd):
    """True only if the command certainly writes nothing and runs no code."""
    cmd = re.sub(r"\d?>&\d|\d>\s*/dev/null|&>\s*/dev/null", " ", cmd or "")
    if not cmd.strip() or _WRITES.search(cmd):
        return False
    for seg in _SPLIT.split(cmd):
        words = seg.split()
        while words and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]):
            words = words[1:]                       # FOO=bar cat x
        if not words:
            continue
        w = words[0].rsplit("/", 1)[-1]
        if w == "git":
            sub = next((x for x in words[1:] if not x.startswith("-")), "")
            if sub not in GIT_READ:
                return False
        elif w not in READ_CMDS:
            return False
    return True


def judged(tool_name, tool_input=None):
    """Whether this action goes to the judge: everything but certain reads."""
    ti = tool_input or {}
    if tool_name in READ_ONLY:
        return False
    if tool_name == "TaskUpdate" and not {"subject", "description"} & set(ti):
        return False                                # a status, owner or dependency change says nothing
    if tool_name == "Bash" and read_only_bash(ti.get("command")):
        return False
    return True


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
    if tool_name == "Bash":
        return " ".join(str(ti.get(k) or "") for k in ("command", "file_path"))[:2000]
    # Any other tool that reaches the judge: its name and its whole input, so it is not shown blank.
    return ("%s %s" % (tool_name, json.dumps(ti)))[:2000]


def target(tool_name, tool_input):
    return _norm(str((tool_input or {}).get("file_path") or ""))


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
    key = "/".join([p for p in tail.split("/") if p][-3:])
    out = {}
    for e in events:
        if e.get("ov_event") != "pre_tool" or e.get("tool_name") not in ("Write", "Edit", "MultiEdit"):
            continue
        who = e.get("agent_id") or "orchestrator"
        if who == agent_id:
            continue
        ti = e.get("tool_input") or {}
        p = _norm(str(ti.get("file_path") or ""))
        if not p.endswith(key) and not key.endswith("/".join(p.split("/")[-3:])):
            continue
        out.setdefault(who, []).append(dict(
            removed=squeeze(str(ti.get("old_string") or ""), 500),
            added=squeeze(str(ti.get("new_string") or ti.get("content") or ""), 1600),
            where=p))
    return out


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
