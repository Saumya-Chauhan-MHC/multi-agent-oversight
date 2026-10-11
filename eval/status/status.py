#!/usr/bin/env python3
"""Where each of the two comparisons stands. Run it any time; it reads state, it changes nothing.

Comparison 1  is the surfacing right?   per decision, offline, scored against golden labels
Comparison 2  does the tool cost or help?  per run, live, scored by the real SWE-Marathon gates
"""
import json, os, subprocess, sys

H = os.path.expanduser
OLD = H("~/research/marathon_run")
A = H("~/research/arm_a_control")
B = H("~/research/arm_b_tool")
C = H("~/research/arm_c_simuser")
EV = H("~/research/offline_eval/marathon")       # the old, confounded recording
EVA = H("~/research/offline_eval/arma")          # the clean control recording
DEC = ("Write", "Edit", "MultiEdit", "Bash", "Agent", "Task")


def events(d):
    p = os.path.join(d, "oversight", "events.jsonl")
    if not os.path.exists(p):
        return []
    out = []
    for l in open(p):
        try:
            out.append(json.loads(l))
        except Exception:
            pass
    return out


def decisions(d):
    return sum(1 for e in events(d)
               if e.get("ov_event") == "pre_tool" and e.get("tool_name") in DEC)


def live(pat):
    return subprocess.run(["pgrep", "-f", pat], capture_output=True).returncode == 0


def lines(p):
    return sum(1 for _ in open(p)) if os.path.exists(p) else 0


def mark(done, running=False):
    return "RUNNING" if running else ("done   " if done else "NOT RUN")


def row(label, done, note="", running=False):
    print("  [%s]  %-44s %s" % (mark(done, running), label, note))


arm_b_live = live("claude -p")
replay_live = live("oversight.v3.replay")
grading_live = live("run_gates")

print("=" * 96)
print("COMPARISON 1   is the surfacing right?   per decision, offline, against golden labels")
print("=" * 96)
print()
print("  -- on the OLD recording (marathon_run: v2 hooks silent, but 5 preference lines injected) --")
row("recording exists", lines(os.path.join(EV, "trajectory.jsonl")) > 0,
    "%d decisions" % decisions(OLD))
row("golden labels, 6 axes", lines(os.path.join(EV, "golden.jsonl")) > 0,
    "%d rows" % lines(os.path.join(EV, "golden.jsonl")))
vers = sorted(f for f in os.listdir(EV) if f.startswith("results_v3") and f.endswith(".jsonl"))
row("tool replayed", bool(vers), "%d versions: %s" % (len(vers), " ".join(
    v.replace("results_", "").replace(".jsonl", "") for v in vers)))
row("scored, surfacing and detection", os.path.exists(os.path.join(EV, "scores_v38.json")))
row("scored, confidence bands", os.path.exists(os.path.join(EV, "scores_bands_v38.json")))
row("labelling rule checked as code", os.path.exists(os.path.join(EV, "derived_labels.json")),
    "70/73 band agreement, both positives derived")
conf = 0
gp = os.path.join(EV, "golden.jsonl")
if os.path.exists(gp):
    conf = sum(1 for l in open(gp) if json.loads(l).get("human_confirmed"))
row("adjudicated by a second person", conf > 0, "%d of %d rows confirmed" % (conf, lines(gp)))
print()
print("  -- on the CLEAN recording (arm_a_control: record-only hooks, nothing injected) --")
row("recording exists", decisions(A) > 0, "%d decisions" % decisions(A))
row("task model extracted (consensus over draws)",
    os.path.exists(os.path.join(EVA, "task_model_arma.json")))
agp = os.path.join(EVA, "golden.jsonl")
row("golden labels, 6 axes", lines(agp) > 0,
    "%d of %d rows" % (lines(agp), decisions(A)) if decisions(A) else "")
arp = os.path.join(EVA, "results_arma.jsonl")
row("tool replayed", lines(arp) > 0, "%d decisions" % lines(arp), running=replay_live)
row("scored, surfacing and detection", os.path.exists(os.path.join(EVA, "scores_arma.json")))
row("scored, confidence bands", os.path.exists(os.path.join(EVA, "scores_bands_arma.json")))
ao = os.path.join(EVA, "scores_outcome_arma.json")
note = ""
if os.path.exists(ao):
    o = json.load(open(ao))
    note = "outcome recall %s, precision %s, harm %d" % (
        o["outcome_recall"]["value"], o["outcome_precision"]["value"], o["harm"]["count"])
row("scored against the real grader failures", os.path.exists(ao),
    note or "the step the old recording could not support")
print()

print("=" * 96)
print("COMPARISON 2   does the tool cost or help?   per run, live, scored by the real gates")
print("=" * 96)
print()
for d, name in ((A, "control (no tool)"), (B, "treatment (v3, nobody to ask)"),
                (C, "treatment (v3 + simulated developer)")):
    nd = decisions(d)
    isb = d in (B, C) and arm_b_live and not os.path.exists(os.path.join(d, "grade", "report.json"))
    row("%s: run" % name, nd > 0 and not isb, "%d decisions, %d events" % (nd, len(events(d))),
        running=isb)
    rep = os.path.join(d, "grade", "report.json")
    note = ""
    if os.path.exists(rep):
        r = json.load(open(rep))
        own = r.get("own_suite") or {}
        note = "official %s/%s, own suite %s/%s, gates %s/%s" % (
            r.get("tests_passed"), r.get("tests_total"), own.get("passed"), own.get("total"),
            r.get("gates_passed"), r.get("gates_total"))
        if r.get("gates_not_runnable"):
            note += ", not runnable: " + ",".join(r["gates_not_runnable"])
    ans = [e for e in events(d) if e.get("ov_event") == "v3_user"]
    if ans:
        import collections as _c
        note = (note + "  " if note else "") + "developer answers: %s" % dict(
            _c.Counter(a.get("decision") for a in ans))
    row("%s: graded by the real gates" % name, os.path.exists(rep), note, running=grading_live)
row("side by side comparison", os.path.exists(os.path.join(EV, "arms.json")))
print()
print("  live processes:  arm B %s   replay %s   grading %s"
      % (arm_b_live, replay_live, grading_live))
