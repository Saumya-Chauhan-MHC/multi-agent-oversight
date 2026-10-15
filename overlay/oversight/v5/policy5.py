#!/usr/bin/env python3
"""Hold or stay quiet, and remember what the developer already said.

There is no rule file to key an answer on, so an answer is keyed on the sentence of the task
description the judge quoted. Answering once about a sentence settles it for the rest of the run:
an agent retrying the same thing five times costs one interruption, not five.
"""
import hashlib, json, os, time

DIR = "control5"


def ctl(proj):
    d = os.path.join(proj, DIR)
    os.makedirs(d, exist_ok=True)
    return d


def now():
    return time.strftime("%F %T")


def _read(proj, name, default):
    try:
        return json.load(open(os.path.join(ctl(proj), name)))
    except Exception:
        return default


def _write(proj, name, obj):
    with open(os.path.join(ctl(proj), name), "w") as f:
        json.dump(obj, f, indent=1)


def topic(verdict):
    """What an answer is about. The quoted sentence when there is one, otherwise the pair of
    agents in conflict, because a cross-agent clash has no sentence behind it."""
    said = (verdict or {}).get("said") or ""
    if said.strip():
        return "q:" + hashlib.sha1(" ".join(said.split()).lower().encode()).hexdigest()[:10]
    # A hold below a yes can carry neither a sentence nor a clash; key it on what the action does,
    # so unrelated holds of that kind do not share one remembered answer.
    v = verdict or {}
    return "x:" + hashlib.sha1((v.get("other_fix") or v.get("does") or "")[:80].encode()).hexdigest()[:10]


def cache_key(action_text, task_sig, agent=""):
    raw = "%s|%s|%s" % (task_sig, agent, action_text)
    return hashlib.sha1(raw.encode()).hexdigest()


def cache_get(proj, key):
    return _read(proj, "judged.json", {}).get(key)


def cache_put(proj, key, verdict):
    c = _read(proj, "judged.json", {})
    c[key] = verdict
    _write(proj, "judged.json", c)


THRESHOLD = 0.3          # hold when p_violation is at least this (low: recall first)


def threshold(proj=None):
    """OV_THRESHOLD, else "threshold" in control5/settings.json, else THRESHOLD."""
    for raw in (os.environ.get("OV_THRESHOLD"),
                (_read(proj, "settings.json", {}) or {}).get("threshold") if proj else None):
        try:
            if raw is not None:
                return max(0.0, min(1.0, float(raw)))
        except (TypeError, ValueError):
            pass
    return THRESHOLD


def score(verdict):
    """The judge's p_violation. A verdict without one scores as its yes/no did."""
    v = verdict or {}
    p = v.get("p")
    return float(p) if isinstance(p, (int, float)) else (1.0 if v.get("breaks") else 0.0)


def decide(verdict, thr=THRESHOLD):
    """Two bands, chosen by one threshold on the judge's p_violation. A judge that could not
    answer, or quoted a line the task does not contain, stays silent as before."""
    v = verdict or {}
    if v.get("source") in ("unavailable", "invalid-quote"):
        return "silent"
    return "hold" if score(v) >= thr else "silent"


def answer_for(proj, tp):
    return _read(proj, "answers.json", {}).get(tp)


def record_answer(proj, tp, decision, note=""):
    a = _read(proj, "answers.json", {})
    a[tp] = dict(decision=decision, note=note, ts=time.time())
    _write(proj, "answers.json", a)


def asked(proj):
    return _read(proj, "answers.json", {})
