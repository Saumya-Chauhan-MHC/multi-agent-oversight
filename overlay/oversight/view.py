#!/usr/bin/env python3
"""What the viewer shows: the work so far, each node's mark, and the catch-up items.

Built by template from what the gate already stored (SSOT appendix B4): no new model call is made
here, ever. A caption is assembled from the judgement that was recorded at the time, so the viewer
cannot say anything the judge did not say.
"""
import json, os, glob, time

import align, memory


def _judgements(proj):
    out = []
    for p in sorted(glob.glob(os.path.join(align.ov(proj), "judgements", "*.json"))):
        if os.sep + "cache" + os.sep in p:
            continue
        try:
            out.append(json.load(open(p)))
        except Exception:
            pass
    out.sort(key=lambda j: j.get("ts", 0))
    return out


def _answers(proj):
    out = {}
    p = os.path.join(align.ctl(proj), "answered.jsonl")
    try:
        for ln in open(p):
            a = json.loads(ln)
            out[a.get("dkey")] = a
    except Exception:
        pass
    return out


def nodes(proj):
    """Orchestrator plus every subagent, with what it wrote and whether it is still running."""
    ns = align.nodes_from_events(proj)
    evs = align.load_events(proj)
    starts = {}
    for e in evs:
        if e.get("ov_event") == "subagent_start" and e.get("agent_id"):
            starts[e["agent_id"]] = e.get("ov_ts", 0)
    out = []
    for k, n in ns.items():
        out.append(dict(id=k, label=n["label"], parent=n.get("parent"), status=n["status"],
                        writes=sorted(n["writes"]), started=starts.get(k, 0)))
    out.sort(key=lambda n: (n["id"] != "orchestrator", n["started"]))
    return out


def state(proj):
    """Everything the page needs in one request."""
    c = align.counters(proj)
    st = memory.settings()
    last_look = c.get("last_look_ts", 0)
    seen = set(c.get("seen_nodes") or [])
    js = _judgements(proj)
    answers = _answers(proj)
    ns = nodes(proj)
    # a spawn whose request file is still in control/pending is BLOCKED on the user right now; that
    # is a different state from "things piled up while you were away" and must not share a heading
    waiting_rids = {os.path.basename(p)[:-5]
                    for p in glob.glob(os.path.join(align.ctl(proj), "pending", "*.json"))}
    # In single-terminal mode the question belongs to Claude Code, so we never see the answer
    # directly. A subagent starting after we asked IS the answer, so the item resolves itself
    # instead of claiming forever that the agent is paused.
    # One subagent start answers ONE ask, oldest first. Clearing every ask on any start was wrong:
    # in a burst, one allowed spawn wiped the record of the others still waiting.
    starts = sorted(e.get("ov_ts", 0) for e in align.load_events(proj)
                    if e.get("ov_event") == "subagent_start")
    asks = []
    for p in sorted(glob.glob(os.path.join(align.ctl(proj), "asked", "*.json"))):
        try:
            asks.append((json.load(open(p)), p))
        except Exception:
            pass
    asks.sort(key=lambda x: x[0].get("ts", 0))
    used = 0
    for a, path in asks:
        later = [t for t in starts[used:] if t > a.get("ts", 0)]
        if later:
            used = starts.index(later[0]) + 1
            os.remove(path)                   # this one was allowed and ran
        else:
            waiting_rids.add(a.get("rid"))

    # one mark per node, from the judgement that let it start
    mark_by_child = {}
    for j in js:
        mark_by_child[(j.get("caller"), j.get("child"))] = j
    for n in ns:
        j = None
        for (caller, child), rec in mark_by_child.items():
            if child and n["label"] and child.strip().lower() == n["label"].strip().lower():
                j = rec
                break
        n["mark"] = ("departs" if j and j.get("band") == "hold" else
                     "guess" if j and j.get("band") == "check" else
                     "fits" if j else "")
        n["judgement"] = j and dict(verdict=j.get("verdict"), confidence=j.get("confidence"),
                                    band=j.get("band"), rid=j.get("rid"))
        n["seen"] = n["id"] in seen
        n["shares_with"] = sorted({o["label"] for o in ns if o["id"] != n["id"]
                                   and set(o["writes"]) & set(n["writes"])})
        n["new_since_look"] = n.get("started", 0) > last_look

    # the items, ordered as B4 asks: lines already said no to, then other flags, then checks,
    # then unseen volume, then finished nodes
    said_no_lines = set()
    for a in answers.values():
        if a.get("answer") == "no":
            said_no_lines.update(a.get("lines") or [])
    items = []
    for j in js:
        a = answers.get(j.get("dkey"))
        if a:
            continue                                   # already answered: not an item
        lines = sorted({e.get("line_id") for e in (j.get("evidence") or []) if e.get("line_id")})
        if j.get("band") == "hold":
            blocked = j.get("rid") in waiting_rids
            why = ("The agent is waiting on your answer in the terminal." if blocked else
                   "Not shown (your q4 = never)" if st.get("involvement") == "never" else
                   "This departed from what you said, and you have not answered it.")
            kind, rank = ("waiting" if blocked else "flag"), (-1 if blocked else
                          0 if (said_no_lines & set(lines)) else 1)
        elif j.get("band") == "check":
            why = "Check you did not answer; the tool went with its guess"
            kind, rank = "check", 2
        else:
            continue
        ev = (j.get("evidence") or [{}])[0]
        items.append(dict(
            kind=kind, rank=rank, rid=j.get("rid"), dkey=j.get("dkey"), caller=j.get("caller"),
            title="%s -> %s%s" % (j.get("parent_label"), j.get("child"),
                                  (": departs from %s" % ", ".join(lines)) if lines else ""),
            caption="%s%s %s%s" % (
                (str(ev.get("proposed")) + ". ") if ev.get("proposed") else "",
                ('You said (%s): "%s".' % (ev.get("line_id"), ev.get("said"))) if ev.get("said")
                else "Nothing in your lines covers this.",
                # the judge's own reason for the call, which is what tells the user HOW it conflicts
                ((" Why: " + str((j.get("suggestion") or {}).get("note"))[:220] + ".")
                 if (j.get("suggestion") or {}).get("note") else ""),
                " " + why),
            if_accepted=j.get("if_accepted"), lines=lines,
            confidence=j.get("confidence"), ts=j.get("ts")))

    unseen_writes = 0
    per_node = {}
    for e in align.load_events(proj):
        if e.get("ov_event") != "pre_tool" or e.get("tool_name") not in ("Write", "Edit", "MultiEdit"):
            continue
        if e.get("ov_ts", 0) <= last_look:
            continue
        who = e.get("agent_id") or "orchestrator"
        if who in seen:
            continue
        per_node[who] = per_node.get(who, 0) + 1
        unseen_writes += 1
    for who, n in sorted(per_node.items(), key=lambda kv: -kv[1]):
        if n < 5:
            continue
        label = next((x["label"] for x in ns if x["id"] == who), who)
        items.append(dict(kind="unseen", rank=3, caller=who,
                          title="%s: %d files written since your last look" % (label, n),
                          caption="You have not opened this node. Click it to open it.", lines=[]))
    owners = {}
    for n in ns:
        for f in n["writes"]:
            owners.setdefault(f, []).append(n["label"])
    pairs = {}
    for f, who in owners.items():
        if len(who) > 1:
            pairs.setdefault(" and ".join(sorted(set(who))[:2]), []).append(os.path.basename(f))
    for whos, fs in pairs.items():
        items.append(dict(kind="overlap", rank=3, caller=None,
                          title="%s both wrote %d file%s" % (whos, len(fs), "" if len(fs) == 1 else "s"),
                          caption="Shared files: %s. Two subagents writing one file is where parallel "
                                  "work collides." % ", ".join(sorted(fs)[:6]), lines=[]))
    for n in ns:
        if n["status"] == "done" and n.get("started", 0) > last_look:
            items.append(dict(kind="finished", rank=4, caller=n["id"],
                              title="%s finished" % n["label"],
                              caption="%d files written." % len(n["writes"]), lines=[]))
    items.sort(key=lambda i: (i["rank"], -(i.get("ts") or 0)))

    total, parts = align.outdatedness(proj, st)
    return dict(
        waiting=sum(1 for i in items if i["kind"] == "waiting"),
        lines=[dict(id=m["id"], text=m["text"], source=m.get("source"), status=m.get("status"))
               for m in memory.load()],
        settings=dict(involvement=st.get("involvement"), threshold=st.get("catchup_threshold"),
                      surface=st.get("surface_mode", "ask")),
        nodes=ns, items=items,
        counters=dict(flags=parts["flags"], checks=parts["checks"], repeats=parts["repeats"],
                      unseen_files=parts["unseen_files"], finished=parts["finished"], total=total,
                      threshold=st.get("catchup_threshold", 5),
                      minutes_since_look=int((align.now_ms() - last_look) / 60000) if last_look else 0),
        judgements=[dict(rid=j.get("rid"), band=j.get("band"), verdict=j.get("verdict"),
                         confidence=j.get("confidence"), parent=j.get("parent_label"),
                         child=j.get("child"), ts=j.get("ts"),
                         lines=sorted({e.get("line_id") for e in (j.get("evidence") or [])}))
                    for j in js],
        now=align.now_ms())


def mark_looked(proj, node=None):
    """Opening a node counts as a look: it resets the counters, as the SSOT asks."""
    c = align.counters(proj)
    seen = set(c.get("seen_nodes") or [])
    if node:
        seen.add(node)
    c["seen_nodes"] = sorted(seen)
    align.save_counters(proj, c)
    align.reset_look(proj, "opened %s" % (node or "the graph"))
    return align.counters(proj)


def answer_item(proj, rid, dkey, answer, note="", lines=None, if_accepted=None, caller=None):
    """accept / no from the catch-up panel. Same consequences as answering in the terminal."""
    lines = lines or []
    align.record_answer(os.path.join(align.ctl(proj), "answered.jsonl"),
                        dict(dkey=dkey, rid=rid, answer=answer, note=note, lines=lines,
                             ts=align.now_ms()))
    if answer == "accept" and if_accepted:
        memory.append_answer(if_accepted, lines, source="answer (accept, catch-up)", rid=rid)
    if answer == "no":
        text = note or "do not do this again"
        memory.append_answer(text, lines, source="answer (no, catch-up)", rid=rid)
        if caller:
            align.send_to_agent(proj, caller, "[oversight] The user looked back at your work: %s" % text)
    align.record_intervention(proj, caller or "orchestrator", rid, answer, note,
                              dict(rid=rid, verdict="", confidence=0, band="catchup", evidence=[]))
    align.reset_look(proj, "answered from catch-up")
    return state(proj)
