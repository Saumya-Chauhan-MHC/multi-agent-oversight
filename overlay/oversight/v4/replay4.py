#!/usr/bin/env python3
"""Replay a recorded run through the simplified tool.

Same no-lookahead rule as v3: at decision n the tool sees events 0..n-1 and nothing after, so the
registry and the dependency map are rebuilt from the past only.
"""
import json, os, sys, argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from oversight.v3 import filter as filt, replay as r3
from oversight.v4 import rules, policy4, judge4


def run(traj_path, rules_path, judge=True, limit=None, verbose=True, out_path=None):
    events = [json.loads(l) for l in open(traj_path) if l.strip()]
    tm = rules.parse(open(rules_path).read())
    sig = rules.signature(tm)
    dec = r3.decisions(events)
    if limit:
        dec = dec[:limit]
    bf = r3.briefs(events)

    proj = os.path.join(os.path.dirname(out_path or traj_path), "_v4ctl")
    os.makedirs(proj, exist_ok=True)
    for f in ("answers.json", "judged.json"):
        try:
            os.remove(os.path.join(policy4.ctl(proj), f))
        except OSError:
            pass

    rows, held, unjudged, free, cached_n = [], [], 0, 0, 0
    for n, (i, e) in enumerate(dec):
        past = events[:i]
        who = e.get("agent_id") or "orchestrator"
        tool, ti = e.get("tool_name"), (e.get("tool_input") or {})
        trig = filt.check(tm, past, tool, ti, who)
        if not trig:
            free += 1
            continue
        if trig.get("path") != "B":
            unjudged += 1
            continue
        action = filt.action_text(tool, ti)
        key = policy4.cache_key(action, sig, who)
        hit = policy4.cache_get(proj, key)
        if hit is not None and hit.get("band") != "hold":
            cached_n += 1
            continue
        v = (judge4.judge(tm, action, trig, bf.get(who, ""), {})
             if judge else dict(breaks=False, source="skipped"))
        band = policy4.decide(v, proj)
        policy4.cache_put(proj, key, dict(band=band, breaks=v.get("breaks")))
        row = dict(idx=n, event=i, agent=who, tool=tool, trigger=trig.get("reason"),
                   band=band, rule=v.get("rule"), why=v.get("why"), does=v.get("does"),
                   action=action[:160], source=v.get("source"))
        rows.append(row)
        if band == "hold":
            prior = policy4.answer_for(proj, v.get("rule"))
            row["reused"] = prior is not None
            if prior is None:
                policy4.record_answer(proj, v.get("rule"), "asked", "")
                held.append(row)
            if verbose:
                print("  idx %3d  %-22s %-10s rule=%-4s %s%s"
                      % (n, trig.get("reason"), who[:10], v.get("rule"),
                         (v.get("why") or "")[:60], "   [reused]" if prior is not None else ""))
    summary = dict(decisions=len(dec), free=free, unjudged_recall_net=unjudged,
                   cached=cached_n, judged=len(rows), held=len(held),
                   held_idx=[h["idx"] for h in held])
    if out_path:
        with open(out_path, "w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
    return summary, rows, held


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("trajectory")
    ap.add_argument("rules")
    ap.add_argument("--out")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--no-judge", action="store_true")
    a = ap.parse_args()
    s, rows, held = run(a.trajectory, a.rules, judge=not a.no_judge, limit=a.limit, out_path=a.out)
    print(json.dumps(s, indent=1))


if __name__ == "__main__":
    main()
