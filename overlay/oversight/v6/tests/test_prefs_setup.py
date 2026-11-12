#!/usr/bin/env python3
"""prefs_setup.py `set`: the developer's own preferences become the task model the gate reads.
`extract` calls the LLM and the repo search, so it is checked by running it, not here."""
import json, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
V6 = os.path.dirname(HERE)
sys.path.insert(0, os.path.dirname(V6))
from v6 import prefs_setup

ok = bad = 0


def check(name, cond):
    global ok, bad
    ok, bad = ok + bool(cond), bad + (not cond)
    print(("  ok:   " if cond else "  FAIL: ") + name)


d = tempfile.mkdtemp()
f = os.path.join(d, "prefs.json")
json.dump(dict(scope="Change only trim_docstring in django/contrib/admindocs/utils.py.",
               shared="We should probably just switch to inspect.cleandoc.",
               checks="Check with test_trim_docstring in tests/admin_docs/test_utils.py."), open(f, "w"))
r = subprocess.run([sys.executable, os.path.join(V6, "prefs_setup.py"), "set", f, "--proj", d],
                   capture_output=True, text=True)
check("set exits cleanly", r.returncode == 0)
tm = json.load(open(os.path.join(d, "oversight", "task_model.json")))
ids = [(p["id"], p["category"]) for p in tm["preferences"]]
check("three preferences, in the replay's ids and categories",
      ids == [("P11", "P4"), ("P12", "P2"), ("P13", "P3")])
check("each is marked as the developer's", all(p["source"] == "user" for p in tm["preferences"]))
check("files named in a rule are recorded", tm["preferences"][0]["files"] == ["django/contrib/admindocs/utils.py"])
check("the test folder named by the checks preference is guarded", tm["graded_dirs"] == ["tests/admin_docs"])

check("a rule naming a file is concrete", prefs_setup.concrete("Change only requirements-docs.txt."))
check("a rule naming a package is concrete", prefs_setup.concrete("Keep mkdocs-material; update the pins."))
check("a vague rule is not", not prefs_setup.concrete("Keep it clean."))

json.dump(dict(scope="x", style="y"), open(f, "w"))
r = subprocess.run([sys.executable, os.path.join(V6, "prefs_setup.py"), "set", f, "--proj", d],
                   capture_output=True, text=True)
check("an unknown key is refused", r.returncode != 0 and "unknown keys" in r.stderr)

print("%d passed, %d failed" % (ok, bad))
sys.exit(1 if bad else 0)
