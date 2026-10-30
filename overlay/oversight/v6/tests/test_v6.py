#!/usr/bin/env python3
"""v6: the two channels, the queue rules, and the preference model that moves."""
import os, sys, json, time, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))
from oversight.v6 import safety, surface, prefs
from oversight.v3 import taskmodel as tmod

OK = FAIL = 0


def check(name, cond):
    global OK, FAIL
    if cond:
        OK += 1
    else:
        FAIL += 1
        print("  FAIL:", name)


# ---- 1. a filter hit becomes the right kind of finding -------------------------------------
for risk, reason in (("collusion", "graded_file"), ("miscoordination", "declared_interface"),
                     ("conflict", "resource_owned_elsewhere")):
    f = safety.classify(dict(risk=risk, reason=reason, detail="x"))
    check("%s is a safety finding" % risk, f and f["kind"] == "safety" and f["risk"] == risk)
    check("%s cites a source" % risk, f["source"] and "arXiv" in f["source"])
    check("%s names the category it extends" % risk, f["category"] in ("P1", "P2", "P3"))
    check("%s asks one narrow question" % risk, f["ask"])

check("a word-overlap hit is not a safety finding",
      safety.classify(dict(risk=None, reason="word_overlap")) is None)

check("collusion extends P3", safety.RISKS["collusion"]["category"] == "P3")
check("miscoordination extends P2", safety.RISKS["miscoordination"]["category"] == "P2")
check("conflict extends P1", safety.RISKS["conflict"]["category"] == "P1")
check("conflict costs time and tokens, not tests",
      safety.RISKS["conflict"]["metric"] == "time+tokens")

# ---- 2. channels are separate --------------------------------------------------------------
p = tempfile.mkdtemp()
SAFE = dict(kind="safety", risk="collusion", reason="graded_file", detail="tests/test_a.py",
            category="P3", metric="tests", costs="c", source="s", extends="e", ask="q")
PREF = dict(kind="preference", reason="word_overlap", detail=["storage"], pid="H1",
            rule="one storage module", category="P1")

surface.enqueue(p, SAFE)
surface.enqueue(p, PREF)
check("safety and preference queue separately", surface.depths(p) == {"safety": 1, "preference": 1})
item = surface.next_to_show(p)
check("safety is shown first", item["channel"] == "safety")

# ---- 3. one at a time, and the quiet window holds the rest ---------------------------------
surface.mark_shown(p, "safety")
surface.pop(p, "safety", item["key"])
surface.enqueue(p, dict(SAFE, reason="weakened_check", detail="tests/test_b.py"))
nxt = surface.next_to_show(p)
check("a second safety flag waits out the quiet window",
      nxt is None or nxt["channel"] == "preference")
check("it is queued, not dropped", surface.depths(p)["safety"] == 1)

# ---- 4. same kind combines into one interruption -------------------------------------------
q = tempfile.mkdtemp()
surface.enqueue(q, SAFE)
r = surface.enqueue(q, dict(SAFE, detail="tests/test_c.py"))
check("the same kind combines", r["combined"] is True)
check("and stays one queue entry", surface.depths(q)["safety"] == 1)
n = surface.notice(surface.next_to_show(q))
check("both concrete requests are listed", "test_a.py" in n and "test_c.py" in n)
r2 = surface.enqueue(q, dict(SAFE, reason="disabled_check", detail="tests/test_d.py"))
check("a different reason does not combine", r2["combined"] is False)

# ---- 5. depth cap drops the oldest ----------------------------------------------------------
d = tempfile.mkdtemp()
for i in range(surface.DEPTH + 3):
    surface.enqueue(d, dict(SAFE, reason="r%d" % i, detail="f%d" % i))
check("the queue is capped", surface.depths(d)["safety"] == surface.DEPTH)
keys = [i["key"] for i in json.load(open(os.path.join(d, surface.DIR, "queue_safety.json")))]
check("the oldest went, not the newest", "risk:collusion:r0" not in keys
      and "risk:collusion:r%d" % (surface.DEPTH + 2) in keys)

# ---- 6. the one preemption ------------------------------------------------------------------
check("an interface about to move preempts the window",
      surface.preempts(dict(kind="safety", risk="miscoordination", reason="declared_interface")))
check("a stale done claim does not",
      not surface.preempts(dict(kind="safety", risk="miscoordination", reason="stale_claim")))
check("collusion does not",
      not surface.preempts(dict(kind="safety", risk="collusion", reason="graded_file")))

e = tempfile.mkdtemp()
surface.enqueue(e, dict(SAFE, risk="miscoordination", reason="declared_interface",
                        detail="app/store.py"))
surface.mark_shown(e, "safety")                       # window is open and should not stop this
check("and it is shown inside the window", surface.next_to_show(e) is not None)

# Regression: the scan used to look only at the head of the queue, so a moving interface sitting
# behind two older flags never preempted anything and the one exception silently did not exist.
b = tempfile.mkdtemp()
surface.enqueue(b, SAFE)
surface.enqueue(b, dict(SAFE, risk="conflict", reason="resource_owned_elsewhere", detail="port:1"))
surface.mark_shown(b, "safety")
check("an ordinary flag stays queued inside the window", surface.next_to_show(b) is None)
surface.enqueue(b, dict(SAFE, risk="miscoordination", reason="declared_interface",
                        detail="app/store.py"))
nb = surface.next_to_show(b)
check("a preempting flag is found even buried behind two others",
      nb is not None and nb["members"][0]["risk"] == "miscoordination")
check("and the ones it jumped are still queued", surface.depths(b)["safety"] == 3)

# ---- 7. the preference model moves, but only on a quotable answer ---------------------------
m = tempfile.mkdtemp()
tm = dict(requirements=[], preferences=[
    dict(id="H1", category="P1", rule="one storage module shared by every component",
         source="PRD", metrics=["tests"])], agents=[], decisions=[])
tmod.save(m, tm)

prefs._ask = lambda pref, decision, note: dict(verb="replace", rule="x", quote="never said this")
out = prefs.update_from_feedback(m, "H1", "reject", "one module per component is fine")
check("a revision the developer did not say is refused", out["applied"] is False
      and out["why"] == "unquoted")
check("and the preference is untouched",
      tmod.preferences(tmod.load(m))[0]["rule"].startswith("one storage module"))

prefs._ask = lambda pref, decision, note: dict(
    verb="replace", rule="one storage module per component",
    quote="one module per component is fine")
out = prefs.update_from_feedback(m, "H1", "reject", "one module per component is fine")
check("a quoted revision applies", out["applied"] is True and out["verb"] == "replace")
tm2 = tmod.load(m)
check("the rule changed", tmod.preferences(tm2)[0]["rule"] == "one storage module per component")
check("the source becomes human", tmod.preferences(tm2)[0]["source"] == "human")
h = prefs.history(tm2, "H1")
check("the original wording is kept", len(h) == 1 and h[0]["from"].startswith("one storage module s"))
check("and what moved it is kept", h[0]["quote"] == "one module per component is fine")
ch = prefs.changed(tm2)
check("the change is showable to the developer",
      len(ch) == 1 and ch[0]["original"] != ch[0]["now"] and ch[0]["moved"] == 1)

# Regression: asked to interpret "yes, that's right, it shouldn't touch that", the live judge
# returned `narrow` and carved out the very case that had just been upheld. Agreement is
# confirmation, so it is refused in code rather than argued for in the prompt.
prefs._ask = lambda pref, decision, note: dict(
    verb="narrow", rule="weakened", quote="yes, that is right")
before_rule = tmod.preferences(tmod.load(m))[0]["rule"]
out = prefs.update_from_feedback(m, "H1", "accept", "yes, that is right")
check("agreeing with a flag does not rewrite the preference", out["applied"] is False)
check("even when the judge tries to narrow it", out["verb"] == "keep")
check("and the rule is untouched",
      tmod.preferences(tmod.load(m))[0]["rule"] == before_rule)
check("an unknown preference id is refused",
      prefs.update_from_feedback(m, "NOPE", "accept", "x")["applied"] is False)

# ---- 7b. miscoordination is derived from the graph, not from a declaration ------------------
# Regression: v3 looked the file up in a `files` list on the P2 preferences, which only the
# extractor ever wrote. Once the deterministic builder replaced it the list was always empty and
# this detector silently never fired again.
ev = [
    dict(ov_event="pre_tool", tool_name="Write", agent_id="core", ov_ts=1,
         tool_input={"file_path": "app/store.py", "content": "def put(b, k): ..."}),
    dict(ov_event="pre_tool", tool_name="Read", agent_id="a", ov_ts=2,
         tool_input={"file_path": "app/store.py"}),
    dict(ov_event="pre_tool", tool_name="Read", agent_id="b", ov_ts=3,
         tool_input={"file_path": "app/store.py"}),
]
tm_plain = dict(requirements=[], preferences=[dict(id="P1", category="P2", rule="shared layer")],
                agents={}, decisions=[])
f = safety.check_action(tm_plain, ev, "Edit",
                        {"file_path": "app/store.py", "old_string": "a", "new_string": "b"}, "core")
check("a moving interface is caught with no declaration anywhere",
      f and f["risk"] == "miscoordination")
check("and it names who is already building on it",
      f and f["dependents"] == ["a", "b"])
check("and says it came from the graph", f and f.get("derived") == "dependency-graph")

d2 = tmod.dependency_map(ev)
check("one dependent is a handoff, not a shared contract",
      safety.interface_dependents(d2, "app/store.py", "core", minimum=3) is None)
check("the acting agent does not count as its own dependent",
      "core" not in (safety.interface_dependents(d2, "app/store.py", "core") or []))
check("defining a file for the first time is not a departure",
      safety.interface_dependents(tmod.dependency_map([]), "app/new.py", "core") is None)
check("reading an interface is not changing it",
      safety.check_action(tm_plain, ev, "Read", {"file_path": "app/store.py"}, "core") is None)

# ---- 8. the notice carries the SSOT's fields ------------------------------------------------
n = surface.notice(dict(channel="safety", key="k", members=[SAFE]))
for field in ("what happened", "rule", "evidence", "cost if kept", "question", "detector after"):
    check("safety notice shows %s" % field, field in n)
n = surface.notice(dict(channel="preference", key="k", members=[PREF]))
for field in ("action", "preference", "evidence", "your call"):
    check("preference notice shows %s" % field, field in n)

print("%d passed, %d failed" % (OK, FAIL))
sys.exit(1 if FAIL else 0)
