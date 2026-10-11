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
def cache_key(action_text, rules_sig):
    return hashlib.sha256((action_text + "|" + rules_sig).encode()).hexdigest()[:16]


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
def band(verdict, proj=None):
    if verdict.get("source") == "unavailable":
        return "silent"
    if verdict.get("verdict") == "departs" and not verdict.get("metric"):
        return "silent"                       # the gate: a breach with nothing at stake
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
    """Group by the preference cited. Same label joins the open block; a new label opens one."""
    label = "+".join(sorted(flag.get("prefs") or ["?"]))
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


def _rank(b):
    best = min((tmod.METRIC_RANK.get(m.get("metric"), 9) for m in b["members"]), default=9)
    conf = max((float(m.get("confidence") or 0) for m in b["members"]), default=0)
    return (best, -conf, b["ts"])


def window_open(proj, at=None):
    st = _read(proj, "state.json", {})
    last = st.get("last_answer_ts", 0)
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
