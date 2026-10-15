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
    return "x:" + hashlib.sha1(((verdict or {}).get("other_fix") or "")[:80].encode()).hexdigest()[:10]


def cache_key(action_text, task_sig, agent=""):
    raw = "%s|%s|%s" % (task_sig, agent, action_text)
    return hashlib.sha1(raw.encode()).hexdigest()


def cache_get(proj, key):
    return _read(proj, "judged.json", {}).get(key)


def cache_put(proj, key, verdict):
    c = _read(proj, "judged.json", {})
    c[key] = verdict
    _write(proj, "judged.json", c)


def decide(verdict):
    """Two bands. The middle one is gone: it was a notice nobody had to act on, and the
    confidence number that chose between bands carried no band information."""
    return "hold" if (verdict or {}).get("breaks") else "silent"


def answer_for(proj, tp):
    return _read(proj, "answers.json", {}).get(tp)


def record_answer(proj, tp, decision, note=""):
    a = _read(proj, "answers.json", {})
    a[tp] = dict(decision=decision, note=note, ts=time.time())
    _write(proj, "answers.json", a)


def asked(proj):
    return _read(proj, "answers.json", {})
