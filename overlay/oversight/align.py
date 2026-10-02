#!/usr/bin/env python3
"""Shared plumbing for the alignment layer: node lookup, counters, notices, notes to an agent.

Deliberately thin and dependency-free. The hooks are short-lived processes on the agent's critical
path, so everything here is file IO and string work.
"""
import json, os, re, time

HERE = os.path.dirname(os.path.abspath(__file__))


def now_ms():
    return int(time.time() * 1000)


def ov(proj):
    return os.path.join(proj, "oversight")


def ctl(proj):
    return os.path.join(ov(proj), "control")


def clear(path):
    try:
        os.unlink(path)
    except OSError:
        pass


# ---------------------------------------------------------------------------- events and counters
def load_events(proj, limit=None):
    p = os.path.join(ov(proj), "events.jsonl")
    out = []
    try:
        with open(p) as f:
            for ln in f:
                try:
                    out.append(json.loads(ln))
                except Exception:
                    pass
    except OSError:
        return []
    return out[-limit:] if limit else out


def append_event(proj, ev):
    try:
        with open(os.path.join(ov(proj), "events.jsonl"), "a") as f:
            f.write(json.dumps(ev, default=str) + "\n")
    except OSError:
        pass


def counters(proj):
    try:
        return json.load(open(os.path.join(ctl(proj), "counters.json")))
    except Exception:
        return dict(flags_unanswered=0, checks_unanswered=0, repeat_flags=0,
                    last_look_ts=now_ms(), last_catchup_ts=0, seen_nodes=[])


def save_counters(proj, c):
    os.makedirs(ctl(proj), exist_ok=True)
    json.dump(c, open(os.path.join(ctl(proj), "counters.json"), "w"), indent=1)


def bump(proj, key, n=1):
    c = counters(proj)
    c[key] = c.get(key, 0) + n
    save_counters(proj, c)
    return c


def reset_look(proj, why="look"):
    """Any look resets both counts to zero (SSOT section 2)."""
    c = counters(proj)
    c.update(flags_unanswered=0, checks_unanswered=0, repeat_flags=0,
             last_look_ts=now_ms(), last_look_why=why)
    save_counters(proj, c)
    return c


def outdatedness(proj, settings=None):
    """How stale the user's picture is, and why. One implementation, three callers.

    Points (SSOT section 2): an unshown departure or unanswered check counts 1; either one citing a
    line the user already refused counts 2; file volume in places they have not opened counts 1 per
    `files_per_point`; a subagent that finished while they were away counts 1.
    """
    import json as _json
    c = counters(proj)
    per = int((settings or {}).get("files_per_point", 10) or 10)
    last = c.get("last_look_ts", 0)
    seen = set(c.get("seen_nodes") or [])
    # Claude Code emits subagent_stop for internal helpers we never saw spawn (26 stop events for 3
    # real children in one run), so only agents we watched START count as work the user missed.
    started = {e.get("agent_id") for e in load_events(proj) if e.get("ov_event") == "subagent_start"}
    files = 0
    done = set()
    for e in load_events(proj):
        if e.get("ov_ts", 0) <= last:
            continue
        if (e.get("ov_event") == "pre_tool" and e.get("tool_name") in ("Write", "Edit", "MultiEdit")
                and (e.get("agent_id") or "orchestrator") not in seen):
            files += 1
        if (e.get("ov_event") == "subagent_stop" and e.get("agent_id") in started
                and e["agent_id"] not in seen):
            done.add(e["agent_id"])
    finished = len(done)
    parts = dict(flags=c.get("flags_unanswered", 0), checks=c.get("checks_unanswered", 0),
                 repeats=c.get("repeat_flags", 0), unseen_files=files, finished=finished)
    total = (parts["flags"] + parts["checks"] + 2 * parts["repeats"]
             + files // per + finished)
    return total, parts


def credit_pause(proj, seconds):
    """Give time back to the session cap.

    Judge latency and time spent waiting for a human are the tool's overhead. Charging them to the
    agent's budget would make a tool-on run look slower than a tool-off one for no good reason.
    """
    try:
        seconds = int(float(seconds))
    except Exception:
        return
    if seconds <= 0:
        return
    no = 1
    try:
        no = int(open(os.path.join(ov(proj), "session_no.txt")).read().strip() or 1)
    except Exception:
        pass
    p = os.path.join(ov(proj), "paused_%d.txt" % no)
    try:
        total = int(open(p).read().strip() or 0) if os.path.exists(p) else 0
        open(p, "w").write(str(total + seconds))
    except OSError:
        pass


# ---------------------------------------------------------------------------- the work graph
def paths_in(text):
    """File paths a brief names. Good enough to group siblings; never used to decide a verdict."""
    if not text:
        return []
    hits = re.findall(r"[A-Za-z0-9_./-]+\.[A-Za-z0-9]{1,5}\b", text)
    out = []
    for h in hits:
        if h.startswith(("http", "www.")) or h.endswith((".md", ".txt")) and "/" not in h:
            continue
        if h not in out:
            out.append(h)
    return out[:20]


def brief_family(prompt):
    """What makes two children the same decision: the shape of the files they aim at.

    `Go lexer` writing lexers/go.py and `JSON lexer` writing lexers/json.py share a family; a
    formatter in another directory does not.
    """
    fam = sorted({(os.path.dirname(p) or ".") + "/*" + os.path.splitext(p)[1] for p in paths_in(prompt)})
    return fam or ["<no files named>"]


def nodes_from_events(proj):
    """Minimal node view: agent id -> label, parent, files written, status.

    The full DAG lives in the viewer; the hooks only need enough to describe the parent to the judge.
    """
    nodes = {}
    order = []
    pending_spawns = []          # a spawn names the child; subagent_start does not carry that name
    evs = load_events(proj)
    denied = {e.get("child") for e in evs
              if e.get("ov_event") == "intervention" and e.get("decision") == "no"}
    for e in evs:
        ev, aid = e.get("ov_event"), e.get("agent_id")
        if ev == "pre_tool" and e.get("tool_name") in ("Agent", "Task"):
            d = (e.get("tool_input") or {}).get("description")
            if d and d not in denied:          # a denied spawn never starts, so it names no node
                pending_spawns.append((d, aid or "orchestrator",
                                       (e.get("tool_input") or {}).get("prompt") or ""))
        elif ev == "subagent_start" and aid:
            label, parent, brief = (pending_spawns.pop(0) if pending_spawns
                                    else (e.get("agent_type") or aid[:10], "orchestrator", ""))
            nodes[aid] = dict(id=aid, label=label, parent=parent, brief=brief, writes=set(),
                              status="running")
            order.append(aid)
        elif ev == "subagent_stop" and aid in nodes:
            nodes[aid]["status"] = "done"
        elif ev == "session_end":
            for n in nodes.values():
                if n["id"] == "orchestrator":
                    n["status"] = "done"
        elif ev == "pre_tool" and e.get("tool_name") in ("Write", "Edit", "MultiEdit"):
            f = ((e.get("tool_input") or {}).get("file_path") or "")
            key = aid if aid in nodes else "orchestrator"
            nodes.setdefault(key, dict(id=key, label="orchestrator", parent=None,
                                       writes=set(), status="running"))
            if f:
                nodes[key]["writes"].add(f)
    nodes.setdefault("orchestrator", dict(id="orchestrator", label="orchestrator", parent=None,
                                          brief="", writes=set(), status="running"))
    if any(e.get("ov_event") == "session_end" for e in evs):
        nodes["orchestrator"]["status"] = "done"
    return nodes


def parent_status(proj, agent_id):
    """Who is spawning, and what the judge needs to know about them."""
    nodes = nodes_from_events(proj)
    key = agent_id if agent_id and agent_id in nodes else "orchestrator"
    n = nodes[key]
    kids = [x for x in nodes.values() if x.get("parent") == key]
    return key, dict(name=n["label"], brief=(n.get("brief") or "")[:1500],
                     files_written=len(n["writes"]),
                     children=len(kids),
                     running_children=sum(1 for k in kids if k["status"] == "running"),
                     plan_next=last_assistant_plan(proj, key))


def last_assistant_plan(proj, key, limit=300):
    """What the parent said it was about to do, if the recorder caught it."""
    for e in reversed(load_events(proj, limit=400)):
        if e.get("ov_event") in ("subagent_stop", "stop") and (e.get("agent_id") or "orchestrator") == key:
            return (e.get("last_assistant_message") or "")[:limit]
    return ""


# ---------------------------------------------------------------------------- decisions and answers
def answered_for(path, dkey):
    try:
        for ln in open(path):
            a = json.loads(ln)
            if a.get("dkey") == dkey:
                return a
    except Exception:
        pass
    return None


def lines_already_refused(path):
    """Lines the user has already said no to in this task.

    A later departure citing one of these counts double toward catch-up: the user has made their
    position on that line clear once, so a repeat they never see is worse than a fresh one.
    """
    out = set()
    try:
        for ln in open(path):
            a = json.loads(ln)
            if a.get("answer") == "no":
                out.update(a.get("lines") or [])
    except Exception:
        pass
    return out


def record_answer(path, a):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(a) + "\n")


def precision(path, window=10):
    """How often a hold turned out to be worth showing, over the last `window` answered holds.

    A hold the user declined counts as a hit; one they waved through counts as a false alarm. It is a
    proxy (a tired user accepts too), but it is the only in-session signal we have, and the alerting
    literature is clear that a flagger below roughly 0.70 is worse than none at all.
    """
    rows = []
    try:
        for ln in open(path):
            a = json.loads(ln)
            if a.get("answer") in ("no", "accept", "accept_all"):
                rows.append(a["answer"])
    except Exception:
        return None, 0
    rows = rows[-window:]
    if not rows:
        return None, 0
    hits = sum(1 for r in rows if r == "no")
    return hits / len(rows), len(rows)


def slot_free(slot):
    """One open question at a time. A slot whose owner is gone must not hold up the next question.

    The owner writes its pid: if the hook was killed (the user pressed esc, Claude Code timed it out),
    the file survives and every later hold would queue behind a question nobody is being asked. The
    age check stays as a backstop for a pid that got reused.
    """
    try:
        if time.time() - os.path.getmtime(slot) > 300:
            os.unlink(slot)
            return True
        parts = open(slot).read().split()
        if len(parts) > 1 and parts[1].isdigit():
            os.kill(int(parts[1]), 0)                 # raises if that process is gone
    except (OSError, ProcessLookupError):
        try:
            os.unlink(slot)
        except OSError:
            pass
        return True
    except ValueError:
        return True
    return False


def inbox_key(agent):
    """inbox.py keys the orchestrator's mailbox "main" and sanitises agent ids; match it exactly."""
    if not agent or agent in ("orchestrator", "main") or str(agent).startswith("main:"):
        return "main"
    return re.sub(r"[^\w.-]", "_", str(agent))


def send_to_agent(proj, agent, text):
    """A note delivered to one agent on its next tool call (inbox.py does the injecting).

    Every message carries an id: inbox.py records delivered ids, and without one it would re-inject
    the same note on every later tool call.
    """
    d = os.path.join(ctl(proj), "inbox")
    os.makedirs(d, exist_ok=True)
    mid = "n%d" % now_ms()
    with open(os.path.join(d, "%s.jsonl" % inbox_key(agent)), "a") as f:
        f.write(json.dumps(dict(id=mid, ts=now_ms(), text=text)) + "\n")
    return mid


def record_intervention(proj, caller, child, answer, note, jrec):
    rec = dict(ov_event="intervention", ov_ts=now_ms(), kind="spawn", initiated_by="agent",
               decided_by="human", target=caller, child=child, decision=answer, note=note,
               judgement={k: jrec.get(k) for k in ("verdict", "confidence", "band", "evidence", "rid")})
    append_event(proj, rec)
    os.makedirs(ctl(proj), exist_ok=True)
    with open(os.path.join(ctl(proj), "interventions.jsonl"), "a") as f:
        f.write(json.dumps(rec, default=str) + "\n")


# ---------------------------------------------------------------------------- what the user reads
def queue_notice(proj, text):
    """Park a line for the next hook that can actually show it.

    SubagentStop's systemMessage is never surfaced by Claude Code (PreToolUse and PostToolUse are;
    verified with a probe session on 2.1.287), so catch-up computed its line twice in a live run and
    the user never saw it. The hook that knows WHEN to speak is not the hook that CAN.
    """
    d = os.path.join(proj, "oversight", "control")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "notice_queue.jsonl"), "a") as f:
        f.write(json.dumps(dict(ts=now_ms(), text=text)) + "\n")


def take_notice(proj):
    """Pop every queued line, oldest first. Returns one string, or None."""
    q = os.path.join(proj, "oversight", "control", "notice_queue.jsonl")
    if not os.path.exists(q):
        return None
    try:
        with open(q) as f:
            rows = [json.loads(l) for l in f if l.strip()]
        os.remove(q)
    except Exception:
        return None
    return "\n\n".join(r["text"] for r in rows) or None


def notice_text(j, kind, caller):
    """The notice body (SSOT appendix A2 and A3), as plain text for the terminal."""
    L = ["oversight %s   %s -> \"%s\"" %
         ("paused a spawn" if kind == "hold" else "quick check", j.get("parent_label"), j.get("child")), ""]
    ev = j.get("evidence") or []
    if ev:
        for e in ev:
            L.append("  you said (%s)  %s" % (e.get("line_id"), str(e.get("said"))[:90]))
            L.append("  proposed       %s" % str(e.get("proposed"))[:90])
        L.append("  verdict        departs from %s   confidence %.2f" %
                 (", ".join(sorted({e.get("line_id") for e in ev})), j.get("confidence", 0)))
    else:
        L.append("  guess          %s (%.2f)" % (j.get("verdict"), j.get("confidence", 0)))
        L.append("  reason         nothing in your lines covers this%s" %
                 ("; nearest is %s" % j.get("precedent") if j.get("precedent") else ""))
    s = j.get("suggestion") or {}
    if s.get("note"):
        L.append("  suggestion     %s: %s" % (s.get("action"), str(s.get("note"))[:110]))
    if j.get("if_accepted"):
        L.append("  accept adds    \"%s\"" % str(j.get("if_accepted"))[:110])
    L.append("  dag            http://localhost:4173/?focus=%s" % caller)
    if kind == "hold":
        L.append("  stop asking for this parent:  python3 oversight/ctl.py accept-all %s" % caller)
    return "\n".join(L)
