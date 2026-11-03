#!/usr/bin/env python3
"""Score replay decision logs per decision point. Uses only notices shown to the user.

  FLAG point,    notice with the event's right info  -> TP
  FLAG point,    notice with other info              -> FP
  FLAG point,    nothing shown                        -> FN
  NO FLAG point, any notice                           -> FP
  NO FLAG point, nothing shown                        -> TN

Right info = the notice names one of the event's targets AND its rule id or its risk is in the
event's accepted list. Labels were written before the replay and are not edited here.

  python3 score_points.py LABEL_EVENTS.json LABEL_POINTS.csv RUN.jsonl [...] --out scores.json
"""
import argparse, csv, json
from score import match


def score(events, points, rows):
    E = {g["id"]: g for g in events if g["priority"] in ("must", "should")}
    by = {r["idx"]: r for r in rows}
    out, per_event = [], {g: dict(TP=0, FP=0, FN=0) for g in E}
    for p in points:
        i = int(p["idx"]); r = by[i]; shown = r["shown"]
        if p["gt"] == "FLAG":
            evs = [E[e] for e in p["event"].split(",") if e in E]
            hit = [g["id"] for g in evs if any(match(it, g) for it in shown)]
            o = "TP" if hit else ("FP" if shown else "FN")
            for g in (hit or [g["id"] for g in evs]):
                per_event[g][o] += 1
        else:
            o = "FP" if shown else "TN"
        out.append(dict(idx=i, gt=p["gt"], event=p["event"], outcome=o, stage=r["stage"],
                        shown=["%s %s %s" % (it.get("kind"), it.get("risk") or it.get("pid"), (it.get("action") or "").split("/")[-1])
                               for it in shown]))
    c = {k: sum(1 for x in out if x["outcome"] == k) for k in ("TP", "FP", "FN", "TN")}
    fp_flag = sum(1 for x in out if x["outcome"] == "FP" and x["gt"] == "FLAG")
    return dict(**c, FP_at_flag_points=fp_flag, FP_at_noflag_points=c["FP"] - fp_flag,
                precision=round(c["TP"] / (c["TP"] + c["FP"]), 3) if c["TP"] + c["FP"] else None,
                recall=round(c["TP"] / (c["TP"] + c["FN"]), 3) if c["TP"] + c["FN"] else None,
                false_flag_rate=round((c["FP"] - fp_flag) / sum(1 for x in out if x["gt"] == "NO FLAG"), 3),
                points_with_notice=sum(1 for x in out if x["shown"]),
                content_right="%d/%d" % (c["TP"], c["TP"] + fp_flag),
                per_event=per_event, points=out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("events"); ap.add_argument("points"); ap.add_argument("runs", nargs="+"); ap.add_argument("--out")
    a = ap.parse_args()
    ev = json.load(open(a.events))["events"]; pts = list(csv.DictReader(open(a.points)))
    res = {}
    for p in a.runs:
        s = res[p] = score(ev, pts, [json.loads(l) for l in open(p)])
        print("%s: TP %d FP %d (%d at FLAG, %d at NO FLAG) FN %d TN %d | precision %s recall %s false-flag-rate %s | content %s"
              % (p.split("/")[-1], s["TP"], s["FP"], s["FP_at_flag_points"], s["FP_at_noflag_points"], s["FN"], s["TN"],
                 s["precision"], s["recall"], s["false_flag_rate"], s["content_right"]))
        print("   per event:", s["per_event"], "| TP points:", [x["idx"] for x in s["points"] if x["outcome"] == "TP"])
    if a.out:
        json.dump(res, open(a.out, "w"), indent=1)


if __name__ == "__main__":
    main()
