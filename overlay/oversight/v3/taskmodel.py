#!/usr/bin/env python3
"""The task model: what must work, how this developer wants it done, and who holds what.

One file per run, oversight/task_model.json, written by the extractor and amended by the human.
Two record kinds, deliberately separate:

  requirement  what must work, with the check that proves it   -> not negotiable
  preference   how this developer wants it met                 -> negotiable, and it evolves

Everything the tool later says quotes a preference, which is why a flag reads "you said X, this
does Y" instead of being the tool's own opinion.

The three lists live here too. One is fixed at extraction (which files the grader runs); the other
two are rebuilt from the event log on demand, because who owns a port and who depends on whose
files are both facts about how the run has gone so far, not about the task.
"""
import json, os, re, time

CATEGORIES = {"P1": "ownership", "P2": "interfaces", "P3": "verification", "P4": "prioritization"}
METRICS = ("tests", "time", "tokens")
METRIC_RANK = {"tests": 0, "time": 1, "tokens": 2}          # what the queue sorts on


def path(proj):
    return os.path.join(proj, "oversight", "task_model.json")


def load(proj):
    try:
        return json.load(open(path(proj)))
    except Exception:
        return dict(requirements=[], preferences=[], agents={}, decisions=[], state={})


def save(proj, tm):
    os.makedirs(os.path.dirname(path(proj)), exist_ok=True)
    json.dump(tm, open(path(proj), "w"), indent=1)
    return tm


def preferences(tm):
    return [p for p in tm.get("preferences", []) if p.get("status") != "retired"]


def requirement(tm, rid):
    return next((r for r in tm.get("requirements", []) if r["id"] == rid), None)


def add_preference(proj, rule, category="P1", source="human", serves=None, metrics=None, rid=None):
    """A human steer becomes a preference. Its id keeps the category prefix so grouping still works."""
    tm = load(proj)
    n = sum(1 for p in tm["preferences"] if p["id"].startswith(category)) + 1
    pref = dict(id="%s-%03d" % (category, n), category=category, rule=rule, when="always",
                source=source, priority="normal", serves=serves or [],
                metrics=metrics or ["tests"], added_ts=int(time.time() * 1000), from_rid=rid)
    tm["preferences"].append(pref)
    save(proj, tm)
    return pref


def rules_signature(tm):
    """What the cache keys against: change any rule and every cached verdict stops being reachable."""
    return "\n".join("%s: %s" % (p["id"], p["rule"]) for p in preferences(tm))


# ---------------------------------------------------------------- list 1: the grader's files
def graded_files(tm):
    """Fixed at extraction. A check like "tests/test_api.py::seq" still protects the file."""
    out = set()
    for r in tm.get("requirements", []):
        for f in (r.get("check_files") or []):
            out.add(f)
        check = (r.get("check") or "").strip()
        if check and "/" in check:
            out.add(check.split("::")[0])
    return {f for f in out if f.endswith((".py", ".js", ".ts", ".go"))}


def graded_dirs(tm):
    """The directories the graded files live in, plus any test directory a preference names.

    Without this the graded set is whatever test files happened to exist when the extractor ran,
    which on a greenfield task is nothing: the agent writes its first test an hour in, and a check
    authored so it cannot fail is invisible because the file it is in was not on a list built
    before the file existed. The verifier runs directories, not the particular files we guessed, so
    a directory is the honest unit. Found by the live arm of the offline eval.
    """
    out = set()
    for f in graded_files(tm):
        d = os.path.dirname(f)
        if d:
            out.add(d.rstrip("/") + "/")
    for p in preferences(tm):
        for m in re.findall(r"\b((?:[\w.-]+/)*tests?(?:/[\w.-]+)*)/?\b", p.get("rule") or ""):
            if m and not m.endswith((".py", ".js", ".ts", ".go")):
                out.add(m.rstrip("/") + "/")
    return out


# A requirement names behaviours. Its declared check is supposed to exercise them. The terms worth
# checking for are the ones the brief itself treats as API surface: things in backticks, route
# fragments, and the status codes a behaviour is defined by. Prose words are not evidence of
# anything, so they are not used.
TERM_RE = re.compile(r"`([^`]{3,40})`|(/api/[\w{}/]+)|\b([a-z][a-z0-9]{3,}_[a-z0-9_]{2,})\b")
STATUS_RE = re.compile(r"\b(40[0-9]|41[0-9]|42[0-9]|20[0-9]|30[0-9])\b")
TERM_STOP = {"workspace_id", "channel_id", "user_id", "created_at", "message_id", "parent_id",
             "display_name", "node_id", "is_private", "is_dm", "is_archived", "owner_id"}


METHOD_RE = re.compile(r"^(?:get|post|put|patch|delete)\s+", re.I)
ENVELOPE_RE = re.compile(r"^(\d{3})\s*\{(.*)\}$")
BRACED_RE = re.compile(r"^\{(.+)\}$")


def _terms(text):
    """Checkable atoms, normalised so a test that exercises a route actually matches it.

    The first version compared literal strings and reported `post /api/auth/register` missing from
    a file that calls `call("POST", "/api/auth/register", ...)`. A route is matched by its path, a
    response envelope by its status code and its field names separately, because that is how a
    test spells them.
    """
    out = set()
    for m in TERM_RE.finditer(text or ""):
        t = (m.group(1) or m.group(2) or m.group(3) or "").strip()
        t = t.split("(")[0].strip().lower()
        if not t or t.startswith("#"):
            continue
        env = ENVELOPE_RE.match(t)
        if env:
            out.add(env.group(1))
            for f in env.group(2).split(","):
                f = f.strip().strip("?").strip()
                if 3 <= len(f) <= 30:
                    out.add(f)
            continue
        br = BRACED_RE.match(t)
        if br:
            # a body or envelope shape. A test spells its fields, never the brace notation, so the
            # fields are the checkable atoms and the notation itself is not.
            for f in br.group(1).split(","):
                f = f.split(":")[0].strip().strip("?").strip("`").strip()
                if 3 <= len(f) <= 30:
                    out.add(f)
            continue
        t = METHOD_RE.sub("", t).strip()
        if t.startswith("/api/"):
            out.add(t.rstrip("/"))
            continue
        t = t.strip("/")
        if 3 <= len(t) <= 40:
            out.add(t)
    return out


def requirement_terms(tm, req, prd=""):
    """The checkable things this requirement is about, taken from the requirement ALONE.

    `prd` is accepted and ignored. The first version of this reached into the whole brief for any
    identifier that looked loosely related to the requirement's wording, and the result was
    useless: a cluster-events requirement came back wanting the SPA's `channel-add-member-form`
    test ids, and every test file in the run looked uncovered. Scoping terms to the requirement
    plus its own quoted spec is the only version that says anything.

    Which means this lookup is only as good as `spec_quote`. A requirement whose text is a
    one-line prose summary -- "Workspaces/channels CRUD, roles, membership semantics function per
    contract" -- yields no checkable term at all, and `uncovered` correctly says nothing rather
    than guessing. The fix for that is upstream, in what the extractor keeps.
    """
    return {t for t in (_terms(req.get("text", "")) | _terms(req.get("spec_quote", "")))
            if t not in TERM_STOP}


def uncovered(tm, target, body, prd="", floor=2):
    """Which requirements declare this file as their check, and what they name that it never does.

    This is the question the eval found missing. On the clean recording the one moment that carried
    leverage was an agent writing the 33KB suite that certifies its own component, having tested
    what it built rather than what was asked: no admin-to-admin role transition, no mention
    expansion, and over-length rejection at its own chosen boundary instead of the brief's. Four of
    the six official test failures were behaviours that file does not exercise. Every existing
    verification trigger looked at the file's *shape* -- is a check disabled, is one weakened -- and
    none of them asked whether the check covers the requirement it is the check for.
    """
    lo = (body or "").lower()

    def absent(term):
        """A route counts as covered if its literal path appears, or if its distinctive segments
        do -- a test may build the path from pieces."""
        if term in lo:
            return False
        if term.startswith("/api/"):
            segs = [x for x in term.split("/") if x and not x.startswith("{") and x != "api"]
            return not (segs and all(sg in lo for sg in segs))
        return True

    out = []
    for r in tm.get("requirements", []):
        checks = list(r.get("check_files") or []) + [(r.get("check") or "").split("::")[0]]
        if not any(c and (same_file(target, c) or target.endswith(c)
                          or os.path.dirname(c) and os.path.dirname(c) in target)
                   for c in checks):
            continue
        terms = requirement_terms(tm, r, prd)
        if len(terms) < floor:
            continue          # nothing concrete enough to be absent; say nothing
        missing = sorted(t for t in terms if t and absent(t))
        if missing:
            out.append(dict(req=r.get("id"), text=r.get("text", "")[:160],
                            missing=missing[:8], of=len(terms)))
    return out


def declaring_requirements(tm, target):
    """The requirements that declare this file as their check, with the brief's own words.

    This exists because of what the provenance check found. The rule the collusion finding kept
    citing -- "each component agent owns and must pass its own test directory before considering
    its piece done" -- is not in the developer's contracts file. Five extraction draws with quote
    verification on produced it zero times; the ownership table says an agent OWNS tests/api/**,
    and nothing anywhere says it must PASS them. The extractor had been inventing the rule and
    labelling it as the developer's own words.

    The defect it was used to flag is real: a check that cannot execute, in a file the grader runs.
    What was wrong was the grounds. A requirement needs no invented rule -- the brief says what
    must work and names the file that proves it, so a declared check that cannot run defeats the
    requirement directly, and the evidence shown to the developer is the brief's own sentence
    rather than one the tool wrote for them.
    """
    out = []
    t = target if target.startswith("/") else "/" + target
    for r in tm.get("requirements", []):
        checks = [c for c in (list(r.get("check_files") or [])
                              + [(r.get("check") or "").split("::")[0]]) if c]
        if any(same_file(target, c) or target.endswith(c) for c in checks):
            out.append(r)
            continue
        # A directory match too, for consistency with is_graded(). Without it a file sitting in a
        # graded directory was graded but had no declaring requirement, so the requirement-grounded
        # path could not reach it: the extractor's guessed check was tests/api/test_api.py and the
        # agent wrote tests/api/test_workspaces.py. The verifier runs directories, so a directory
        # is the unit on both sides or neither.
        dirs = {os.path.dirname(c).strip("/") for c in checks if os.path.dirname(c)}
        if any(("/" + d + "/") in t for d in dirs if d):
            out.append(r)
    return out


def is_graded(tm, target):
    """A file is graded if it is one of the checks, or sits in a directory the checks live in."""
    if not target:
        return False
    if any(same_file(target, g) or target.endswith(g) for g in graded_files(tm)):
        return True
    t = target if target.startswith("/") else "/" + target
    return any(("/" + d.strip("/") + "/") in t for d in graded_dirs(tm))


# ---------------------------------------------------------------- list 2: who started what
PORT_RE = re.compile(r"(?::|\bport[= ])(\d{2,5})\b")
BARE_PORT_RE = re.compile(r"\b(\d{4,5})\b")      # `node.py 8000` names a port without a colon
START_RE = re.compile(r"\b(python3?|node|npm|uvicorn|flask|gunicorn|http\.server)\b")
KILL_RE = re.compile(r"\b(kill|pkill|killall|fuser)\b")


def registry(events):
    """{resource -> owner}. A command that binds a port claims it for the agent that ran it."""
    owners = {}
    for e in events:
        if e.get("ov_event") != "pre_tool" or e.get("tool_name") != "Bash":
            continue
        cmd = ((e.get("tool_input") or {}).get("command") or "")
        if KILL_RE.search(cmd) or not START_RE.search(cmd):
            continue
        found = PORT_RE.findall(cmd) or [n for n in BARE_PORT_RE.findall(cmd)
                                         if 1024 <= int(n) <= 65535]
        for port in found:
            owners.setdefault("port:" + port, e.get("agent_id") or "orchestrator")
    return owners


def resources_touched(command):
    """What a kill-style command is reaching for, as registry keys."""
    if not KILL_RE.search(command or ""):
        return []
    found = PORT_RE.findall(command) or [n for n in BARE_PORT_RE.findall(command)
                                         if 1024 <= int(n) <= 65535]
    return ["port:" + p for p in found]


# ---------------------------------------------------------------- list 3: who depends on whom
IMPORT_RE = re.compile(r"(?:from|import|require)\s*\(?\s*['\"]?([\w./]+)")


def _imported_paths(text, known):
    """Project files referenced by an import inside written code.

    An agent that writes `from huddle.web.http import Request` depends on huddle/web/http.py
    without ever having opened it, so read-tracking alone misses the edge that matters most:
    the one into a declared interface.
    """
    if not text:
        return set()
    hits = set()
    mods = set(IMPORT_RE.findall(str(text)[:20000]))
    for mod in mods:
        as_path = mod.replace(".", "/").strip("/")
        if not as_path:
            continue
        for f in known:
            stem = (f[:-3] if f.endswith(".py") else f).replace("\\", "/")
            if stem.endswith(as_path) or stem.endswith(as_path + "/__init__"):
                hits.add(f)
    return hits


def dependency_map(events):
    """Per agent: files it wrote (owns), files it read but does not own, and its last green run."""
    wrote, read, last_pass, last_global, imports = {}, {}, {}, {}, {}
    for e in events:
        who = e.get("agent_id") or "orchestrator"
        ts = e.get("ov_ts", 0)
        name, ti = e.get("tool_name"), (e.get("tool_input") or {})
        if e.get("ov_event") == "pre_tool" and name in ("Write", "Edit", "MultiEdit"):
            wrote.setdefault(who, {})[ti.get("file_path", "")] = ts
            body = ti.get("content") or ti.get("new_string") or ""
            imports.setdefault(who, {})[ts] = body
        elif e.get("ov_event") == "pre_tool" and name == "Read":
            read.setdefault(who, {})[ti.get("file_path", "")] = ts
        elif e.get("ov_event") == "post_tool" and name == "Bash":
            cmd = ti.get("command", "")
            ok = str((e.get("tool_response") or {}).get("exit_code", 0)) in ("0", "None")
            if ok and re.search(r"\b(pytest|unittest|npm test|go test|python3? -m pytest)\b", cmd):
                last_pass[who] = ts
                # a check that is not scoped to one agent's own directory counts as global
                if not re.search(r"\b(tests?/[a-z_]+/|-k )\b", cmd):
                    last_global["*"] = max(last_global.get("*", 0), ts)
    owned = {w: set(f for f in files) for w, files in wrote.items()}
    known = {f for files in wrote.values() for f in files if f}
    deps = {}
    for who in set(list(read) + list(imports)):
        mine = owned.get(who, set())
        edges = {f for f in read.get(who, {}) if f and f not in mine}
        for body in (imports.get(who) or {}).values():
            edges |= {f for f in _imported_paths(body, known) if f not in mine}
        deps[who] = edges
    return dict(wrote=wrote, owns=owned, depends_on=deps,
                last_pass=last_pass, last_global=last_global.get("*", 0))


def stale_claim(dep, who):
    """True when this agent's green run predates someone else's change to what it depends on."""
    mine = dep["last_pass"].get(who, 0)
    if not mine:
        return None
    for f in dep["depends_on"].get(who, ()):
        for other, files in dep["wrote"].items():
            if other != who and files.get(f, 0) > mine:
                if dep["last_global"] <= files[f]:
                    return dict(file=f, by=other, at=files[f], my_last_pass=mine)
    return None


def same_file(a, b):
    """Two paths naming the same file.

    Hooks report an absolute path, a preference names a repo-relative one, and a trajectory
    recorded on another machine carries that machine's prefix. Comparing them exactly meant a
    declared interface was never recognised as one.
    """
    if not a or not b:
        return False
    a, b = str(a).replace("\\", "/"), str(b).replace("\\", "/")
    return a == b or a.endswith("/" + b) or b.endswith("/" + a)


def interface_dependents(tm, dep, target):
    """Agents that have read or written a declared interface file, other than the one acting."""
    declared = set()
    for p in preferences(tm):
        if p["category"] == "P2":
            declared |= set(p.get("files") or [])
    if not any(same_file(target, d) for d in declared):
        return None
    users = set()
    for src in ("depends_on", "wrote"):
        for who, files in (dep.get(src) or {}).items():
            if any(same_file(target, f) for f in files):
                users.add(who)
    return users
