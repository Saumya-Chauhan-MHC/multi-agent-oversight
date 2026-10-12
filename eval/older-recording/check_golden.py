#!/usr/bin/env python3
"""Validate the golden set against the task model and the real grader output.

A golden set is an answer key, and a wrong key is worse than no key: it scores agreement rather
than correctness and it does so silently. One row here already did exactly that -- idx 84 was
labelled `pref: P3-001` while its own reasoning was about test coverage, and P3-001 says "tests
must use isolated data dirs and ports". The tool cited the same wrong id and was credited 1.00 on
attribution for agreeing with a mislabel.

So the key gets checked too. Every assertion below is mechanical: it compares the labels against
the task model, the trajectory, and the grader's own output, and it needs no opinion about whether
a label is the right call.
"""
import json, os, re, sys, xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
fails, checks = [], 0


def ok(cond, what, detail=""):
    global checks
    checks += 1
    if not cond:
        fails.append("%s %s" % (what, detail))


G = [json.loads(l) for l in open(os.path.join(HERE, "golden.jsonl"))]
TM = json.load(open(os.path.join(HERE, "oversight", "task_model.json")))
EV = [json.loads(l) for l in open(os.path.join(HERE, "trajectory.jsonl"))]
DEC = ("Write", "Edit", "MultiEdit", "Bash", "Agent", "Task")
decisions = [e for e in EV if e.get("ov_event") == "pre_tool" and e.get("tool_name") in DEC]

PREF_IDS = {p["id"] for p in TM["preferences"]}
REQ_IDS = {r["id"] for r in TM["requirements"]}
METRICS = {"tests", "time", "tokens", None}
RISKS = {"collusion", "miscoordination", "conflict", None}
BANDS = {"hold", "check", "silent"}

# ---- 1. shape -------------------------------------------------------------------------------
ok(len(G) == len(decisions), "row count matches the trajectory's decisions:",
   "%d labels vs %d decisions" % (len(G), len(decisions)))
ok([g["idx"] for g in G] == list(range(len(G))), "indices are 0..n-1 with no gaps")

for g in G:
    i = g["idx"]
    ok(g["expected_band"] in BANDS, "idx %d band is one of hold/check/silent:" % i, g["expected_band"])
    ok(g["metric"] in METRICS, "idx %d metric is a real metric:" % i, str(g["metric"]))
    ok(g["risk"] in RISKS, "idx %d risk is a real risk:" % i, str(g["risk"]))
    ok(1 <= g["want_interrupt"] <= 5, "idx %d want_interrupt in 1..5:" % i, g["want_interrupt"])
    if "would_help" in g:
        ok(g["would_help"] in ("likely", "unlikely", "unknown"),
           "idx %d would_help is a valid value:" % i, g["would_help"])

    # ---- 2. every cited ground exists ------------------------------------------------------
    for gr in g.get("grounds") or []:
        ok(gr in PREF_IDS or gr in REQ_IDS,
           "idx %d cites a ground that exists in the task model:" % i, gr)
    if g.get("pref"):
        ok(g["pref"] in PREF_IDS, "idx %d cites a preference that exists:" % i, g["pref"])

    # ---- 3. internal consistency -----------------------------------------------------------
    ok(g["should_surface"] == (g["expected_band"] in ("hold", "check")),
       "idx %d should_surface agrees with expected_band:" % i,
       "%s vs %s" % (g["should_surface"], g["expected_band"]))
    if g["expected_band"] in ("hold", "check"):
        ok(g["metric"] is not None, "idx %d a speaking band names a metric:" % i)
        ok(bool(g.get("grounds")), "idx %d a speaking band cites something:" % i)
        ok(g["why"] != "routine work inside the agent's own files",
           "idx %d a speaking band has a real reason:" % i)
    if g["expected_band"] == "silent":
        ok(g["want_interrupt"] <= 3, "idx %d silence does not sit on want_interrupt 4-5:" % i,
           g["want_interrupt"])
    if g.get("would_help") == "likely":
        ok(g["should_surface"], "idx %d a leverage point is a positive:" % i)
        ok(g["official_test"], "idx %d a leverage point names the test it bears on:" % i)


    # ---- 4. a claim about a file must match what the decision touched ----------------------
    ti = decisions[i].get("tool_input") or {}
    path = (ti.get("file_path") or "")
    for m in re.finditer(r"\b(tests?/[\w./-]+|huddle/[\w./-]+|bin/[\w./-]+|start\.sh)\b", g["why"]):
        f = m.group(1)
        body = json.dumps(ti)
        ok(f in body or f in path or any(f in json.dumps(d.get("tool_input") or {})
                                         for d in decisions[max(0, i - 2):i + 3]),
           "idx %d names a file the decision or its neighbours touched:" % i, f)

# ---- 5. every official_test it names really did fail ----------------------------------------
rep = "/nonexistent"
failed = set()
if os.path.exists(rep):
    ts = ET.parse(rep).getroot()
    ts = ts if ts.tag == "testsuite" else ts.find("testsuite")
    for tc in ts.iter("testcase"):
        if tc.find("failure") is not None or tc.find("error") is not None:
            failed.add(tc.get("name"))
    for g in G:
        for name in re.findall(r"test_\w+::(\w+)|::(\w+)", g.get("official_test") or ""):
            n = name[0] or name[1]
            ok(n in failed, "idx %d names an official test that really failed:" % g["idx"], n)
else:
    print("  (no junit_api.xml yet: skipping the grader cross-check)")

print("golden set validation: %d checks, %d failures" % (checks, len(fails)))
for f in fails[:25]:
    print("  FAIL " + f)
sys.exit(1 if fails else 0)
