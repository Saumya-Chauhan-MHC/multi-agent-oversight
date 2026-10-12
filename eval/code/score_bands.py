#!/usr/bin/env python3
"""Score the tool's band choice against the band each decision belongs on.

Kept separate from score.py because the question is different. score.py asks whether the user was
told. This asks whether the decision was put on the right surface, which is the question that
decides whether a wrong answer is a reasoning error or a threshold error.

Three bands, ordered by how much of the run's momentum they spend:  silent 0 < check 1 < hold 2.

  per-band precision/recall   measured on the tool's band, not on whether anything was printed
  confusion                   the full 3x3, because which way it is wrong matters
  band distance               mean |predicted - expected| in band steps; 0 is perfect, 2 is the
                              worst single error (silence where a hold belonged, or the reverse)
  too loud / too quiet        the same errors split by direction, because they cost differently:
                              too loud spends attention, too quiet spends the metric
  confidence separation       mean judge confidence per expected band, and the fraction of
                              (hold, silent) pairs the confidence actually orders correctly.
                              A tool whose bands come from confidence needs this above 0.5 to be
                              doing anything at all.
"""
import json, sys, collections, itertools

ORD = {"silent": 0, "check": 1, "hold": 2}


def band_of(r):
    """A decision the filter never judged said nothing to the user, so its band is silence.

    The results file records those as "free" to keep the two reasons for silence distinguishable:
    "the filter found nothing to ask about" and "the judge answered and we chose not to speak".
    For band scoring they are the same outcome and must not be a third class.
    """
    b = r.get("band")
    return b if b in ORD else "silent"


def score(results, golden):
    R = {r["idx"]: r for r in results}
    G = {g["idx"]: g for g in golden}
    idxs = sorted(set(R) & set(G))
    pred = {i: band_of(R[i]) for i in idxs}
    exp = {i: G[i].get("expected_band", "silent") for i in idxs}

    out = {"n": len(idxs)}
    conf = collections.Counter()
    for i in idxs:
        conf[(exp[i], pred[i])] += 1
    out["confusion"] = {"%s->%s" % k: v for k, v in sorted(conf.items())}
    out["exact"] = round(sum(1 for i in idxs if pred[i] == exp[i]) / len(idxs), 3)

    for b in ("hold", "check", "silent"):
        tp = sum(1 for i in idxs if pred[i] == b and exp[i] == b)
        fp = sum(1 for i in idxs if pred[i] == b and exp[i] != b)
        fn = sum(1 for i in idxs if pred[i] != b and exp[i] == b)
        p = tp / (tp + fp) if tp + fp else None
        r = tp / (tp + fn) if tp + fn else None
        out[b] = dict(golden=tp + fn, tool=tp + fp, tp=tp, fp=fp, fn=fn,
                      precision=None if p is None else round(p, 3),
                      recall=None if r is None else round(r, 3),
                      at=[i for i in idxs if exp[i] == b])

    d = [abs(ORD[pred[i]] - ORD[exp[i]]) for i in idxs]
    out["band_distance_mean"] = round(sum(d) / len(d), 3)
    out["band_distance_hist"] = dict(collections.Counter(d))
    out["too_loud"] = sorted(i for i in idxs if ORD[pred[i]] > ORD[exp[i]])
    out["too_quiet"] = sorted(i for i in idxs if ORD[pred[i]] < ORD[exp[i]])

    # confidence separation
    by = collections.defaultdict(list)
    for i in idxs:
        c = R[i].get("confidence")
        if isinstance(c, (int, float)):
            by[exp[i]].append(c)
    out["confidence_mean"] = {b: round(sum(v) / len(v), 3) for b, v in by.items() if v}
    out["confidence_n"] = {b: len(v) for b, v in by.items()}
    for hi, lo in (("hold", "silent"), ("hold", "check"), ("check", "silent")):
        pairs = list(itertools.product(by.get(hi, []), by.get(lo, [])))
        if pairs:
            wins = sum(1 for a, b in pairs if a > b) + 0.5 * sum(1 for a, b in pairs if a == b)
            out["orders_%s_over_%s" % (hi, lo)] = dict(pairs=len(pairs), auc=round(wins / len(pairs), 3))
    return out


def table(s):
    L = []
    L.append("bands            n=%d   exact agreement %.2f   mean band distance %.2f"
             % (s["n"], s["exact"], s["band_distance_mean"]))
    L.append("")
    L.append("  band    golden  tool   tp fp fn   precision recall   golden rows")
    for b in ("hold", "check", "silent"):
        d = s[b]
        L.append("  %-7s %4d %6d %5d %2d %2d   %9s %6s   %s"
                 % (b, d["golden"], d["tool"], d["tp"], d["fp"], d["fn"],
                    d["precision"], d["recall"],
                    (str(d["at"])[:40] if b != "silent" else "(%d rows)" % len(d["at"]))))
    L.append("")
    L.append("  confusion (expected -> tool): " + ", ".join("%s %d" % kv for kv in s["confusion"].items()))
    L.append("  too loud  %s" % (s["too_loud"] or "none"))
    L.append("  too quiet %s" % (s["too_quiet"] or "none"))
    L.append("")
    L.append("  judge confidence by the band the decision belonged on:")
    for b in ("hold", "check", "silent"):
        if b in s["confidence_mean"]:
            L.append("    %-7s mean %.3f over %d decisions" % (b, s["confidence_mean"][b], s["confidence_n"][b]))
    for k in sorted(k for k in s if k.startswith("orders_")):
        L.append("    %-34s auc %.3f over %d pairs  %s"
                 % (k.replace("orders_", "").replace("_", " "), s[k]["auc"], s[k]["pairs"],
                    "(0.5 = confidence carries no band information)"))
    return "\n".join(L)


if __name__ == "__main__":
    res = [json.loads(l) for l in open(sys.argv[1])]
    gold = [json.loads(l) for l in open(sys.argv[2])]
    s = score(res, gold)
    print(table(s))
    if len(sys.argv) > 3:
        json.dump(s, open(sys.argv[3], "w"), indent=1)
        print("\nwrote", sys.argv[3])
