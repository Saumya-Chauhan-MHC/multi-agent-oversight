#!/usr/bin/env python3
"""Everything between a verdict and a human being interrupted. No model runs here.

  metric gate    a departure that threatens none of the three metrics is recorded, never shown.
                 A fit is silent too: when the preferences come from the task itself, "nothing
                 covers this" is not news, it is most of the run.
  grouping       the block's label is the preference cited, so the same kind of judgement is
                 one interruption however many flags land inside it
  queue          one block at a time, worst metric first, then confidence
  quiet window   ten minutes after any answer; the window also filters, since flags whose action
                 has landed can no longer be steered and leave
  preempt        one exception: a declared interface change two or more agents already built on
  precision      if the user waves holds through, holds become notices until that recovers
"""
import hashlib, json, os, time
from . import taskmodel as tmod

WINDOW_S = 600          # ten minutes of quiet after an answer
PREEMPT_EVERY_S = 3600  # at most one jumped window per hour
HOLD_BAND = 0.85
CHECK_BAND = 0.50
PRECISION_FLOOR = 0.70


def ctl(proj):
    d = os.path.join(proj, "oversight", "control3")
    os.makedirs(d, exist_ok=True)
    return d


def _read(proj, name, default):
    try:
        return json.load(open(os.path.join(ctl(proj), name)))
    except Exception:
        return default


def _write(proj, name, obj):
    json.dump(obj, open(os.path.join(ctl(proj), name), "w"), indent=1)
    return obj


def now():
    return int(time.time() * 1000)


# ---------------------------------------------------------------- cache
def cache_key(action_text, rules_sig, agent=""):
    """Keyed on the agent too: the lead defining an interface and a component agent
    rewriting the same path later are different decisions, and the second must not be
    served the first one's verdict.
    """
    return hashlib.sha256((agent + "|" + action_text + "|" + rules_sig).encode()).hexdigest()[:16]


def cache_get(proj, key):
    try:
        return json.load(open(os.path.join(ctl(proj), "seen", key + ".json")))
    except Exception:
        return None


def cache_put(proj, key, verdict):
    d = os.path.join(ctl(proj), "seen")
    os.makedirs(d, exist_ok=True)
    json.dump(verdict, open(os.path.join(d, key + ".json"), "w"), indent=1)


# ---------------------------------------------------------------- bands and the metric gate
STRUCTURAL = {"graded_file", "disabled_check", "weakened_check", "resource_owned_elsewhere",
              "declared_interface", "stale_claim"}


def band(verdict, proj=None, trigger=None):
    """Which surface this verdict belongs on. Silence is the default and has to be argued out of.

    `trigger` is the filter's reason. An item whose only support is word overlap is capped at
    silence: it is still judged and still recorded, so its value can go on being measured, but it
    cannot spend the user's attention on its own.

    That cap is the one change both evaluations asked for independently. On the first trajectory
    word overlap raised 3 flags and all 3 were wrong while the structural lookups raised 2 and both
    were right. On the second it raised 5 and all 5 were wrong, and because the channel is rationed
    those 5 did not merely waste attention -- they arrived earlier in the run, found an open quiet
    window, and spent it, so the two items that mattered were still queued when the run ended.
    With a rationed channel a false positive is not just noise, it is a true positive displaced.

    Word overlap keeps its job, which is recall: it is what gets a decision in front of the judge
    at all when no deterministic lookup matched. What it does not get is a vote on interrupting.
    """
    if verdict.get("source") == "unavailable":
        return "silent"
    if verdict.get("verdict") == "departs" and not verdict.get("metric"):
        return "silent"                       # the gate: a breach with nothing at stake
    if trigger is not None and trigger not in STRUCTURAL:
        return "silent"                       # a recall net does not get to interrupt
    conf = float(verdict.get("confidence") or 0)
    if verdict.get("verdict") == "departs" and conf >= HOLD_BAND:
        if proj and _precision_low(proj):
            return "check"                    # crying wolf lately: stop stopping the work
        return "hold"
    if verdict.get("verdict") == "departs" and conf >= CHECK_BAND:
        return "check"
    return "silent"


def _precision_low(proj):
    rows = _answers(proj)[-5:]
    if len(rows) < 5:
        return False
    kept = sum(1 for r in rows if r.get("decision") != "accept")
    return (kept / len(rows)) < PRECISION_FLOOR


# ---------------------------------------------------------------- blocks and the queue
def _blocks(proj):
    return _read(proj, "blocks.json", [])


def enqueue(proj, flag):
    """Group by what was cited. Same label joins the open block; a new label opens one.

    `grounds` is preferences and requirements together, because a verification departure is now
    grounded in the requirement whose declared check cannot do its job -- there being no
    verification preference in the developer's own words to cite. Two agents breaking the same
    requirement is still one recommendation.
    """
    label = "+".join(sorted(flag.get("grounds") or flag.get("prefs") or ["?"]))
    blocks = _blocks(proj)
    for b in blocks:
        if b["label"] == label and b["status"] == "waiting":
            b["members"].append(flag)
            b["ts"] = min(b["ts"], flag["ts"])
            _write(proj, "blocks.json", blocks)
            return b
    b = dict(label=label, status="waiting", ts=flag["ts"], members=[flag])
    blocks.append(b)
    _write(proj, "blocks.json", blocks)
    return b


def mark_landed(proj, rid):
    """Its action happened: there is nothing left to steer, so it leaves the queue."""
    blocks = _blocks(proj)
    changed = False
    for b in blocks:
        keep = [m for m in b["members"] if m["rid"] != rid]
        if len(keep) != len(b["members"]):
            b["members"], changed = keep, True
    blocks = [b for b in blocks if b["members"] or b["status"] != "waiting"]
    if changed:
        _write(proj, "blocks.json", blocks)
    return changed


def mark_shown(proj, rid, at=None):
    """It reached the user, so the quiet window starts now.

    Both bands call this. A check pauses nothing, but it still spends the user's attention, and the
    600s window exists to ration attention rather than to ration pauses. Before the check band had
    an output channel this distinction could not arise, because only a hold was ever delivered.
    """
    st = _read(proj, "state.json", {})
    st["last_shown_ts"] = at or now()     # the replay passes the trajectory's own clock
    _write(proj, "state.json", st)
    blocks = _blocks(proj)
    for b in blocks:
        for m in b["members"]:
            if m["rid"] == rid:
                m["shown"] = True
                b["status"] = "shown"
    _write(proj, "blocks.json", blocks)


def _rank(b):
    """Which waiting block is worth the one channel. Lower sorts first.

    Order: the metric at risk, then whether a deterministic fact backs the item, then confidence,
    then arrival.

    The middle term is the one the evaluation forced. It used to be absent, so items tying on
    metric were ordered by confidence alone -- and confidence does not rank these decisions: on
    the clean recording the judge's confidence ordered (check, silent) pairs at an AUC of 0.086,
    worse than a coin flip. The consequence was mechanical and bad. Eight items reached the queue
    on that run, all tying on `tests`; the two that mattered were backed by a structural lookup
    and carried confidences of 0.55 and 0.78, so they sorted below five word-overlap items at
    0.78-0.82 and were still waiting when the run ended. Three false positives spent the channel
    and both true positives were suppressed by the quiet window and the queue they were sitting in.

    Whether a structural lookup fired is deterministic and, across both recordings, the only signal
    that tracked whether an item was worth showing: 2 of 2 right on the first trajectory against
    0 of 3 for word overlap, and both golden positives on the second. Ranking on it costs nothing
    and does not depend on the judge being calibrated, which it is not.
    """
    best = min((tmod.METRIC_RANK.get(m.get("metric"), 9) for m in b["members"]), default=9)
    structural = 0 if any(m.get("trigger") in STRUCTURAL for m in b["members"]) else 1
    conf = max((float(m.get("confidence") or 0) for m in b["members"]), default=0)
    return (best, structural, -conf, b["ts"])


def window_open(proj, at=None):
    """The quiet window runs from the last time the user's attention was spent.

    That used to mean the last answer, which was correct only while a hold was the sole thing ever
    delivered: a hold asks, so it is always answered, so answering and being shown were the same
    event. Now a check is delivered too and pauses nothing, so it is never answered -- keying the
    window on answers alone would leave it permanently open and let checks flood the terminal,
    which is the alert-fatigue failure the window exists to prevent.
    """
    st = _read(proj, "state.json", {})
    last = max(st.get("last_answer_ts", 0), st.get("last_shown_ts", 0))
    return (at or now()) - last >= WINDOW_S * 1000


def may_preempt(proj, flag, at=None):
    """The only thing allowed through a closed window."""
    if flag.get("trigger") != "declared_interface":
        return False
    if len(flag.get("dependents") or []) < 2:
        return False
    if flag.get("landed"):
        return False
    st = _read(proj, "state.json", {})
    return (at or now()) - st.get("last_preempt_ts", 0) >= PREEMPT_EVERY_S * 1000


def due(proj, at=None):
    """The one block to show now, or None. Re-checked before it is handed over."""
    at = at or now()
    blocks = [b for b in _blocks(proj) if b["status"] == "waiting" and b["members"]]
    if not blocks:
        return None
    blocks.sort(key=_rank)
    top = blocks[0]
    if window_open(proj, at):
        return top
    for b in blocks:
        if any(may_preempt(proj, m, at) for m in b["members"]):
            b["preempted"] = True
            return b
    return None


def consume_preempt(proj, at=None):
    """Spend the hourly preempt budget.

    due() is read-only on purpose: a status check or a viewer poll must not burn the one jump
    allowed per hour. Only the surface that actually interrupts the user calls this.
    """
    st = _read(proj, "state.json", {})
    st["last_preempt_ts"] = at or now()
    _write(proj, "state.json", st)


# ---------------------------------------------------------------- answers
def _answers(proj):
    p = os.path.join(ctl(proj), "answers.jsonl")
    try:
        return [json.loads(l) for l in open(p) if l.strip()]
    except Exception:
        return []


def answer(proj, label, decision, note="", rids=None):
    """Recorded per member, so one answer can cover a block or a single flag inside it."""
    blocks = _blocks(proj)
    target = next((b for b in blocks if b["label"] == label and b["status"] == "waiting"), None)
    if not target:
        return None
    members = [m for m in target["members"] if rids is None or m["rid"] in rids]
    p = os.path.join(ctl(proj), "answers.jsonl")
    with open(p, "a") as f:
        for m in members:
            f.write(json.dumps(dict(ts=now(), rid=m["rid"], label=label, decision=decision,
                                    note=note, prefs=m.get("prefs"),
                                    confidence=m.get("confidence"))) + "\n")
    rest = [m for m in target["members"] if m not in members]
    target["members"] = rest
    if not rest:
        target["status"] = "answered"
    _write(proj, "blocks.json", blocks)
    st = _read(proj, "state.json", {})
    st["last_answer_ts"] = now()
    _write(proj, "state.json", st)
    return members
