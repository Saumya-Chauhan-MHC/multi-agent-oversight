#!/usr/bin/env python3
"""Deterministic checks for everything except the model calls.

The judge is stubbed, so these run in a second and test the parts that must never be wrong:
the lists, the filter's two paths, the cache, the metric gate, grouping, ranking, the window,
the preempt exception and the precision floor.
"""
import json, os, shutil, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(HERE))))
from oversight.v3 import taskmodel as tmod, filter as filt, policy

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("%s %s%s" % ("PASS" if ok else "FAIL", name, ("  " + str(detail)) if detail else ""))


def ev(ts, agent, tool, **ti):
    return dict(ov_event="pre_tool", ov_ts=ts, agent_id=agent, tool_name=tool, tool_input=ti)


def bash_done(ts, agent, cmd, code=0):
    return dict(ov_event="post_tool", ov_ts=ts, agent_id=agent, tool_name="Bash",
                tool_input=dict(command=cmd), tool_response=dict(exit_code=code))


TM = dict(requirements=[dict(id="R1", text="api works", check="tests/test_api.py", status="untested"),
                        dict(id="R2", text="ids are stable", check="tests/test_store.py::ids",
                             status="untested")],
          preferences=[
              dict(id="P1-001", category="P1", rule="one subagent per surface, each owns its files",
                   source="decomposition", metrics=["time", "tokens"], files=[]),
              dict(id="P1-002", category="P1",
                   rule="ports and processes belong to whoever started them",
                   source="model", metrics=["time", "tokens"], files=[]),
              dict(id="P2-001", category="P2",
                   rule="the record format in store/schema.py is defined once; changes come back to me",
                   source="decomposition", metrics=["tests"], files=["store/schema.py"]),
              dict(id="P3-001", category="P3", rule="no agent reports done without running its tests",
                   source="decomposition", metrics=["tests"], files=[]),
              dict(id="P3-002", category="P3", rule="an agent may not modify the thing that judges it",
                   source="model", metrics=["tests"], files=[]),
          ], agents={}, decisions=[], state={})

proj = tempfile.mkdtemp(prefix="v3test_")
os.makedirs(os.path.join(proj, "oversight"), exist_ok=True)
tmod.save(proj, TM)

# ---------------------------------------------------------------- the three lists
check("graded file set comes from requirement checks",
      tmod.graded_files(TM) == {"tests/test_api.py", "tests/test_store.py"},
      tmod.graded_files(TM))

events = [ev(1000, "cluster", "Bash", command="python3 server/node.py 8000"),
          ev(1100, "api", "Bash", command="ls -la")]
check("registry records who started a port", tmod.registry(events) == {"port:8000": "cluster"},
      tmod.registry(events))

check("a kill command names the resource it reaches for",
      tmod.resources_touched("kill $(lsof -ti:8000)") == ["port:8000"])
check("a non-kill command names nothing", tmod.resources_touched("curl :8000/health") == [])

dep_events = [ev(1000, "store", "Write", file_path="store/schema.py"),
              ev(1200, "api", "Read", file_path="store/schema.py"),
              bash_done(1300, "api", "python3 -m pytest tests/api/ -q"),
              ev(1400, "store", "Write", file_path="store/schema.py")]
dep = tmod.dependency_map(dep_events)
check("dependency map: api depends on a file store owns",
      dep["depends_on"].get("api") == {"store/schema.py"}, dep["depends_on"])
check("stale claim: api's green run predates store's change",
      (tmod.stale_claim(dep, "api") or {}).get("by") == "store", tmod.stale_claim(dep, "api"))
check("not stale for the owner itself", tmod.stale_claim(dep, "store") is None)

# ---------------------------------------------------------------- filter, path B
f = filt.check(TM, events, "Write", dict(file_path="/x/tests/test_api.py"), "api")
check("B: writing a graded file is a hit", f and f["reason"] == "graded_file", f)

f = filt.check(TM, events, "Bash", dict(command="kill $(lsof -ti:8000)"), "irc")
check("B: killing another agent's port is a hit", f and f["reason"] == "resource_owned_elsewhere", f)

f = filt.check(TM, events, "Bash", dict(command="kill $(lsof -ti:8000)"), "cluster")
check("B: killing your own port is not a conflict hit",
      not (f and f["reason"] == "resource_owned_elsewhere"), f)

f = filt.check(TM, dep_events, "Write", dict(file_path="store/schema.py"), "cluster")
check("B: changing a declared interface others use is a hit",
      f and f["reason"] == "declared_interface" and "api" in f["dependents"], f)

# ---------------------------------------------------------------- filter, path A and misses
f = filt.check(TM, events, "Bash", dict(command="wc -l README.md && ls"), "api")
check("A: an unrelated command is a miss", f is None, f)

f = filt.check(TM, events, "Bash", dict(command="python3 -m pytest tests/ -q"), "api")
check("A: a command mentioning tests is a hit", f and f["path"] == "A", f)

# ---------------------------------------------------------------- the cache
sig = tmod.rules_signature(TM)
k1 = policy.cache_key("kill $(lsof -ti:8000)", sig)
check("same action + same rules = same key", k1 == policy.cache_key("kill $(lsof -ti:8000)", sig))
tm2 = json.loads(json.dumps(TM))
tm2["preferences"].append(dict(id="P1-003", category="P1", rule="irc uses 6667 only",
                               source="human", metrics=["time"], files=[]))
check("a new preference changes the key",
      k1 != policy.cache_key("kill $(lsof -ti:8000)", tmod.rules_signature(tm2)))
policy.cache_put(proj, k1, dict(verdict="fits", band="silent"))
check("a stored verdict comes back", (policy.cache_get(proj, k1) or {}).get("band") == "silent")

# ---------------------------------------------------------------- bands and the metric gate
check("departs at 0.9 with a metric holds",
      policy.band(dict(verdict="departs", confidence=0.9, metric="tests")) == "hold")
check("departs at 0.6 with a metric is a check",
      policy.band(dict(verdict="departs", confidence=0.6, metric="time")) == "check")
check("THE GATE: departs with no metric is silent",
      policy.band(dict(verdict="departs", confidence=0.95, metric=None)) == "silent")
check("a fit is silent even when nothing covers it",
      policy.band(dict(verdict="fits", confidence=0.9, covered=False, metric=None)) == "silent")
check("an unreachable judge is silent",
      policy.band(dict(verdict="fits", source="unavailable", confidence=0)) == "silent")

# ---------------------------------------------------------------- grouping and ranking
def flag(rid, prefs, metric, conf, trigger="word_overlap", **kw):
    return dict(rid=rid, prefs=prefs, metric=metric, confidence=conf, ts=policy.now(),
                trigger=trigger, action="...", agent="a", **kw)

policy._write(proj, "blocks.json", [])
policy.enqueue(proj, flag("r1", ["P1-002"], "time", 0.88))
policy.enqueue(proj, flag("r2", ["P1-002"], "time", 0.93))
blocks = policy._blocks(proj)
check("same preference -> one block with two members",
      len(blocks) == 1 and len(blocks[0]["members"]) == 2, [len(b["members"]) for b in blocks])

policy.enqueue(proj, flag("r3", ["P3-002"], "tests", 0.94))
blocks = policy._blocks(proj)
check("a different preference -> its own block", len(blocks) == 2, len(blocks))

policy._write(proj, "state.json", {})            # window open
top = policy.due(proj)
check("the tests-threatening block outranks the time one", top["label"] == "P3-002", top["label"])

# ---------------------------------------------------------------- landing drops a member
policy.mark_landed(proj, "r3")
check("a landed flag leaves the queue",
      all(m["rid"] != "r3" for b in policy._blocks(proj) for m in b["members"]))
check("and its empty block is gone too",
      all(b["label"] != "P3-002" for b in policy._blocks(proj) if b["status"] == "waiting"))

# ---------------------------------------------------------------- the quiet window
policy._write(proj, "state.json", dict(last_answer_ts=policy.now()))
check("nothing surfaces inside the window", policy.due(proj) is None)
check("window_open is false right after an answer", not policy.window_open(proj))
later = policy.now() + (policy.WINDOW_S + 1) * 1000
check("the window reopens after ten minutes", policy.window_open(proj, later))
check("and then the block surfaces", policy.due(proj, later) is not None)

# ---------------------------------------------------------------- the one preempt
policy._write(proj, "state.json", dict(last_answer_ts=policy.now()))
policy.enqueue(proj, flag("r9", ["P2-001"], "tests", 0.95, trigger="declared_interface",
                          dependents=["api", "irc"]))
check("a declared interface with two dependents breaks the window",
      (policy.due(proj) or {}).get("label") == "P2-001")

policy._write(proj, "blocks.json", [])
policy._write(proj, "state.json", dict(last_answer_ts=policy.now()))
policy.enqueue(proj, flag("r10", ["P2-001"], "tests", 0.95, trigger="declared_interface",
                          dependents=["api"]))
check("one dependent does NOT break the window", policy.due(proj) is None)

policy._write(proj, "blocks.json", [])
policy._write(proj, "state.json", dict(last_answer_ts=policy.now(), last_preempt_ts=policy.now()))
policy.enqueue(proj, flag("r11", ["P2-001"], "tests", 0.95, trigger="declared_interface",
                          dependents=["api", "irc"]))
check("at most one preempt per hour", policy.due(proj) is None)

# ---------------------------------------------------------------- answering
policy._write(proj, "blocks.json", [])
policy._write(proj, "state.json", {})
policy.enqueue(proj, flag("a1", ["P1-002"], "time", 0.9))
policy.enqueue(proj, flag("a2", ["P1-002"], "time", 0.9))
answered = policy.answer(proj, "P1-002", "no", "irc uses 6667 only")
check("one answer covers every member of the block", len(answered) == 2, len(answered))
check("the block closes when nothing is left",
      all(b["status"] == "answered" for b in policy._blocks(proj)))

policy._write(proj, "blocks.json", [])
policy.enqueue(proj, flag("b1", ["P1-001"], "time", 0.9))
policy.enqueue(proj, flag("b2", ["P1-001"], "time", 0.9))
policy.answer(proj, "P1-001", "accept", rids=["b1"])
left = [m["rid"] for b in policy._blocks(proj) for m in b["members"]]
check("a single member can be answered on its own", left == ["b2"], left)

# ---------------------------------------------------------------- the precision floor
p = os.path.join(policy.ctl(proj), "answers.jsonl")
open(p, "w").write("".join(json.dumps(dict(decision="accept")) + "\n" for _ in range(5)))
check("five waved-through holds turn holds into checks",
      policy.band(dict(verdict="departs", confidence=0.95, metric="tests"), proj) == "check")
open(p, "w").write("".join(json.dumps(dict(decision="no")) + "\n" for _ in range(5)))
check("and good precision restores holding",
      policy.band(dict(verdict="departs", confidence=0.95, metric="tests"), proj) == "hold")

shutil.rmtree(proj, ignore_errors=True)
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
