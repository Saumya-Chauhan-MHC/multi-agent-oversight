#!/usr/bin/env python3
"""Deliver the other half of a repair to the agent whose checkout needs it.

A pre-action hook sees one action by one agent. When two isolated agents conflict, the repair has
two halves and the hook is standing in front of only one of them. Telling the acting agent to
"also update the other agent's call sites" does not work: it is in its own git worktree and cannot
write into anyone else's. Five treatment arms cut interference roughly in half and never got past
1 of 12 on both-tasks-done, and this is why. The correction was always true and was always
delivered to whoever happened to act second, which is not the same as whoever's checkout is wrong.

So the correction is routed instead of broadcast. The judge returns `other_fix`, the half that only
the other agent's checkout can take, and it goes to that agent's inbox, which inbox.py injects on
its next tool call. If that agent has already stopped, nobody is left to receive it, and it falls
back to the orchestrator, which can still write into both worktrees while the session is open.

Nothing here invents a fact. Every message is the judge's own sentence about the other agent's own
code, sent to the one party able to act on it.
"""
import os
from .. import align


def running(events, agent):
    """True if this subagent has started and not yet stopped.

    Claude Code emits stop events for internal helpers that were never seen to start, so a stop is
    only believed for an agent whose start was recorded.
    """
    started = stopped = False
    for e in events:
        if (e.get("agent_id") or "") != agent:
            continue
        ev = e.get("ov_event")
        if ev == "subagent_start":
            started = True
        elif ev == "subagent_stop":
            stopped = True
    return started and not stopped


def _msg(text, acting, where):
    """`where` is the recipient's own file, not the other agent's: it is the path the recipient
    wrote, which is how the two were matched up in the first place. Labelling it "theirs" sent the
    agent looking for a checkout it cannot open."""
    lines = ["Another agent is working on the same file as you, in a separate checkout, and has "
             "just changed it. You cannot see their work and they cannot see yours.",
             "", "What you need to do in your own checkout:", "  " + text]
    if where:
        lines += ["", "The file to change is the one you already wrote: " + where]
    lines += ["", "This is a fact about the other checkout, not a review of your work. Make the "
                  "change and carry on with your own task."]
    return "\n".join(lines)


def send(proj, verdict, trigger, acting, rid):
    """Route the judge's `other_fix` to the checkouts that need it. Returns the recipients."""
    text = (verdict or {}).get("other_fix") or ""
    others = (trigger or {}).get("others") or {}
    if not text.strip() or not others:
        return []
    events = align.load_events(proj)
    where = ""
    for edits in others.values():
        for ed in edits:
            if ed.get("where"):
                where = ed["where"]
    sent = []
    for who in others:
        if who in ("orchestrator", "main") or not running(events, who):
            continue
        align.send_to_agent(proj, who, _msg(text, acting, where), kind="relay")
        sent.append(who)
    if not sent:
        # Everyone who could act on this has finished. The orchestrator is the only party still
        # able to write into their worktrees, and only while the session is open.
        align.send_to_agent(proj, "orchestrator", _msg(text, acting, where), kind="relay")
        sent.append("orchestrator")
    align.append_event(proj, dict(ov_event="v4_relay", rid=rid, acting=acting,
                                  to=sent, other_fix=text[:300], where=where))
    return sent
