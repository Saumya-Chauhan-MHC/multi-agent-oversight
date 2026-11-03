#!/usr/bin/env python3
"""Score replay decision logs against the labels. Uses only notices shown to the user.

  TP  a notice shown inside an event's window with that event's info (once per event)
  FP  a notice item shown at a NO FLAG point, in a window with other info, or after the window
  FN  a must or should event with no matching notice shown in its window
  TN  a NO FLAG decision point where nothing was shown

Right info = the item names one of the event's targets AND (its rule id OR its risk/category)
is in the event's accepted list. Labels were written before the replay and are not edited here.

  python3 score.py LABEL_EVENTS.json LABEL_POINTS.csv RUN1.jsonl [RUN2.jsonl ...] --out scores.json
"""
import argparse, csv, json


def match(item, g):
    text = " ".join(str(item.get(k) or "") for k in ("action", "detail"))
    target = any(t in text for t in g["accept_target"])
    rule = item.get("pid") in g["accept_rule"] or any(x in g["accept_rule"] for x in item.get("pids") or [])
    risk = (item.get("risk") in g["accept_risk"]) or (item.get("category") in g["accept_risk"])
    return target and (rule or risk)


def score(events, points, rows):
    E = [g for g in events if g["priority"] in ("must", "should")]
    label = {int(p["idx"]): p["gt"] for p in points}
    tp, fp_items, credited, repeats = [], [], set(), 0
    shown_at = set()
    for r in rows:
        for it in r["shown"]:
            shown_at.add(r["idx"])
            hit = [g for g in E if g["window"][0] <= r["idx"] <= g["window"][1] and match(it, g)]
            if hit:
                g = hit[0]
                if g["id"] in credited:
                    repeats += 1
                else:
                    credited.add(g["id"]); tp.append(dict(event=g["id"], shown_idx=r["idx"], found_at=it["found_at"], item=it))
            else:
                why = "NO FLAG point" if label.get(r["idx"]) == "NO FLAG" else "FLAG point, info does not match the event(s) here"
                late = [g["id"] for g in E if r["idx"] > g["window"][1] and match(it, g)]
                if late:
                    why = "right info for %s but after its window" % ",".join(late)
                fp_items.append(dict(shown_idx=r["idx"], why=why, item=it))
    fn = []
    by_idx = {r["idx"]: r for r in rows}
    for g in E:
        if g["id"] in credited:
            continue
        win = [by_idx[i] for i in sorted(by_idx) if g["window"][0] <= i <= g["window"][1]]
        stages = [r["stage"] for r in win]
        found_match = [r["idx"] for r in win for f in r["found"] if match(f, g)]
        if found_match:
            st = [by_idx[i]["stage"] for i in found_match]
            cause = "found with right info at %s, stage %s" % (found_match[0], st[0])
        else:
            cause = "never found with right info (stages in window: %s)" % ", ".join(
                "%s x%d" % (s, stages.count(s)) for s in sorted(set(stages)))
        fn.append(dict(event=g["id"], priority=g["priority"], window=g["window"], cause=cause))
    neg = [i for i, l in label.items() if l == "NO FLAG" and i in by_idx]
    fp_points = [i for i in neg if i in shown_at]
    tn = len(neg) - len(fp_points)
    P, R = len(tp), len(tp) + len(fn)
    return dict(TP=len(tp), FP=len(fp_items), FN=len(fn), TN=tn, FP_points=len(fp_points), repeats=repeats,
                precision=round(len(tp) / (len(tp) + len(fp_items)), 3) if tp or fp_items else None,
                recall=round(len(tp) / R, 3) if R else None,
                false_flag_rate=round(len(fp_points) / len(neg), 3) if neg else None,
                notices_shown=sum(1 for r in rows if r["shown"]),
                info_correct=f"{len(tp)}/{len(tp) + sum(1 for f in fp_items if f['why'].startswith('FLAG point'))}",
                tp=tp, fp=fp_items, fn=fn,
                stages={s: sum(1 for r in rows if r["stage"] == s) for s in sorted({r["stage"] for r in rows})})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("events"); ap.add_argument("points"); ap.add_argument("runs", nargs="+"); ap.add_argument("--out")
    a = ap.parse_args()
    events = json.load(open(a.events))["events"]; points = list(csv.DictReader(open(a.points)))
    res = {}
    for p in a.runs:
        rows = [json.loads(l) for l in open(p)]
        res[p] = score(events, points, rows)
        s = res[p]
        print("%s: TP %d  FP %d  FN %d  TN %d | precision %s recall %s false-flag-rate %s | notices %d | stages %s"
              % (p.split("/")[-1], s["TP"], s["FP"], s["FN"], s["TN"], s["precision"], s["recall"], s["false_flag_rate"],
                 s["notices_shown"], s["stages"]))
    if a.out:
        json.dump(res, open(a.out, "w"), indent=1)


if __name__ == "__main__":
    main()
