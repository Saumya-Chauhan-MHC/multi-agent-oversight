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
def dependency_map(events):
    """Per agent: files it wrote (owns), files it read but does not own, and its last green run."""
    wrote, read, last_pass, last_global = {}, {}, {}, {}
    for e in events:
        who = e.get("agent_id") or "orchestrator"
        ts = e.get("ov_ts", 0)
        name, ti = e.get("tool_name"), (e.get("tool_input") or {})
        if e.get("ov_event") == "pre_tool" and name in ("Write", "Edit", "MultiEdit"):
            wrote.setdefault(who, {})[ti.get("file_path", "")] = ts
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
    deps = {}
    for who, files in read.items():
        mine = owned.get(who, set())
        deps[who] = {f for f in files if f and f not in mine}
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


def interface_dependents(tm, dep, target):
    """Agents that have read or written a declared interface file, other than the one acting."""
    declared = set()
    for p in preferences(tm):
        if p["category"] == "P2":
            declared |= set(p.get("files") or [])
    if target not in declared:
        return None
    users = set()
    for who, files in dep["depends_on"].items():
        if target in files:
            users.add(who)
    for who, files in dep["wrote"].items():
        if target in files:
            users.add(who)
    return users
