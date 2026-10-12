# Comparison 1 — key takeaways

**One sentence:** replay the recorded run decision by decision and ask whether the tool's choice to
speak or stay quiet was right, against an answer key written before the tool was run.

111 decisions. 2 moments the key says were worth surfacing.

```
                           precision recall    f1
detection                  0.13      1.00      0.24     did the judge see it
surfacing                  0.50      0.50      0.50     did the developer get told

band accuracy              0.97      mean band distance 0.03
attribution  pref/metric/risk   1.00 / 1.00 / 1.00
alarms per 100 decisions   1.8
harm                       0
```

## What this says about the tool

**1 · It sees both moments, every time.** Detection recall 1.00. Nothing is missed at the filter or
the judge — the tool's reading of what is going on agrees with the key.

**2 · Half of what it sees reaches nobody.** Surfacing 0.50 against detection 1.00. **The gap
between those two numbers is the single most important result here:** the tool knows, and the
developer is not told.

**3 · When it speaks, it speaks accurately.** Attribution 1.00 on all three axes — the item that
got through cited the right requirement, the right metric and the right safety risk. A flag with the
wrong reason is unanswerable, so this is the axis that decides whether a notice is usable at all.

**4 · Precision is what limits recall, which is unusual and worth understanding.** There is one
channel, rationed to one item every ten minutes. So a false positive does not merely waste
attention — **it displaces a true positive.** Buying recall here means buying precision first.

**5 · It is quiet, and quiet about the right things.** 1.8 alarms per 100 decisions. Three moments
in this run would have made things *worse* if acted on: stopping the lead from writing its own
interface contracts, and an `if False` in production source that a keyword search hits. **It raised
none of them. Harm 0.**

**6 · The band assignment is nearly right.** 0.97 exact agreement, mean band distance 0.03 — when it
is wrong about the band it is wrong by one step, not two.

## What it does not establish

**Two golden positives is not a sample.** A 95% interval on recall over two positives spans most of
the scale. These are figures about this run, not properties of the tool.

**The strongest path is untested here.** This run contains **no hold-band moment at all** — no
shared interface rewritten under live dependents, no disabled assertion, and across all 111
decisions no subagent ever wrote a file it did not own. **No conflict instances.** So the
deterministic lookups the tool is best at mostly did not get a chance to fire.

**It has not reproduced.** A second recording replayed under this same implementation did not
reproduce these figures. I am keeping that line in rather than reporting the good run alone, because
a single non-replicated result is what these numbers are.

**The answer key shares an author with the system.** `human_confirmed` is empty on all 111 rows. The
key passes a mechanical validator — 974 checks — which confirms every citation resolves, not that it
is the apt one.
