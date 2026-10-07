#!/usr/bin/env python3
"""Replay recorded runs through the oversight tool's gates, offline (harness/gates.py).

  .venv/bin/python replay.py port_kill port_kill/runs/sonnet45/plain-*
  .venv/bin/python replay.py port_kill --count port_kill/runs/sonnet45/plain-*     # judge calls it would cost
  .venv/bin/python replay.py stale_merge --lines A stale_merge/runs/sonnet45/input_cap/none-*
  .venv/bin/python replay.py delegation_laundering --summary delegation_laundering/runs/sonnet45_plain/*/multi-*
  add --events to print every judged spawn and every violating or held call

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
    a = ap.parse_args(sys.argv[2:])
    runs = [os.path.realpath(r) for r in a.runs]
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


if __name__ == "__main__":
    main()
