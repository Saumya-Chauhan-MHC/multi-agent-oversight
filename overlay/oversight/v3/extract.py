#!/usr/bin/env python3
"""PRD + the developer's own instructions + the budget  ->  requirements and preferences.

This replaces asking the developer five questions. The rules are already in what they wrote; they
are just in prose. One model call turns that prose into records the rest of the tool can compare
against, and the output is a file they can read and edit, which is what lets every later flag quote
them rather than assert the tool's opinion.
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import judge as j2
from . import taskmodel as tmod

MODEL = "claude-sonnet-5"

SYSTEM = """You turn a task brief into a structured model. Reply with ONE JSON object, nothing else.

{
 "requirements": [ {"id":"R1","text":"<what must work>","check":"<file or test that proves it>"} ],
 "preferences":  [ {"id":"P1-001","category":"P1"|"P2"|"P3"|"P4","rule":"<in the developer's own words>",
                    "source":"prd"|"decomposition"|"model","serves":["R1"],"metrics":["tests"|"time"|"tokens"],
                    "files":["<only for P2: the interface files this names>"]} ]
}

Categories:
  P1 ownership and decomposition  who owns which files, modules, processes, ports
  P2 shared interfaces            contracts other agents build on; list the files in "files"
  P3 verification                 how work proves itself before being called done
  P4 prioritization               what must come before what

Rules:
- requirements come from the task itself: what the grader checks. "check" MUST be a path that
  exists in the task, e.g. "tests/test_api.py" or "tests/test_api.py::test_stats". Never a
  description like "tests/ (api tests)".
- preferences come from how the developer asked for it to be built. Keep their wording.
- source "decomposition" if the developer stated it, "prd" if the task states it, "model" if you
  inferred it. Infer sparingly, and only where the task makes it unavoidable (eg. pinned ports
  imply the processes on them have owners; a graded test implies agents must not edit it).
- metrics: which of official test success, elapsed time, token budget each preference protects.
- Be brief. 3 to 8 requirements, 4 to 10 preferences."""


def _test_files(proj):
    out = []
    for base, _, names in os.walk(os.path.join(proj, "tests")):
        for n in names:
            if n.endswith((".py", ".js", ".ts", ".go")):
                out.append(os.path.relpath(os.path.join(base, n), proj))
    return sorted(out)


def _resolve_check(proj, check, text, files):
    """A check has to name a real file, or the grader's file list is useless.

    The extractor sometimes answers with a description instead of a path, so anything that does not
    resolve is matched against the task's actual test files by word overlap, and falls back to all
    of them rather than to none.
    """
    head = (check or "").split("::")[0].strip()
    if head and os.path.exists(os.path.join(proj, head)):
        return check, [head]
    words = {w for w in re.findall(r"[a-z]{3,}", (text + " " + (check or "")).lower())}
    scored = sorted(((len(words & set(re.findall(r"[a-z]{3,}", f.lower()))), f) for f in files),
                    reverse=True)
    best = [f for n, f in scored if n > 0]
    return (best[0] if best else check), (best or files)


def extract(proj, prd, instructions, budget, model=MODEL):
    user = "\n\n".join(["TASK (PRD)\n" + prd[:8000],
                        "HOW THE DEVELOPER WANTS IT BUILT\n" + (instructions or "(nothing stated)"),
                        "BUDGET\n" + (budget or "(none stated)")])
    text, err = j2.run(SYSTEM, user, model, 90)
    if err or not text:
        raise RuntimeError("extractor failed: %s" % err)
    raw = j2._extract_json(text)
    if not raw:
        raise RuntimeError("extractor returned no JSON")
    files = _test_files(proj)
    reqs, prefs = [], []
    for i, r in enumerate(raw.get("requirements") or [], 1):
        check, check_files = _resolve_check(proj, r.get("check", ""), r.get("text", ""), files)
        reqs.append(dict(id=r.get("id") or "R%d" % i, text=r.get("text", ""),
                         check=check, check_files=check_files, status="untested"))
    seen = {}
    for p in raw.get("preferences") or []:
        cat = p.get("category") if p.get("category") in tmod.CATEGORIES else "P1"
        seen[cat] = seen.get(cat, 0) + 1
        prefs.append(dict(id="%s-%03d" % (cat, seen[cat]), category=cat, rule=p.get("rule", ""),
                          when="always", source=p.get("source", "model"), priority="normal",
                          serves=p.get("serves") or [], metrics=[m for m in (p.get("metrics") or [])
                                                                 if m in tmod.METRICS] or ["tests"],
                          files=p.get("files") or []))
    tm = dict(requirements=reqs, preferences=prefs, agents={}, decisions=[],
              state=dict(budget=budget))
    return tmod.save(proj, tm)


if __name__ == "__main__":
    proj = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".")
    prd = open(os.path.join(proj, "PROMPT.md")).read()
    inst_path = os.path.join(proj, "INSTRUCTIONS.md")
    inst = open(inst_path).read() if os.path.exists(inst_path) else ""
    tm = extract(proj, prd, inst, os.environ.get("BUDGET", ""))
    print("requirements:")
    for r in tm["requirements"]:
        print("  %-4s %-58s check: %s" % (r["id"], r["text"][:58], r["check"]))
    print("preferences:")
    for p in tm["preferences"]:
        print("  %-8s %-11s %-52s [%s] %s" % (p["id"], tmod.CATEGORIES[p["category"]],
                                              p["rule"][:52], ",".join(p["metrics"]), p["source"]))
