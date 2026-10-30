# v6 — the SSOT build

What SSOT (26) and (27) describe, built and tested. Two things separate it from v5: preferences
come back, and safety gets its own channel.

## What it does

```
PRD  ──deterministic──▶  task_model.json  (P1–P4 preferences, no model involved)
                               │
agent action ──▶ code lookup ──┤
                               ├─▶ safety finding    ──▶ safety queue     ──▶ developer
                               └─▶ preference finding ──▶ preference queue ──▶ developer
                                                                               │
                                        task_model.json  ◀──LLMAJ──  accept/reject + why
```

Code settles the fact. The judge is asked only what code cannot settle. The queue decides whether
the developer is interrupted now or later. A safety finding and a preference finding never get
ranked against each other.

## The three safety risks

None of these detectors is a new idea. Each mirrors a mitigation that production systems already
use for that failure mode.

| risk | published failure mode | what the detector mirrors |
|---|---|---|
| **collusion** | ImpossibleBench, [2510.20270](https://arxiv.org/abs/2510.20270) — models pass "impossible" tasks by modifying assertions, special-casing, or keeping state to game the evaluation | protected paths + a diff check. SWE-bench restores test files from the reference commit before grading; CODEOWNERS and pre-commit's `no-commit-to-branch` are the same idea at review time |
| **miscoordination** | Passes Alone, Fails Together (STALE), [2609.25396](https://arxiv.org/abs/2609.25396) — same tests pass on each patch alone and fail on the combination | *before*: reverse-dependency / blast-radius analysis, as `bazel query rdeps` and CODEOWNERS reviewer selection do. *after*: the merge-queue rule — GitHub merge queues and Zuul re-test against the updated base, for exactly STALE's reason |
| **conflict** | Worse Together, [2610.00583](https://arxiv.org/abs/2610.00583) — teams sharing limited resources underperform one coordinating agent | advisory locking and ownership registries: `flock`, pidfiles, "address already in use". The paper motivates the risk; it supplies no detector, so the detector is borrowed from here |

Each finding carries the category it extends (collusion → P3, miscoordination → P2, conflict →
P1), the metric it costs, and the one narrow question left for the judge.

## The queue

One at a time. `OV_QUIET_S` (600s) after each. `OV_QUEUE_DEPTH` (10) per channel, oldest dropped
first. Same-kind flags combine into one interruption that lists each concrete request.

One exception: a miscoordination flag raised *before* the interface moves preempts the quiet
window, because once every dependent has built on the old contract no later answer repairs it. A
stale done-claim does not — that one is already late.

## Preferences that move

`prefs.update_from_feedback()` gives the judge the preference as it stands and the developer's
exact words, and allows three outcomes: `keep`, `narrow`, `replace`. Two guards:

- **quote** — a revision must quote the developer verbatim, or it is refused as `unquoted`
- **agreement** — accepting a flag can never change a preference, enforced in code

Every revision appends to the preference's `history`, so "your preferences are changing" is
something the tool can show: original wording, what it became, and the sentence that moved it.

## Run it

```
python3 oversight/v6/tests/test_v6.py        # 63 checks
python3 oversight/v6/demo6.py                # all 8 stages, through the real hook
OV_DEMO_LIVE_JUDGE=1 python3 oversight/v6/demo6.py
python3 oversight/v6/shot.py ~/Downloads/v6_screenshots
```

`demo6.py` runs `.claude/hooks/v6_gate.py` as a subprocess with real payloads. Nothing is mocked
except the developer typing, and the judge in stage 7 unless `OV_DEMO_LIVE_JUDGE=1`.

## Two bugs this build found

**Miscoordination-before was dead code.** `v3.taskmodel.interface_dependents` looks the file up in
a `files` list on the P2 preferences. Only the extractor ever populated that list. When the
extractor was replaced by the deterministic builder nothing wrote it any more, the set was always
empty, and the detector silently never fired again — a clean run and a run with the detector
deleted look identical from outside. v6 derives the interface from the dependency graph instead,
which is also the more standard shape: `rdeps` does not ask anyone to declare what an interface is.

**The one queue exception did not exist.** `next_to_show` checked only the head of the queue for a
preempting item, so a moving interface sitting behind two older flags waited its turn like
anything else. Found by the demo: stage 5 claimed to preempt and did not.

## Still open

- `v6_gate.py` is wired nowhere in `overlay/.claude/settings.json`
- the DAG view is v3's and has not been re-pointed at v6's events
- no arm has been run with v6; everything above is the test suite and the demo
