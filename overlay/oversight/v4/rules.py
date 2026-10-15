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

    Sections are all optional. Headings are matched on their first word so "## Rules",
    "## Hard rules" and "## My rules" are the same section.
    """
    sec = _sections(text)

    def pick(*names):
        for k, v in sec.items():
            if any(k.startswith(n) for n in names):
                return _items(v)
        return []

    rules = pick("rule", "hard rule", "constraint")
    task = pick("task", "what", "goal")
    owners_raw = pick("owner", "file owner", "ownership")
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

    # "<owner>: path, path, path" per line. The owner name is whatever the developer calls that
    # agent in the brief, because the judge resolves it against the brief, not against an id.
    ownership = {}
    for line in owners_raw:
        if ":" not in line:
            continue
        who, paths = line.split(":", 1)
        who = who.strip().strip("`*_").lower()
        got = [p.strip().strip("`") for p in paths.replace("|", ",").split(",") if p.strip()]
        if who and got:
            ownership.setdefault(who, []).extend(got)

    return dict(requirements=reqs, preferences=prefs, agents={}, decisions=[], state={},
                ownership=ownership, task="\n".join(task),
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


def task_text(tm):
    """What the developer said the task is, for the places that have to weigh a rule against it.

    The orchestrator has no brief - nobody hands the lead its own instructions - so without this
    the stand-in developer is asked whether to stop the lead while being shown no work to lose.
    """
    return (tm or {}).get("task") or ""


# --- reading the task's own document ---------------------------------------------------------
#
# A reviewer put it plainly: the tool was handed a user-written RULES.md instead of the task
# description, which is not the baseline. They are right, and the SWE-Marathon example proves it.
# Its RULES.md is a hand-transcription of CONTRACTS.md, a document the task already ships: the
# ownership bullets restate a markdown table line for line. Asking for that twice is work the
# developer should not do, and it is work they can get wrong. I did: `nobody: start.sh, bin/`
# where CONTRACTS.md gives both to the lead, which produced a confident and completely wrong
# block and cost a whole arm.
#
# So the task document is read directly. No model is involved, which is the point - the extractor
# was removed because an LLM reading a brief needed provenance checks, quote checks and a
# consensus vote before anything it produced could be trusted. A markdown table needs none of
# that: it either parses or it does not, and the developer can see what was read.

TABLE_ROW = re.compile(r"^\s*\|(.+)\|\s*$")


def _tables_under(text, *heading_words):
    """Rows of every markdown table under a heading mentioning one of these words."""
    out, live = [], False
    for line in (text or "").splitlines():
        if line.startswith("#"):
            low = line.lower()
            live = any(w in low for w in heading_words)
            continue
        if not live:
            continue
        m = TABLE_ROW.match(line)
        if not m:
            continue
        cells = [c.strip() for c in m.group(1).split("|")]
        if len(cells) < 2 or set("".join(cells)) <= set("-: "):
            continue                                  # separator row, or a header underline
        out.append(cells)
    return out


def from_contract(text):
    """A task document -> the same shape parse() returns, for the parts that are unambiguous.

    Only the ownership table is read. Prose is left alone on purpose: "do NOT write start.sh"
    sitting inside a heading is exactly the kind of line an extractor would have to interpret,
    and interpreting it is the thing this version does not do.
    """
    ownership = {}
    for cells in _tables_under(text, "ownership", "owner", "files"):
        who = cells[0].strip().strip("`*_").lower()
        if who in ("owner", "who", "agent", ""):
            continue                                  # header row
        who = re.split(r"\s+/\s+", who)[0].strip()     # "lead / user" -> "lead", but
        #                                               "cluster/WS agent" is one name, not two
        paths = []
        for raw in cells[1].replace("|", ",").split(","):
            g = raw.strip().strip("`")
            if not g or g.lower().startswith("any "):  # "any supervisor/launcher" is prose
                continue
            paths.append(g)
        if who and paths:
            ownership.setdefault(who, []).extend(paths)
    return ownership
