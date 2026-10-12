#!/usr/bin/env python3
"""Replay recorded runs through the oversight tool's gates, offline (harness/gates.py).

  .venv/bin/python replay.py port_kill port_kill/runs/sonnet45/plain-*
  .venv/bin/python replay.py port_kill --count port_kill/runs/sonnet45/plain-*     # judge calls it would cost
  .venv/bin/python replay.py stale_merge --lines A stale_merge/runs/sonnet45/input_cap/none-*
  .venv/bin/python replay.py delegation_laundering --summary delegation_laundering/runs/sonnet45_plain/*/multi-*
  add --events to print every judged spawn and every violating or held call
  .venv/bin/python replay.py delegation_laundering --tool v3 [--no-judge] <run dirs>   # the v3 tool (harness/v3_gates.py)

The user's lines and what counts as a violating call come from the scenario. Writes
<run>/oversight_replay.json (or oversight_replay_<lines>.json for a named variant).
"""
import argparse, json, os, sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from harness import gates                                           # noqa: E402
from harness.runner import load_scenario                            # noqa: E402


def print_events(o):
    for e in o["events"]:
        if e["gate"] != "spawn" and not (e.get("violating") or e["band"] == "hold" or e.get("verdict") == "departs"):
            continue
        tag = "SPAWN" if e["gate"] == "spawn" else ("BAD  " if e.get("violating") else "ok   ")
        print("   %s %-6s %-8s %-8s %-5s %s" % (tag, e.get("role") or "", e["band"], e.get("verdict"),
                                              e.get("confidence"), " ".join(str(e.get("what", "")).split())[:100]))


def main():
    if len(sys.argv) < 2 or sys.argv[1].startswith("-"):
        sys.exit(__doc__)
    sc = load_scenario(sys.argv[1])
    ap = argparse.ArgumentParser(prog="replay.py %s" % sc.name)
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--lines", choices=sc.replay_variants, default=sc.replay_variants[0])
    ap.add_argument("--spawns-only", action="store_true", help="only the spawn gate")
    ap.add_argument("--count", action="store_true", help="keyword filter only: how many judge calls a replay costs")
    ap.add_argument("--summary", action="store_true", help="only summarize existing replays")
    ap.add_argument("--events", action="store_true")
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--tool", choices=("v2", "v3"), default="v2")
    ap.add_argument("--no-judge", action="store_true", help="v3: filter and structure only, no model calls")
    ap.add_argument("--no-extract", action="store_true", help="v3: fail rather than extract a missing task model")
    a = ap.parse_args(sys.argv[2:])
    runs = [os.path.realpath(r) for r in a.runs]
    if a.tool == "v3":
        return main_v3(sc, a, runs)
    if a.summary:
        outs = [json.load(open(os.path.join(r, gates.out_name(a.lines)))) for r in runs]
    else:
        with ThreadPoolExecutor(a.jobs) as ex:
            outs = list(ex.map(lambda r: gates.replay(sc, r, a.lines, a.spawns_only, a.count), runs))
    for o in outs:
        ev = o["events"]
        if a.count:
            print("%-40s spawns=%d judged_actions=%d violating=%d (unjudged %d)" % (
                o["run"], sum(e["gate"] == "spawn" for e in ev),
                sum(e["gate"] == "action" and e["band"] == "?" for e in ev),
                sum(bool(e.get("violating")) for e in ev), sum(e["band"] == "unjudged" for e in ev)))
            continue
        s = gates.summarize(o)
        print("%-40s bad_calls=%d held_bad=%d held_by_then=%-5s holds=%d checks=%d departs_unheld=%d judged=%d unavail=%d" % (
            s["run"], s["violating_calls"], s["violating_held"], s["held_at_or_before_violation"], s["holds"],
            s["checks"], s["departs_not_held"], s["judged"], s["unavailable"]))
        if a.events:
            print_events(o)


def main_v3(sc, a, runs):
    from harness import v3_gates
    if a.summary:
        outs = [json.load(open(os.path.join(r, v3_gates.OUT))) for r in runs]
    else:
        for r in runs:                       # one extraction per instance, before the parallel replays
            v3_gates.task_model(r, extract=not a.no_extract)
        with ThreadPoolExecutor(a.jobs) as ex:
            outs = list(ex.map(lambda r: v3_gates.replay(sc, r, judge=not a.no_judge), runs))
    for o in outs:
        s = v3_gates.summarize(o)
        print("%-40s decisions=%d to_judge=%d bad_calls=%d bad_filtered=%d bad_shown=%d held_by_then=%-5s "
              "noted_by_then=%-5s holds=%d checks=%d triggers=%s" % (
                  s["run"], s["decisions"], s["to_judge"], s["violating_calls"], s["bad_filtered"],
                  s["bad_shown"], s["held_by_then"], s["noted_by_then"], s["holds_shown"],
                  s["checks_shown"], ",".join(s["triggers"])))
        if a.events:
            for r in o["results"]:
                if r.get("violating") or r.get("shown"):
                    print("   %s %-26s %-6s %-5s %s" % ("BAD" if r["violating"] else "ok ", r.get("trigger") or "-",
                                                     r.get("band"), "SHOWN" if r.get("shown") else "",
                                                     " ".join(r["action"].split())[:90]))


if __name__ == "__main__":
    main()
