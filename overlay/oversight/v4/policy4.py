#!/usr/bin/env python3
"""Hold or silence. Nothing in between, and no number decides it.

v3 had three bands and a queue that rationed a scarce attention channel between them. Most of that
machinery existed to manage the middle band: a notice that paused nothing, which meant it had to be
ranked, grouped, quieted and precision-floored so it did not become a feed.

With only holds left, almost all of it goes. A hold pauses the tool call, so the run serialises
itself -- a second hold cannot arrive while the developer is answering the first. What remains is
the one thing that genuinely stops repetition: once the developer has answered about a rule, that
answer stands for the rest of the run and the same rule never asks twice.
"""
import json, os, time

CTL = "control4"


def ctl(proj):
    d = os.path.join(proj, CTL)
    os.makedirs(d, exist_ok=True)
    return d


def now():
    return time.time()


def _read(proj, name, default):
    try:
        with open(os.path.join(ctl(proj), name)) as f:
            return json.load(f)
    except Exception:
        return default


def _write(proj, name, obj):
    p = os.path.join(ctl(proj), name)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f)
    os.replace(tmp, p)


# ------------------------------------------------------------------ the cache
def cache_key(action_text, rules_sig, agent=""):
    import hashlib
    return hashlib.sha1(("%s|%s|%s" % (rules_sig, agent, action_text)).encode()).hexdigest()


def cache_get(proj, key):
    return _read(proj, "judged.json", {}).get(key)


def cache_put(proj, key, verdict):
    c = _read(proj, "judged.json", {})
    c[key] = verdict
    _write(proj, "judged.json", c)


# ------------------------------------------------------------------ the one decision
def decide(verdict, proj=None):
    """hold if a rule is broken, silent otherwise. That is the whole policy.

    `source` matters: a judge that timed out or returned nonsense reports breaks=False already,
    but being explicit here keeps the fail-open path visible to anyone reading this function.
    """
    if verdict.get("source") in ("unavailable", "invalid-citation"):
        return "silent"
    return "hold" if verdict.get("breaks") else "silent"


# ------------------------------------------------------------------ asking once per rule
def answer_for(proj, rule_id):
    """What the developer already said about this rule, or None if they have not been asked."""
    return _read(proj, "answers.json", {}).get(rule_id)


def record_answer(proj, rule_id, decision, note=""):
    a = _read(proj, "answers.json", {})
    a[rule_id] = dict(decision=decision, note=note, ts=now())
    _write(proj, "answers.json", a)
    return a[rule_id]


def asked(proj):
    return _read(proj, "answers.json", {})
