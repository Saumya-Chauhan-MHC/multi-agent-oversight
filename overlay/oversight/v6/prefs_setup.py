#!/usr/bin/env python3
"""Give the tool its preferences, one of two ways, before the agents start.

  set      the developer writes them. Nothing is extracted.
  extract  extract.py builds them from the request, the repo, the project docs, the issue
           discussion and, when there is one, the merged fix.

Either way the result is the same three preferences, written to oversight/task_model.json in the
shape the gate and the swe3 replay already read:

  P11  scope    how far the change may reach          (category P4)
  P12  shared   what to build on                       (category P2)
  P13  checks   which tests or commands show it works  (category P3)

`source` records where each one came from (user, or extracted:<source>), so a run can always say
whether a flag rests on something the developer said or something the tool inferred. Preferences
still move during the run through v6_feedback.py, whichever way they started.

  python3 oversight/v6/prefs_setup.py set prefs.json [--proj DIR]
  python3 oversight/v6/prefs_setup.py extract [--proj DIR] [--prompt FILE] [--discussion FILE]
                                              [--merged-fix FILE]

prefs.json for `set`:  {"scope": "...", "shared": "...", "checks": "..."}   (any of the three)
"""
import argparse, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from v3 import taskmodel as tmod

# key in prefs.json, extract.py's number, id, category, section
SLOTS = (("scope", "1", "P11", "P4", "Scope: how much to change"),
         ("shared", "2", "P12", "P2", "Shared: what to build on"),
         ("checks", "3", "P13", "P3", "Checks: how to check the work"))
FILE_RE = r"[\w/.-]+\.(?:py|txt|yml|yaml|toml|cfg|md|json|js|ts|go|sh)\b"
PROMPT_NAMES = ("PROMPT.md", "prompt.txt", "instruction.md", "TASK.md", "README.md")


def concrete(rule):
    """The check every extracted preference passed: a departure has to show up in an action, so
    the rule must name a file, function, command or test. A rule that names none is kept but
    reported, because neither the gate nor a labeller can check it."""
    return bool(re.search(FILE_RE, rule) or re.search(r"\w+\(\)|\b\w+-\w+\b|\b\w+_\w+\b|`[^`]+`|\b(?:make|pytest|npm|python3?)\b", rule))


def model(rules, sources):
    prefs = []
    for key, _, pid, cat, section in SLOTS:
        rule = (rules.get(key) or "").strip()
        if not rule:
            continue
        prefs.append(dict(id=pid, category=cat, rule=rule, quote=rule, when="always",
                          source=sources.get(key, "user"), priority="soft", serves=[],
                          metrics=["tests"], files=sorted(set(re.findall(FILE_RE, rule))),
                          section=section))
    checks = next((p for p in prefs if p["id"] == "P13"), None)
    graded = sorted({os.path.dirname(f) for f in (checks or {}).get("files", []) if "test" in f})
    return dict(source="prefs_setup", requirements=[], agents={}, decisions=[], state={},
                graded_dirs=graded, preferences=prefs)


def write(proj, tm):
    tmod.save(proj, tm)
    out = tmod.path(proj)
    for p in tm["preferences"]:
        warn = "" if concrete(p["rule"]) else "   (names no file, function or command: hard to check)"
        print("%s  %-22s %s%s" % (p["id"], p["source"], p["rule"], warn))
    print("-> %s" % out)
    return out


def do_set(a):
    rules = json.load(open(a.file))
    unknown = [k for k in rules if k not in [s[0] for s in SLOTS]]
    if unknown:
        sys.exit("unknown keys %s; use scope, shared, checks" % unknown)
    return write(a.proj, model(rules, {k: "user" for k in rules}))


def _read(path):
    return open(path, errors="ignore").read() if path else ""


def do_extract(a):
    from v6 import extract
    prompt = a.prompt or next((os.path.join(a.proj, n) for n in PROMPT_NAMES
                               if os.path.exists(os.path.join(a.proj, n))), None)
    if not prompt:
        sys.exit("no request found; pass --prompt FILE")
    out = os.path.join(a.proj, "oversight", "extract")
    os.makedirs(out, exist_ok=True)
    t = dict(task=os.path.basename(os.path.abspath(a.proj)), ws=os.path.abspath(a.proj),
             prompt=_read(prompt), hints=_read(a.discussion), merged_fix=_read(a.merged_fix))
    res = extract.run(t, out)
    json.dump(extract.LOG, open(os.path.join(out, "check_log.json"), "w"), indent=1)
    if res.get("crashed"):
        sys.exit("extraction crashed; see %s/check_log.json" % out)
    by = {}
    for f in res["final"]:
        by.setdefault(f["pref"], f)
    rules = {k: by[n]["rule"] for k, n, *_ in SLOTS if n in by}
    sources = {k: "extracted:" + by[n]["source"] for k, n, *_ in SLOTS if n in by}
    tm = model(rules, sources)
    for p in tm["preferences"]:
        n = next(s[1] for s in SLOTS if s[2] == p["id"])
        if by[n]["source"] == "default":
            p["confirm"] = True                    # nothing answered it: ask the developer
    return write(a.proj, tm)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="mode", required=True)
    s = sub.add_parser("set", help="use the developer's own preferences")
    s.add_argument("file")
    e = sub.add_parser("extract", help="extract them from the request and the repo")
    e.add_argument("--prompt")
    e.add_argument("--discussion", help="issue thread or other discussion, as text")
    e.add_argument("--merged-fix", help="a reference patch, when the task has one")
    for p in (s, e):
        p.add_argument("--proj", default=os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    a = ap.parse_args()
    return do_set(a) if a.mode == "set" else do_extract(a)


if __name__ == "__main__":
    main()
