#!/usr/bin/env python3
"""The developer's rules, read from a file they wrote. No model is involved.

This replaces v3's extractor. The extractor read the brief, asked an LLM for the rules, and then
had to spend a provenance check, a verbatim-quote check and a five-draw consensus vote defending
itself against its own output -- because it had twice produced a rule the developer never wrote,
and once dropped the only rule that mattered as a minority opinion.

None of that machinery is needed if the developer writes the rules down. A rule here is theirs by
construction. It cannot be invented, it cannot be out-voted, and the notice can quote it back
verbatim because the string in the notice is the string in their file.

The cost is that the developer has to write RULES.md. That is the trade this version makes.
"""
import os, re

FILENAME = "RULES.md"

HEAD_RE = re.compile(r"^#{1,6}\s*(.+?)\s*$")
ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.+?)\s*$")


def path(proj):
    return os.path.join(proj, FILENAME)


def _sections(text):
    """{heading lowercased: [lines]}. Anything before the first heading lands under ''."""
    out, cur = {}, ""
    out[cur] = []
    for line in (text or "").splitlines():
        h = HEAD_RE.match(line)
        if h:
            cur = h.group(1).strip().lower()
            out.setdefault(cur, [])
            continue
        if line.strip():
            out[cur].append(line)
    return out


def _items(lines):
    """Bullets if there are any, otherwise every non-empty line. Lets the developer write either."""
    bullets = [m.group(1) for m in (ITEM_RE.match(l) for l in lines) if m]
    return bullets or [l.strip() for l in lines if l.strip() and not l.strip().startswith(">")]


def parse(text):
    """RULES.md -> a task model v3's filter and lookups already understand.

    Three sections, all optional. Headings are matched on their first word so "## Rules",
    "## Hard rules" and "## My rules" are the same section.
    """
    sec = _sections(text)

    def pick(*names):
        for k, v in sec.items():
            if any(k.startswith(n) for n in names):
                return _items(v)
        return []

    rules = pick("rule", "hard rule", "constraint")
    graded = pick("graded", "protected", "test")
    ifaces = pick("interface", "shared", "contract")

    prefs = []
    for i, r in enumerate(rules, 1):
        prefs.append(dict(id="H%d" % i, category="H", rule=r, when="always",
                          source="developer", priority="hard", quote=r,
                          serves=[], metrics=["tests"], files=[]))

    # The graded set reaches v3's lookups two ways, because they read it two ways: whole
    # directories through the rule text graded_dirs() scans, individual files through a
    # requirement's check_files.
    reqs = []
    dirs = [g for g in graded if not g.endswith((".py", ".js", ".ts", ".go"))]
    files = [g for g in graded if g.endswith((".py", ".js", ".ts", ".go"))]
    if dirs:
        prefs.append(dict(id="H-graded", category="H",
                          rule="Never edit, skip or weaken anything under " +
                               ", ".join(d.rstrip("/") + "/" for d in dirs),
                          when="always", source="developer", priority="hard",
                          quote="", serves=[], metrics=["tests"], files=[]))
    if files:
        reqs.append(dict(id="G1", text="The checks the developer protected", check="",
                         check_files=files, spec_quote=""))

    if ifaces:
        prefs.append(dict(id="H-interface", category="P2",
                          rule="These files are shared contracts: " + ", ".join(ifaces),
                          when="always", source="developer", priority="hard",
                          quote="", serves=[], metrics=["tests"], files=ifaces))

    return dict(requirements=reqs, preferences=prefs, agents={}, decisions=[], state={},
                graded_dirs=[d.rstrip("/") + "/" for d in dirs],
                source=dict(kind="developer-written", file=FILENAME, rules=len(rules),
                            graded=len(graded), interfaces=len(ifaces)))


def load(proj):
    try:
        with open(path(proj)) as f:
            return parse(f.read())
    except FileNotFoundError:
        return dict(requirements=[], preferences=[], agents={}, decisions=[], state={},
                    source=dict(kind="missing", file=FILENAME))


def stated(tm):
    """The rules as the developer wrote them, for the judge payload and the notice."""
    return [p for p in tm.get("preferences", []) if p.get("priority") == "hard"]


def signature(tm):
    """Changes when the rules change, so a cached verdict never outlives the rule behind it."""
    import hashlib
    return hashlib.sha1("|".join(p["rule"] for p in stated(tm)).encode()).hexdigest()[:12]
