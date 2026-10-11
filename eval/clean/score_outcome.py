#!/usr/bin/env python3
"""Score the surfacing against the run's real outcome, not only against a judgement of it.

The other two scorers ask whether the tool spoke at the right moments and on the right band. This
one asks the two questions a developer actually cares about:

  did it speak where speaking would have improved the official test result
  would the developer have been glad of what it did say, knowing how the run turned out

Both need something the old recording did not have: a graded outcome. Arm A was built with no
tool and then run through the real SWE-Marathon gates, so every label can carry the official test
it bears on and whether acting on it would plausibly have changed that test.

  outcome recall        of the moments where acting would likely have fixed a real failure,
                        how many did the tool surface at all (any band)
  outcome precision     of what the tool surfaced, how much was tied to a real failure
  satisfaction of what   the golden satisfied_after of every item the tool put in front of the
  was shown             developer: glad / neutral / annoyed, judged after the grader spoke
  harm                  items the tool surfaced that are labelled "annoyed", meaning acting on
                        them would have made the run worse. These are worse than ordinary false
                        positives and are counted separately
  silent misses         moments labelled would_help=likely that the tool never raised in any band

A note on what "likely" means. It is a judgement that acting at that moment would plausibly have
changed the outcome, made with the failure list in hand. It is not a counterfactual measurement:
nobody re-ran the task with the flag delivered. The honest reading is "this is where the leverage
was", not "this many tests would have passed".
"""
import collections, json, sys

ORD = {"silent": 0, "check": 1, "hold": 2}


def band_of(r):
    b = r.get("band")
    return b if b in ORD else "silent"


def score(results, golden):
    R = {r["idx"]: r for r in results}
    G = {g["idx"]: g for g in golden}
    idxs = sorted(set(R) & set(G))

    spoke = [i for i in idxs if band_of(R[i]) in ("hold", "check")]
    shown = [i for i in idxs if R[i].get("shown")]
    leverage = [i for i in idxs if G[i].get("would_help") == "likely"]
    tied = [i for i in idxs if G[i].get("official_test")]

    out = dict(n=len(idxs), spoke=spoke, shown=shown,
               leverage_points=leverage, tied_to_a_real_failure=tied)

    caught = [i for i in leverage if i in spoke]
    out["outcome_recall"] = dict(
        of=len(leverage), caught=len(caught), at=caught,
        value=round(len(caught) / len(leverage), 3) if leverage else None,
        note="of the moments where acting would likely have fixed a real official failure, "
             "how many the tool raised in any band")
    hit = [i for i in spoke if G[i].get("official_test")]
    out["outcome_precision"] = dict(
        of=len(spoke), tied=len(hit), at=hit,
        value=round(len(hit) / len(spoke), 3) if spoke else None,
        note="of what the tool raised, how much bears on a failure that really happened")

    sat = collections.Counter(G[i].get("satisfied_after", "neutral") for i in spoke)
    out["satisfaction_of_what_was_raised"] = dict(sat)
    sat_shown = collections.Counter(G[i].get("satisfied_after", "neutral") for i in shown)
    out["satisfaction_of_what_reached_the_user"] = dict(sat_shown)

    harm = [i for i in spoke if G[i].get("satisfied_after") == "annoyed"]
    out["harm"] = dict(count=len(harm), at=harm,
                       note="raised, and labelled annoyed: acting on these would have made the "
                            "run worse, not merely wasted attention")
    out["silent_misses"] = dict(at=[i for i in leverage if i not in spoke],
                                note="leverage points the tool never raised in any band")

    # where the leverage points went, stage by stage
    detail = []
    for i in leverage + [j for j in tied if j not in leverage]:
        r, g = R[i], G[i]
        detail.append(dict(idx=i, tool_trigger=r.get("trigger"), tool_verdict=r.get("verdict"),
                           tool_confidence=r.get("confidence"), tool_band=band_of(r),
                           tool_shown=bool(r.get("shown")),
                           golden_band=g.get("expected_band"), golden_pref=g.get("pref"),
                           golden_risk=g.get("risk"), would_help=g.get("would_help"),
                           satisfied_after=g.get("satisfied_after"),
                           official_test=g.get("official_test")))
    out["leverage_detail"] = detail
    return out


def table(s):
    L = ["outcome scoring   n=%d   tool raised %d (%s)   reached the user %d (%s)"
         % (s["n"], len(s["spoke"]), s["spoke"], len(s["shown"]), s["shown"])]
    L.append("")
    r = s["outcome_recall"]
    L.append("  outcome recall      %s   caught %d of %d leverage points %s"
             % (r["value"], r["caught"], r["of"], r["at"]))
    p = s["outcome_precision"]
    L.append("  outcome precision   %s   %d of %d raised items bear on a real failure"
             % (p["value"], p["tied"], p["of"]))
    L.append("  harm                %d %s" % (s["harm"]["count"], s["harm"]["at"] or ""))
    L.append("  silent misses       %s" % (s["silent_misses"]["at"] or "none"))
    L.append("")
    L.append("  how the developer would feel about what was raised, judged after the grader spoke:")
    for k in ("glad", "neutral", "annoyed"):
        if k in s["satisfaction_of_what_was_raised"]:
            L.append("    %-8s %d" % (k, s["satisfaction_of_what_was_raised"][k]))
    L.append("")
    L.append("  the moments that carried the leverage:")
    L.append("    idx  tool                                      golden            help    after")
    for d in s["leverage_detail"]:
        L.append("    %3d  %-14s %-8s %-5s %-6s shown=%-5s %-6s %-9s %-7s %s"
                 % (d["idx"], d["tool_trigger"] or "free", d["tool_verdict"] or "-",
                    d["tool_confidence"], d["tool_band"], d["tool_shown"],
                    d["golden_band"], d["golden_pref"] or "-", d["would_help"],
                    d["satisfied_after"]))
    return "\n".join(L)


if __name__ == "__main__":
    res = [json.loads(l) for l in open(sys.argv[1])]
    gold = [json.loads(l) for l in open(sys.argv[2])]
    s = score(res, gold)
    print(table(s))
    if len(sys.argv) > 3:
        json.dump(s, open(sys.argv[3], "w"), indent=1)
        print("\nwrote", sys.argv[3])
