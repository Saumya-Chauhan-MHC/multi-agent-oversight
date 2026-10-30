#!/usr/bin/env python3
"""Two channels, one queue each, and the rules about when a developer is actually interrupted.

The SSOT separates these: a preference misalignment and a safety risk are not the same kind of
interruption and are not shown the same way. A preference flag asks the developer what they want
and can move the preference model. A safety flag reports a fact code already established and asks
only the narrow question the fact leaves open. They are kept apart here rather than ranked
together, so a run can be read as "this is what it asked me" and "this is what it caught".

Queue rules, from the SSOT:

  one at a time         a second flag does not interrupt; it waits
  QUIET_S after each    time for the run to move on, so a queued item can become irrelevant and
                        drop out instead of being asked
  DEPTH per channel     past that the oldest goes, because a question about work that has long
                        since landed is not worth the interruption
  combine same kind     flags of the same kind merge into one interruption that lists each
                        concrete request, so the developer digests one issue, not five copies

One exception, and it is the only one. A miscoordination flag raised *before* the interface
moves preempts the quiet window, because once every dependent has built on the old contract no
later answer repairs it. A miscoordination flag raised *after*, on a done claim, does not: that
one is already late and can wait its turn.
"""
import json, os, time

QUIET_S = int(os.environ.get("OV_QUIET_S", "600"))      # 10 minutes
DEPTH = int(os.environ.get("OV_QUEUE_DEPTH", "10"))
DIR = "control6"


def ctl(proj):
    d = os.path.join(proj, DIR)
    os.makedirs(d, exist_ok=True)
    return d


def _p(proj, name):
    return os.path.join(ctl(proj), name)


def _read(proj, name, default):
    try:
        return json.load(open(_p(proj, name)))
    except Exception:
        return default


def _write(proj, name, obj):
    with open(_p(proj, name), "w") as f:
        json.dump(obj, f, indent=1)


def _chan(finding):
    return "safety" if finding.get("kind") == "safety" else "preference"


def group_key(f):
    """What makes two flags "the same kind of request". Same risk, or same preference rule: the
    file each one touches is allowed to differ, and both are listed when it surfaces."""
    if f.get("kind") == "safety":
        return "risk:%s:%s" % (f.get("risk"), f.get("reason"))
    return "pref:%s" % (f.get("pid") or f.get("reason"))


def preempts(f):
    """The one thing allowed to break the quiet window."""
    return f.get("kind") == "safety" and f.get("risk") == "miscoordination" \
        and f.get("reason") == "declared_interface"


def enqueue(proj, finding):
    ch = _chan(finding)
    q = _read(proj, "queue_%s.json" % ch, [])
    k = group_key(finding)
    for item in q:
        if item["key"] == k:
            item["members"].append(finding)          # same kind: one interruption, both requests
            _write(proj, "queue_%s.json" % ch, q)
            return dict(queued=True, combined=True, key=k, depth=len(q))
    q.append(dict(key=k, at=time.time(), members=[finding]))
    dropped = []
    while len(q) > DEPTH:
        dropped.append(q.pop(0)["key"])              # oldest first: it is the most likely stale
    _write(proj, "queue_%s.json" % ch, q)
    return dict(queued=True, combined=False, key=k, depth=len(q), dropped=dropped)


def quiet_until(proj, ch):
    return _read(proj, "quiet.json", {}).get(ch, 0)


def remaining(proj, ch, now=None):
    """Seconds left in the quiet window. Shown rather than waited out: a demo that sat for the
    full ten minutes would prove the same thing and be unwatchable."""
    now = time.time() if now is None else now
    return max(0, int(quiet_until(proj, ch) - now))


def mark_shown(proj, ch):
    q = _read(proj, "quiet.json", {})
    q[ch] = time.time() + QUIET_S
    _write(proj, "quiet.json", q)


def next_to_show(proj, now=None):
    """The one thing to surface, or None. Safety is checked first: it is a fact, not a question.

    Inside a quiet window the whole queue is scanned for a preempting item, not just its head.
    Checking only the head meant a moving interface stayed buried behind two older flags and the
    one exception that exists never fired -- the queue silently turned it back into an ordinary
    item, which is exactly the outcome the exception is there to prevent.
    """
    now = time.time() if now is None else now
    for ch in ("safety", "preference"):
        q = _read(proj, "queue_%s.json" % ch, [])
        if not q:
            continue
        if now < quiet_until(proj, ch):
            urgent = next((i for i in q if any(preempts(m) for m in i["members"])), None)
            if urgent is None:
                continue
            return dict(channel=ch, **urgent)
        return dict(channel=ch, **q[0])
    return None


def pop(proj, ch, key):
    q = _read(proj, "queue_%s.json" % ch, [])
    q = [i for i in q if i["key"] != key]
    _write(proj, "queue_%s.json" % ch, q)


def depths(proj):
    return {ch: len(_read(proj, "queue_%s.json" % ch, [])) for ch in ("safety", "preference")}


def notice(item):
    """What the developer reads. The SSOT's six fields, in order, for both channels."""
    m = item["members"][0]
    L = []
    if item["channel"] == "safety":
        L.append("[oversight · safety] %s" % m["risk"].upper())
        L.append("  what happened:  %s  (%s)" % (m["reason"], m.get("detail")))
        L.append("  rule:           %s %s" % (m["category"], m["extends"]))
        L.append("  evidence:       %s" % _evidence(m))
        L.append("  cost if kept:   %s (%s)" % (m["costs"], m["metric"]))
        if m.get("ask"):
            L.append("  question:       %s" % m["ask"])
        else:
            # No permission question for this one: the fact is the whole finding.
            L.append("  correction:     %s" % (m.get("correction") or
                                               "announce the change before it lands"))
        L.append("  detector after: %s" % m["source"])
    else:
        L.append("[oversight · preference] %s" % (m.get("category") or ""))
        L.append("  action:         %s" % str(m.get("action", ""))[:100].replace("\n", " "))
        L.append("  preference:     %s" % m.get("rule", m.get("detail")))
        L.append("  evidence:       %s" % _evidence(m))
        L.append("  your call:      accept the flag, or reject it and say why")
    if len(item["members"]) > 1:
        L.append("  also, same kind:")
        for other in item["members"][1:]:
            L.append("    - %s" % (other.get("detail") or other.get("action")))
    return "\n".join(L)


def _evidence(m):
    if m.get("dependents"):
        return "%s already built on this: %s" % (len(m["dependents"]), ", ".join(m["dependents"]))
    if m.get("owner"):
        return "started by %s, not by the agent stopping it" % m["owner"]
    return str(m.get("detail") or "")
