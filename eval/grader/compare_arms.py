#!/usr/bin/env python3
"""Compare two arms of the same SWE-Marathon task: one with the oversight tool, one without.

The control arm runs plain Claude Code with recording-only hooks. Recording-only means the hooks
append to events.jsonl and return nothing: no judge, no preference text injected into the agent's
context, no PreToolUse decision. The agent is never told anything and never waits on anything, so
its behaviour is the behaviour it would have had with no tool installed, and we still get the
event stream the golden set is annotated against. That last part is why the control arm is not
literally a bare `claude -p`: an unobserved run cannot be labelled.

What this prints, and why each line is here:

  decisions / tool calls     the denominator for every surfacing rate
  spawns                     whether the task produced fan-out at all
  wall clock                 the time metric, and the tool's own overhead inside it
  judge calls, shown         the tool's volume; 0 shown in the control arm by construction
  gates passed, tests passed the task-success metric, from the real verifier's pytest gates
  official reward            the verifier's own binary: all five gates, start.sh present, anti-cheat

A difference in gates between the arms is not attributable to the tool on one trial. Two runs of
one task differ for many reasons. What a single pair can show is whether the tool cost anything
obvious (time, a broken run) and whether the decisions it surfaced were about things that later
turned out to matter in the gates.
"""
import argparse, json, os, collections

TOOLS = ("Write", "Edit", "MultiEdit", "Bash", "Agent", "Task")


def load(d):
    p = os.path.join(d, "oversight", "events.jsonl")
    return [json.loads(l) for l in open(p)] if os.path.exists(p) else []


def arm(d, label):
    E = load(d)
    pre = [e for e in E if e.get("ov_event") == "pre_tool"]
    dec = [e for e in pre if e.get("tool_name") in TOOLS]
    ts = [e.get("ov_ts") for e in E if e.get("ov_ts")]
    judge = [e for e in E if e.get("ov_event") in ("judgement", "v3_judgement")]
    shown = [j for j in judge if j.get("shown")]
    bands = collections.Counter(j.get("band") for j in judge)
    files = {e.get("tool_input", {}).get("file_path") for e in dec
             if e.get("tool_name") in ("Write", "Edit", "MultiEdit")}
    files.discard(None)
    rep_path = os.path.join(d, "grade", "report.json")
    rep = json.load(open(rep_path)) if os.path.exists(rep_path) else {}
    return dict(label=label, dir=d, events=len(E), decisions=len(dec),
                tool_calls=len(pre), spawns=sum(1 for e in E if e.get("ov_event") == "subagent_start"),
                files_touched=len(files),
                minutes=round((max(ts) - min(ts)) / 60000.0, 1) if len(ts) > 1 else None,
                judgements=len(judge), shown=len(shown), bands=dict(bands),
                start_sh=rep.get("start_sh_present"), supervisor=rep.get("supervisor"),
                health=rep.get("health"), anti_cheat=rep.get("anti_cheat"),
                gates_passed=rep.get("gates_passed"), gates_total=rep.get("gates_total"),
                tests_passed=rep.get("tests_passed"), tests_total=rep.get("tests_total"),
                official_reward=rep.get("official_reward"),
                gate_detail={g["gate"]: "%s/%s" % (g["passed"], g["total"])
                             for g in rep.get("gates", [])})


ROWS = [("events recorded", "events"), ("decisions (Write/Edit/Bash/Agent)", "decisions"),
        ("all tool calls", "tool_calls"), ("subagents spawned", "spawns"),
        ("files written or edited", "files_touched"), ("wall clock, minutes", "minutes"),
        ("judge calls", "judgements"), ("reached the user", "shown"),
        ("start.sh present", "start_sh"), ("booted with a supervisor", "supervisor"),
        ("three nodes healthy", "health"), ("anti-cheat", "anti_cheat"),
        ("gates passed", "gates_passed"), ("tests passed", "tests_passed"),
        ("official reward (binary)", "official_reward")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--control", required=True)
    ap.add_argument("--treatment", required=True)
    ap.add_argument("--out")
    a = ap.parse_args()
    A, B = arm(a.control, "control (no tool)"), arm(a.treatment, "treatment (v3)")

    w = max(len(r[0]) for r in ROWS) + 2
    print("%-*s %-22s %-22s" % (w, "", A["label"], B["label"]))
    print("-" * (w + 46))
    for name, key in ROWS:
        va, vb = A.get(key), B.get(key)
        if key == "gates_passed":
            va = None if va is None else "%s/%s" % (va, A["gates_total"])
            vb = None if vb is None else "%s/%s" % (vb, B["gates_total"])
        if key == "tests_passed":
            va = None if va is None else "%s/%s" % (va, A["tests_total"])
            vb = None if vb is None else "%s/%s" % (vb, B["tests_total"])
        print("%-*s %-22s %-22s" % (w, name, "-" if va is None else va, "-" if vb is None else vb))
    if A["gate_detail"] or B["gate_detail"]:
        print("\nper gate (passed/total):")
        for g in sorted(set(A["gate_detail"]) | set(B["gate_detail"])):
            print("  %-10s %-14s %-14s" % (g, A["gate_detail"].get(g, "-"), B["gate_detail"].get(g, "-")))
    if B["bands"]:
        print("\ntreatment bands:", B["bands"])
    if a.out:
        json.dump(dict(control=A, treatment=B), open(a.out, "w"), indent=1)
        print("\nwrote", a.out)


if __name__ == "__main__":
    main()
