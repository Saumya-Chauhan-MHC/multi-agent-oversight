#!/usr/bin/env python3
"""B -> A: every hold of the action-only Monitor B is one more thing A sees.

Reads <run>/oversight_replay_vb_action.json and, once per hold, asks A its one question on the state
of the work (`judge_a.judge_state`), with the stop as the newest event and the same history A's
replay uses. Writes <run>/oversight_b_to_a_state.json.

  .venv/bin/python b_to_a.py <run dirs>
"""
import json, os, sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from harness import monitor_a as ma                                 # noqa: E402
from harness.runner import OUTPUTS                                  # noqa: E402

OUT = "oversight_b_to_a_state.json"          # oversight_b_to_a.json holds the first version's answers


def one(run):
    o = json.load(open(os.path.join(run, "oversight_replay_vb_action.json")))
    holds = [x for x in o["results"] if ma.judge_b.held(x, o["threshold"])]
    if not holds:
        return None
    ss = ma.steps(run)
    request = open(os.path.join(run, "prompt.txt")).read()
    with ThreadPoolExecutor(3) as ex:
        outs = list(ex.map(lambda h: ma.judge_a.judge_state(
            request, ma.history(ss, h["step"]),
            ma.judge_a.stopped(ma.action_for_judge(ss[h["step"]]), h["said"], h["does"]),
            observed=ma.observed(ss, h["step"])), holds))
    res = dict(run=os.path.relpath(run, OUTPUTS), commit_step=o["commit_step"],
               items=[dict(step=h["step"], tool=h["tool"], action=h["action"], said=h["said"], does=h["does"], a=a)
                      for h, a in zip(holds, outs)])
    json.dump(res, open(os.path.join(run, OUT), "w"), indent=1)
    return res


if __name__ == "__main__":
    runs = [os.path.realpath(r) for r in sys.argv[1:]]
    with ThreadPoolExecutor(3) as ex:
        for r in ex.map(one, runs):
            if r:
                for it in r["items"]:
                    a = it["a"]
                    print("%-75s step=%-3d %-13s p=%.2f %s" % (r["run"][-75:], it["step"], a.get("kind"), a.get("p", 0),
                          (a.get("problem") or a.get("way_forward") or a.get("why") or "")[:120].replace("\n", " ")))
