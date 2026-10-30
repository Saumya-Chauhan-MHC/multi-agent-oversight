#!/usr/bin/env python3
"""Does the trajectory help or hurt? Monitors A and B at each run's committing step, with and without it.

At the step `harness/monitor_a.py` marks as the run's first committing action, each monitor is
called REPS times with the history the replay uses and REPS times with no history (request and
action only), nothing marked as already asked. Writes <run>/oversight_probe_history.json.

  .venv/bin/python history_probe.py <scenario> <run dirs>
"""
import json, os, sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from harness import monitor_a as ma                                 # noqa: E402
from harness.runner import load_scenario, OUTPUTS                   # noqa: E402

REPS = 2
OUT = "oversight_probe_history.json"


def probe(sc, run):
    ss = ma.steps(run)
    k = json.load(open(os.path.join(run, ma.OUT)))["commit_step"]        # the step A's replay marked
    if k is None:
        return None
    request = open(os.path.join(run, "prompt.txt")).read()
    action = ma.action_for_judge(ss[k])
    jobs = [(m, h) for m in ("A", "B") for h in ("history", "none") for _ in range(REPS)]
    hist, obs = ma.history(ss, k), ma.observed(ss, k)
    with ThreadPoolExecutor(4) as ex:
        outs = list(ex.map(lambda j: ma.MONITORS[j[0]][0].judge(request, hist if j[1] == "history" else "", action, observed=obs if j[1] == "history" else None), jobs))
    calls = [dict(monitor=m, input=h, **v) for (m, h), v in zip(jobs, outs)]
    o = dict(run=os.path.relpath(run, OUTPUTS), step=k, who=ss[k]["who"], tool=ss[k]["tool"],
             action=ma._clip(action, 600), calls=calls)
    json.dump(o, open(os.path.join(run, OUT), "w"), indent=1)
    return o


def main():
    sc = load_scenario(sys.argv[1])
    runs = [os.path.realpath(r) for r in sys.argv[2:]]
    with ThreadPoolExecutor(2) as ex:
        for o in ex.map(lambda r: probe(sc, r), runs):
            if not o:
                continue
            cell = lambda m, h: " ".join("%.2f" % c["p"] for c in o["calls"] if c["monitor"] == m and c["input"] == h)
            print("%-80s step=%-3d A hist %s | A none %s | B hist %s | B none %s" % (
                o["run"], o["step"], cell("A", "history"), cell("A", "none"), cell("B", "history"), cell("B", "none")))


if __name__ == "__main__":
    main()
