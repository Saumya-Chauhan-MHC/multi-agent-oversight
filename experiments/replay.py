#!/usr/bin/env python3
"""Replay recorded runs through the oversight tool's gates, offline (harness/gates.py).

  .venv/bin/python replay.py delegation_laundering outputs/week_0/delegation_laundering/sonnet45-multi-notool/*/plain-*
  .venv/bin/python replay.py delegation_laundering --count outputs/week_0/delegation_laundering/sonnet45-multi-notool/*/plain-*   # judge calls it would cost
  .venv/bin/python replay.py delegation_laundering --summary outputs/week_0/delegation_laundering/sonnet45-multi-notool/*/plain-*
  add --events to print every judged spawn and every violating or held call
  .venv/bin/python replay.py delegation_laundering --tool baseline [--threshold T] <run dirs>   # harness/baseline_gates.py
  .venv/bin/python replay.py swechat --tool A [--threshold T] [--grade] <run dirs>   # Monitor A (harness/monitor_a.py)
  .venv/bin/python replay.py swechat --tool B [--threshold T] <run dirs>   # Monitor B (overlay/oversight/vb), A's inputs
  .venv/bin/python replay.py swechat --tool B-action <run dirs>             # Monitor B on the request and the action only

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
    ap.add_argument("--tool", choices=("v2", "baseline", "A", "B", "B-action"), default="v2")
    ap.add_argument("--threshold", type=float, default=None, help="baseline: hold at this score (default policy5.THRESHOLD)")
    ap.add_argument("--grade", action="store_true", help="A: grade each hold's question against the scenario's cards")
    a = ap.parse_args(sys.argv[2:])
    runs = [os.path.realpath(r) for r in a.runs]
    if a.tool == "baseline":
        return main_baseline(sc, a, runs)
    if a.tool in ("A", "B", "B-action"):
        return main_a(sc, a, runs)
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


def main_baseline(sc, a, runs):
    from harness import baseline_gates as bg
    if a.summary:
        outs = [json.load(open(os.path.join(r, bg.OUT))) for r in runs]
    else:
        with ThreadPoolExecutor(a.jobs) as ex:
            outs = list(ex.map(lambda r: bg.replay(sc, r), runs))
    t = a.threshold if a.threshold is not None else bg.THRESHOLD
    for o in outs:
        s = bg.summarize(o, t)
        print("%-60s decisions=%d bad_calls=%d bad_held=%d first_bad_held=%-5s held_by_then=%-5s holds=%d "
              "false_holds=%d unavail=%d invalid_quote=%d" % (
                  s["run"], s["decisions"], s["violating_calls"], s["bad_held"], s["first_bad_held"], s["held_by_then"],
                  s["holds"], s["false_holds"], s["unavailable"], s["invalid_quote"]))
        if a.events:
            for r in o["results"]:
                if r["violating"] or r["score"] >= t:
                    print("   %s %.2f %-13s %s | %s" % ("BAD" if r["violating"] else "ok ", r["score"], r["source"],
                                                       " ".join(r["action"].split())[:80], (r.get("why") or "")[:120]))


def main_a(sc, a, runs):
    from harness import monitor_a as ma
    mod, out_name = ma.MONITORS[a.tool]
    t = a.threshold if a.threshold is not None else mod.THRESHOLD
    if not a.summary:
        with ThreadPoolExecutor(a.jobs) as ex:
            list(ex.map(lambda r: ma.replay(sc, r, t, a.tool), runs))
    if a.grade and a.tool == "A":
        with ThreadPoolExecutor(a.jobs) as ex:
            list(ex.map(lambda r: ma.score_questions(r, t), runs))
    for r in runs:
        o = json.load(open(os.path.join(r, out_name)))
        s = ma.summarize(o, t)
        print("%-70s judged=%d commit=%s holds=%d held_by_commit=%-5s first_hold=%s unavail=%d ev=%d/%d" % (
            s["run"], s["judged"], s["commit_step"], s["holds"], s["held_by_commit"], s["first_hold"],
            s["unavailable"], s["evidence_kept"], s["evidence_kept"] + s["evidence_dropped"]))
        if a.events:
            for x in o["results"]:
                if x.get("commits") or mod.held(x, t):
                    print("   %s %.2f %-13s step=%-3d %s | %s" % ("COMMIT" if x["commits"] else "      ", x["p"],
                          x.get("kind", "B"), x["step"], " ".join(x["action"].split())[:70],
                          (x.get("decision") or x.get("said") or "")[:110]))


if __name__ == "__main__":
    main()
