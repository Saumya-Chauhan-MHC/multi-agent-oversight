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
                own_passed=(rep.get("own_suite") or {}).get("passed"),
                own_total=(rep.get("own_suite") or {}).get("total"),
                not_runnable=", ".join(rep.get("gates_not_runnable") or []) or None,
                answers=dict(collections.Counter(
                    e.get("decision") for e in E if e.get("ov_event") == "v3_user")) or None,
                gate_detail={g["gate"]: "%s/%s" % (g["passed"], g["total"])
                             for g in rep.get("gates", [])})


ROWS = [("events recorded", "events"), ("decisions (Write/Edit/Bash/Agent)", "decisions"),
        ("all tool calls", "tool_calls"), ("subagents spawned", "spawns"),
        ("files written or edited", "files_touched"), ("wall clock, minutes", "minutes"),
        ("judge calls", "judgements"), ("reached the user", "shown"),
        ("developer answers", "answers"),
        ("start.sh present", "start_sh"), ("booted with a supervisor", "supervisor"),
        ("three nodes healthy", "health"), ("anti-cheat", "anti_cheat"),
        ("gates not runnable here", "not_runnable"),
        ("the agent's own suite", "own_passed"),
        ("gates passed (runnable)", "gates_passed"), ("official tests passed", "tests_passed"),
        ("official reward (binary)", "official_reward")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", action="append", required=True, metavar="LABEL=DIR",
                    help="repeatable, e.g. --arm 'control (no tool)=~/research/arm_a_control'")
    ap.add_argument("--out")
    a = ap.parse_args()
    arms = []
    for spec in a.arm:
        label, _, d = spec.partition("=")
        arms.append(arm(os.path.expanduser(d), label))

    def cell(x, key):
        v = x.get(key)
        if v is None:
            return "-"
        if key == "gates_passed":
            return "%s/%s" % (v, x["gates_total"])
        if key == "own_passed":
            return "%s/%s passed" % (v, x["own_total"])
        if key == "tests_passed":
            return "%s/%s" % (v, x["tests_total"])
        return str(v)

    w = max(len(r[0]) for r in ROWS) + 2
    cw = max(24, max(len(x["label"]) for x in arms) + 2)
    print("%-*s%s" % (w, "", "".join("%-*s" % (cw, x["label"]) for x in arms)))
    print("-" * (w + cw * len(arms)))
    for name, key in ROWS:
        print("%-*s%s" % (w, name, "".join("%-*s" % (cw, cell(x, key)) for x in arms)))
    gates = sorted({g for x in arms for g in x["gate_detail"]})
    if gates:
        print("\nper gate (passed/total):")
        for g in gates:
            print("  %-10s%s" % (g, "".join("%-*s" % (cw, x["gate_detail"].get(g, "-"))
                                            for x in arms)))
    print("\nbands raised:")
    for x in arms:
        print("  %-*s %s" % (cw, x["label"], x["bands"] or "none"))
    print("\nwhat the developer said:")
    for x in arms:
        print("  %-*s %s" % (cw, x["label"], x["answers"] or "nobody was asked"))
    if a.out:
        json.dump({x["label"]: x for x in arms}, open(a.out, "w"), indent=1)
        print("\nwrote", a.out)


if __name__ == "__main__":
    main()
