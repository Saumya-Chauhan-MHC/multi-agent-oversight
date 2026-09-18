#!/usr/bin/env python3
"""Human interventions for the oversight tool.

Four operations, shared by the terminal (oversight/ctl.py) and the viewer (serve.py), so both
paths write the same record:

  split gate     the agent proposes spawning a subagent; the gate hook pauses it until a human
                 accepts, asks for changes, rejects, or resets (.claude/hooks/gate.py)
  reset          restore every workspace file to its state at a checkpoint; forks a branch
  edit + rerun   revert one node's output and rerun it with an edited brief; forks a branch
  instruction    deliver a message to a running node on its next tool call; does not fork

Every mutating operation is previewed first (what it undoes or touches) and applied only on
confirm. Each writes the same fields: who initiated, kind, impact shown, decision, checkpoint
before and after. Resets back up the files they overwrite, so a reset can itself be undone.
"""
import json, os, re, time, shutil, subprocess, collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OV = os.path.join(ROOT, "oversight")
CTL = os.path.join(OV, "control")
PENDING, DECISIONS = os.path.join(CTL, "pending"), os.path.join(CTL, "decisions")
INBOX, BACKUPS = os.path.join(CTL, "inbox"), os.path.join(CTL, "backups")
STORE = os.path.join(OV, "snap", "store")
WRITE = ("Write", "Edit", "MultiEdit")
SKIP = {".git", "oversight", ".claude", "node_modules", "__pycache__", ".venv", "venv", "target", ".cache"}
STALE_MS = 20 * 60 * 1000          # a session with no events for this long is not "running"

for d in (PENDING, DECISIONS, INBOX, BACKUPS):
    os.makedirs(d, exist_ok=True)


# ---------------------------------------------------------------- events and nodes ----------
def now_ms():
    return int(time.time() * 1000)


KNOWN_ROOTS = {ROOT}   # plus every cwd the log recorded, so archived or moved runs still resolve


def load_events():
    p = os.path.join(OV, "events.jsonl")
    evs = []
    if os.path.exists(p):
        for ln in open(p, errors="ignore"):
            ln = ln.strip()
            if ln:
                try:
                    evs.append(json.loads(ln))
                except Exception:
                    pass
    evs.sort(key=lambda e: e.get("ov_ts", 0))
    KNOWN_ROOTS.update(e["cwd"].rstrip("/") for e in evs if isinstance(e.get("cwd"), str) and e["cwd"])
    return evs


def rel(p):
    if not p:
        return p
    if os.path.isabs(p):
        for r in sorted(KNOWN_ROOTS, key=len, reverse=True):
            if p.startswith(r + os.sep):
                return os.path.relpath(p, r)
        return p
    return p


def in_ws(p):
    return bool(p) and not os.path.isabs(p) and not p.startswith("..") and p.split("/")[0] not in SKIP


def build(evs=None):
    """Nodes keyed uniquely (Claude Code can reuse an agent id), with parent, status, writes, reads."""
    evs = load_events() if evs is None else evs
    nodes, live, pend = {}, {}, collections.defaultdict(list)
    ended = set()
    for e in evs:
        s = e.get("ov_session_no", 1)
        mk = f"main:{s}"
        if mk not in nodes:
            nodes[mk] = dict(key=mk, main=True, session=s, intent="orchestrator", prompt="",
                             parent=None, start=e.get("ov_ts"), stop=None, agent_id=None,
                             writes=set(), reads=set())
        ev = e.get("ov_event")
        if ev == "session_end":
            ended.add(s)
        if ev == "pre_tool" and e.get("tool_name") in ("Agent", "Task"):
            pend[s].append((e, live.get(e.get("agent_id")) or mk))
        if ev == "subagent_start" and e.get("ov_subagent_real", True) and e.get("agent_type"):
            aid = e.get("agent_id")
            key = aid
            if key in nodes:
                i = 2
                while f"{aid}#{i}" in nodes:
                    i += 1
                key = f"{aid}#{i}"
            live[aid] = key
            sp, caller = pend[s].pop(0) if pend[s] else ({}, mk)
            ti = sp.get("tool_input") or {}
            nodes[key] = dict(key=key, main=False, session=s, agent_id=aid,
                              intent=ti.get("description") or e.get("agent_type"),
                              prompt=ti.get("prompt") or "", spawn_ts=sp.get("ov_ts"),
                              parent=caller, start=e.get("ov_ts"), stop=None,
                              writes=set(), reads=set())
        if ev == "subagent_stop" and e.get("ov_subagent_real", True):
            k = live.get(e.get("agent_id"))
            if k in nodes:
                nodes[k]["stop"] = e.get("ov_ts")
        k = live.get(e.get("agent_id")) if e.get("agent_id") else mk
        n = nodes.get(k) or nodes[mk]
        ti = e.get("tool_input") or {}
        if ev == "pre_tool" and e.get("tool_name") in WRITE and ti.get("file_path"):
            f = rel(ti["file_path"])
            if in_ws(f):
                n["writes"].add(f)
        if ev == "pre_tool" and e.get("tool_name") in ("Read", "Glob", "Grep") and ti.get("file_path"):
            f = rel(ti["file_path"])
            if in_ws(f):
                n["reads"].add(f)
        if not e.get("ov_bash_writes_ambiguous"):
            n["writes"] |= {f for f in (e.get("ov_bash_writes") or []) if in_ws(f)}
        n["reads"] |= {f for f in (e.get("ov_bash_reads") or []) if in_ws(f)}
    for n in nodes.values():
        n["status"] = ("done" if n["stop"] else ("cut off" if n["session"] in ended else "running")) \
            if not n["main"] else ("ended" if n["session"] in ended else "running")
    return nodes, live


def node_of(e, live):
    s = e.get("ov_session_no", 1)
    return (live.get(e.get("agent_id")) if e.get("agent_id") else None) or f"main:{s}"


def label(nodes, k):
    n = nodes.get(k)
    if not n:
        return k
    return "orchestrator" if n["main"] else f"{n['intent']} ({n['key'][:10]})"


def find_node(nodes, ref):
    """Accept a node key, an id prefix, 'orchestrator', or a case-insensitive intent substring."""
    if ref in nodes:
        return ref
    if ref in ("orchestrator", "main"):
        mains = sorted((k for k in nodes if k.startswith("main:")), key=lambda k: nodes[k]["session"])
        return mains[-1] if mains else None
    hits = [k for k in nodes if k.startswith(ref)]
    if len(hits) == 1:
        return hits[0]
    hits = [k for k in nodes if not nodes[k]["main"] and ref.lower() in (nodes[k]["intent"] or "").lower()]
    return hits[0] if len(hits) == 1 else None


# ---------------------------------------------------------------- run state -----------------
def run_state(evs=None):
    evs = load_events() if evs is None else evs
    if not evs:
        return dict(session=0, active=False, paused=bool(pending()), last_event_age_s=None)
    starts = [e for e in evs if e.get("ov_event") == "session_start"]
    s = max((e.get("ov_session_no", 1) for e in starts), default=1)
    ended = any(e.get("ov_event") == "session_end" and e.get("ov_session_no") == s for e in evs)
    age = (now_ms() - evs[-1]["ov_ts"]) / 1000
    active = (not ended) and age * 1000 < STALE_MS
    return dict(session=s, active=active, paused=bool(pending()), last_event_age_s=round(age))


# ---------------------------------------------------------------- checkpoints ---------------
def checkpoints(evs=None):
    """Per-file checkpoints (cNNN) plus workspace checkpoints (wNNN) written at interventions."""
    evs = load_events() if evs is None else evs
    out = []
    p = os.path.join(OV, "checkpoints.txt")
    ts_of = {}
    for e in evs:
        for c in [e.get("ov_checkpoint")] + list(e.get("ov_checkpoint_bash") or []):
            if c and c not in ts_of:
                ts_of[c] = e["ov_ts"]
    if os.path.exists(p):
        for ln in open(p):
            parts = ln.split()
            if len(parts) >= 3:
                kv = dict(x.split("=", 1) for x in parts[3:] if "=" in x)
                out.append(dict(id=parts[0], file=rel(parts[1]), agent=kv.get("agent", "main"),
                                ts=ts_of.get(parts[0]), kind="file"))
    wp = os.path.join(CTL, "wcp.jsonl")
    if os.path.exists(wp):
        for ln in open(wp):
            try:
                w = json.loads(ln)
                out.append(dict(id=w["id"], file=None, agent="human", ts=w["ts"], kind="workspace",
                                label=w.get("label")))
            except Exception:
                pass
    out.sort(key=lambda c: c["ts"] or 0)
    return out


def new_wcp(label_):
    wp = os.path.join(CTL, "wcp.jsonl")
    n = sum(1 for _ in open(wp)) + 1 if os.path.exists(wp) else 1
    w = dict(id=f"w{n:03d}", ts=now_ms(), label=label_)
    with open(wp, "a") as f:
        f.write(json.dumps(w) + "\n")
    return w["id"]


def latest_checkpoint(evs=None):
    cps = checkpoints(evs)
    return cps[-1]["id"] if cps else None


def resolve(target, evs=None):
    """Checkpoint id, workspace checkpoint, 'node:<ref>' (just before that node started), or
    t<seconds> into the current session. Returns (ts_ms, description)."""
    evs = load_events() if evs is None else evs
    for c in checkpoints(evs):
        if c["id"] == target and c["ts"]:
            return c["ts"], f"checkpoint {target}"
    if target.startswith("node:"):
        nodes, _ = build(evs)
        k = find_node(nodes, target[5:])
        if k and nodes[k].get("spawn_ts"):
            return nodes[k]["spawn_ts"], f"before {label(nodes, k)} was spawned"
    m = re.match(r"t\+?(\d+)s?$", target)
    if m:
        st = run_state(evs)["session"]
        s0 = min((e["ov_ts"] for e in evs if e.get("ov_session_no") == st), default=now_ms())
        return s0 + int(m.group(1)) * 1000, f"t+{m.group(1)}s in session {st}"
    raise ValueError(f"unknown checkpoint or target: {target}")


# ---------------------------------------------------------------- change log and plans ------
def changes(evs=None):
    """Every recorded file change, with the file's state immediately before it."""
    evs = load_events() if evs is None else evs
    _, live = build(evs)
    out = []
    for e in evs:
        ts, ev = e["ov_ts"], e.get("ov_event")
        nk = node_of(e, live)
        if ev == "pre_tool" and e.get("ov_before_tool"):
            for f, d in e["ov_before_tool"].items():
                if in_ws(f):
                    out.append(dict(ts=ts, file=f, node=nk, before=("digest", d) if d else ("absent",)))
        elif ev == "pre_tool" and e.get("tool_name") in WRITE and e.get("ov_checkpoint"):
            f = rel((e.get("tool_input") or {}).get("file_path"))       # logs from before ov_before_tool
            if in_ws(f):
                snap = os.path.join(OV, "snap", f"{e['ov_checkpoint']}__{os.path.basename(f)}")
                out.append(dict(ts=ts, file=f, node=nk, before=("snap", snap) if os.path.exists(snap) else ("absent",)))
        if ev == "post_tool" and e.get("tool_name") == "Bash":
            files = set(e.get("ov_bash_writes") or []) | set(e.get("ov_bash_writes_dropped") or [])
            bf, cr, un = e.get("ov_before") or {}, set(e.get("ov_created") or []), set(e.get("ov_unrestorable") or [])
            new_fmt = "ov_created" in e or "ov_unrestorable" in e
            for f in files:
                if not in_ws(f):
                    continue
                if f in bf:
                    b = ("digest", bf[f])
                elif f in cr:
                    b = ("absent",)
                elif f in un:
                    b = ("unknown", "binary or larger than 512 KB")
                elif new_fmt:
                    b = ("absent",)
                else:
                    b = ("unknown", "recorded before restore metadata existed")
                out.append(dict(ts=ts, file=f, node=nk if not e.get("ov_bash_writes_ambiguous") else None, before=b))
    out.sort(key=lambda c: c["ts"])
    return out


def _plan(chs):
    first, touched = {}, collections.defaultdict(set)
    for c in chs:
        touched[c["file"]].add(c["node"])
        first.setdefault(c["file"], c)
    plan = []
    for f, c in sorted(first.items()):
        b = c["before"]
        exists = os.path.exists(os.path.join(ROOT, f))
        if b[0] == "absent":
            act = "delete" if exists else "none"
        elif b[0] == "digest":
            act = "restore" if b[1] and os.path.exists(os.path.join(STORE, b[1])) else "unrestorable"
        elif b[0] == "snap":
            act = "restore" if os.path.exists(b[1]) else "unrestorable"
        else:
            act = "unrestorable"
        plan.append(dict(file=f, action=act, source=list(b), by=sorted(x for x in touched[f] if x)))
    return plan


def plan_since(ts, evs=None):
    return _plan([c for c in changes(evs) if c["ts"] >= ts])


def plan_for_node(key, evs=None):
    """Undo one node's changes: each file back to its state before that node first touched it.
    Flags files another node changed afterwards, since reverting those loses the other work."""
    chs = changes(evs)
    mine = [c for c in chs if c["node"] == key]
    plan = _plan(mine)
    for p in plan:
        t0 = next(c["ts"] for c in mine if c["file"] == p["file"])
        p["also_changed_by"] = sorted({c["node"] for c in chs if c["file"] == p["file"]
                                       and c["ts"] > t0 and c["node"] not in (key, None)})
    return plan


def apply_plan(plan, tag):
    """Back up every file the plan overwrites or deletes, then apply it. Returns the backup id."""
    bid = f"{time.strftime('%Y%m%d-%H%M%S')}-{tag}"
    bdir = os.path.join(BACKUPS, bid)
    os.makedirs(bdir, exist_ok=True)
    manifest, done = {}, collections.Counter()
    for p in plan:
        if p["action"] not in ("restore", "delete"):
            done[p["action"]] += 1
            continue
        ap = os.path.join(ROOT, p["file"])
        if os.path.exists(ap):
            dst = os.path.join(bdir, p["file"])
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(ap, dst)
            manifest[p["file"]] = "present"
        else:
            manifest[p["file"]] = "absent"
        if p["action"] == "delete":
            if os.path.exists(ap):
                os.remove(ap)
        else:
            src = os.path.join(STORE, p["source"][1]) if p["source"][0] == "digest" else p["source"][1]
            os.makedirs(os.path.dirname(ap) or ROOT, exist_ok=True)
            shutil.copy2(src, ap)
        done[p["action"]] += 1
    json.dump(manifest, open(os.path.join(bdir, "_manifest.json"), "w"), indent=1)
    return bid, dict(done)


def undo(bid):
    bdir = os.path.join(BACKUPS, bid)
    man = json.load(open(os.path.join(bdir, "_manifest.json")))
    for f, st in man.items():
        ap = os.path.join(ROOT, f)
        if st == "present":
            os.makedirs(os.path.dirname(ap) or ROOT, exist_ok=True)
            shutil.copy2(os.path.join(bdir, f), ap)
        elif os.path.exists(ap):
            os.remove(ap)
    return len(man)


# ---------------------------------------------------------------- impact --------------------
PATH_RE = re.compile(r"(?<![\w@])((?:\.{0,2}/)?[\w.\-]+(?:/[\w.\-]+)+/?|[\w\-]+\.[A-Za-z]{1,5})(?![\w/])")


def paths_in(text):
    out = []
    for m in PATH_RE.finditer(text or ""):
        p = rel(m.group(1).rstrip("/.,;:"))
        if p.startswith("./"):
            p = p[2:]
        if re.fullmatch(r"[A-Za-z]{1,2}\.[A-Za-z]{1,2}", p):   # "e.g", "i.e": prose, not files
            continue
        if in_ws(p) and not re.match(r"^\d", p) and p not in out and "." in p.split("/")[-1] + ("x" if p.endswith("/") else ""):
            out.append(p)
        elif in_ws(p) and p.endswith("/") and p not in out:
            out.append(p)
    return out[:20]


def downstream_of(nodes, key, files):
    return sorted(k for k, n in nodes.items() if k != key and n["reads"] & set(files))


def cross_session(nodes, key, files):
    s = nodes[key]["session"] if key in nodes else None
    return sorted(k for k, n in nodes.items() if k != key and n["session"] != s and n["writes"] & set(files))


# ---------------------------------------------------------------- the record ----------------
def record(kind, initiated_by, target, impact, decision, cp_before, cp_after, note="", extra=None):
    st = run_state()
    rec = dict(ov_event="intervention", ov_ts=now_ms(), ov_session_no=max(st["session"], 1),
               session_id="control", kind=kind, initiated_by=initiated_by, decided_by="human",
               target=target, impact_shown=impact, decision=decision,
               checkpoint_before=cp_before, checkpoint_after=cp_after, note=note)
    if extra:
        rec.update(extra)
    for fn in ("interventions.jsonl", "events.jsonl"):
        with open(os.path.join(OV if fn == "events.jsonl" else CTL, fn), "a") as f:
            f.write(json.dumps(rec, default=list) + "\n")
    return rec


def interventions():
    p = os.path.join(CTL, "interventions.jsonl")
    return [json.loads(l) for l in open(p)] if os.path.exists(p) else []


# ---------------------------------------------------------------- 1. split gate -------------
def pending():
    out = []
    for fn in sorted(os.listdir(PENDING)) if os.path.isdir(PENDING) else []:
        if fn.endswith(".json"):
            try:
                out.append(json.load(open(os.path.join(PENDING, fn))))
            except Exception:
                pass
    return out


def split_impact(caller, description, prompt, evs=None):
    evs = load_events() if evs is None else evs
    nodes, _ = build(evs)
    par = nodes.get(caller)
    pw = sorted(par["writes"]) if par else []
    scope = paths_in(prompt)
    _, down = walk_impact(caller, evs=evs)
    cross = cross_session(nodes, caller, scope + pw)
    kids = [k for k, n in nodes.items() if n.get("parent") == caller]
    return dict(
        parent=caller, parent_label=label(nodes, caller) if par else caller,
        child=description,
        files_in_scope=scope,
        parent_output=pw[:30], parent_output_count=len(pw),
        downstream=[dict(key=d["key"], label=d["label"], depth=d["depth"], reason=d["reason"]) for d in down],
        cross_session=[dict(key=k, label=label(nodes, k)) for k in cross],
        threshold=len(down) >= 2 or bool(cross),
        existing_children=[dict(key=k, label=label(nodes, k)) for k in kids],
        checkpoint_before=latest_checkpoint(evs))


def flag(name, default="off"):
    """Feature switches kept as one-word files in oversight/: gate_mode, recommend_mode."""
    try:
        return open(os.path.join(OV, name)).read().strip() or default
    except Exception:
        return default


def set_flag(name, state):
    open(os.path.join(OV, name), "w").write("on" if state == "on" else "off")


def decide(rid, decision, note="", reset_to=None):
    """decision: accept | accept_all | modify | reject | reset.

    accept_all also approves every further spawn from the same parent until that parent finishes.
    It is explicit because agents propose a split one child per message, so a human accepting the
    first child has not seen the rest. For reset the files are restored now, while the agent is
    paused, and the agent is told why its spawn was refused."""
    req_p = os.path.join(PENDING, f"{rid}.json")
    if not os.path.exists(req_p):
        raise ValueError(f"no pending split {rid}")
    req = json.load(open(req_p))
    cp_before = new_wcp(f"before split decision {rid}")
    extra = dict(request=rid, parent=req["caller"], child=req["description"])
    if decision == "reset":
        # default: the most recent checkpoint, i.e. undo the latest change. The orchestrator has no
        # spawn time to reset to, so "before this branch" only exists for subagent parents.
        reset_to = reset_to or latest_checkpoint()
        if not reset_to:
            raise ValueError("no checkpoint to reset to")
        ts, what = resolve(reset_to)
        plan = plan_since(ts)
        bid, done = apply_plan(plan, f"split-reset-{rid}")
        extra.update(reset_to=reset_to, reset_desc=what, backup=bid, restored=done)
        note = note or f"workspace reset to {what}"
    if decision == "accept_all":
        json.dump(dict(rid=rid, ts=now_ms(), parent=req["caller"]),
                  open(os.path.join(CTL, f"standing_{_safe(req['caller'])}.json"), "w"))
    json.dump(dict(decision=decision, note=note, reset_to=reset_to, ts=now_ms()),
              open(os.path.join(DECISIONS, f"{rid}.json"), "w"))
    cp_after = new_wcp(f"after split decision {rid}") if decision == "reset" else cp_before
    return record("split", "agent", req["caller"], req.get("impact"), decision, cp_before, cp_after, note, extra)


def _safe(k):
    return re.sub(r"[^\w.-]", "_", k or "main")


# ---------------------------------------------------------------- 2. reset ------------------
def preview_reset(target):
    evs = load_events()
    ts, what = resolve(target, evs)
    nodes, live = build(evs)
    plan = plan_since(ts, evs)
    by_node = collections.defaultdict(list)
    for c in changes(evs):
        if c["ts"] >= ts:
            by_node[c["node"]].append(c["file"])
    back = [k for k, n in nodes.items() if not n["main"] and (n.get("start") or 0) >= ts]
    discards = [dict(node=label(nodes, k) if k else "unattributed", files=sorted(set(v))[:8], n=len(set(v)))
                for k, v in by_node.items()]
    changed = [p["file"] for p in plan if p["action"] in ("restore", "delete")]
    down = sorted({k for k, n in nodes.items() if n["reads"] & set(changed)} - set(back))
    return dict(kind="reset", target=target, to=what, ts=ts,
                discards=discards, nodes_back_to_pending=[label(nodes, k) for k in back],
                files_restored=sum(1 for p in plan if p["action"] == "restore"),
                files_deleted=sum(1 for p in plan if p["action"] == "delete"),
                unrestorable=[p["file"] for p in plan if p["action"] == "unrestorable"],
                downstream=[label(nodes, k) for k in down],
                threshold=len(down) >= 2, run=run_state(evs), plan=plan)


def apply_reset(target, note="", force=False):
    st = run_state()
    if st["active"] and not st["paused"] and not force:
        raise RuntimeError("a run is active and not paused; resetting under a working agent would "
                           "corrupt its files. Wait for it to end, reset while a split is pending, or pass force.")
    pv = preview_reset(target)
    cp_before = new_wcp(f"before reset to {target}")
    bid, done = apply_plan(pv["plan"], f"reset-{target}")
    cp_after = new_wcp(f"after reset to {target}")
    branch = f"S{st['session']}b"
    impact = {k: pv[k] for k in ("to", "files_restored", "files_deleted", "unrestorable",
                                  "nodes_back_to_pending", "downstream", "threshold")}
    return record("reset", "human", target, impact, "confirm", cp_before, cp_after, note,
                  dict(backup=bid, applied=done, branch=branch))


# ---------------------------------------------------------------- 3. edit and rerun ---------
def preview_edit(node_ref, new_brief):
    evs = load_events()
    nodes, _ = build(evs)
    k = find_node(nodes, node_ref)
    if not k or nodes[k]["main"]:
        raise ValueError(f"not a subagent node: {node_ref}")
    n = nodes[k]
    plan = plan_for_node(k, evs)
    out_files = [p["file"] for p in plan if p["action"] in ("restore", "delete")]
    _, walked = walk_impact(k, evs=evs)
    down = [d["key"] for d in walked]
    sibs = [x for x, m in nodes.items() if x != k and m.get("parent") == n["parent"]]
    st = run_state(evs)
    parent_alive = nodes[n["parent"]]["status"] == "running" if n["parent"] in nodes else False
    route = "orchestrator" if st["active"] and parent_alive else "standalone"
    warn = []
    if n["status"] == "running":
        warn.append("this node is still running; reverting its files now would corrupt its work. "
                    "Send it an instruction instead, or wait until it finishes.")
    clobber = sorted({x for p in plan for x in p["also_changed_by"]})
    if clobber:
        warn.append("some of these files were changed afterwards by " +
                    ", ".join(label(nodes, x) for x in clobber) + "; reverting loses that work too")
    return dict(kind="edit", node=k, node_label=label(nodes, k), status=n["status"],
                old_brief=n["prompt"], new_brief=new_brief,
                discards=out_files[:40], discards_n=len(out_files),
                downstream=[label(nodes, x) for x in down],
                downstream_reasons=[dict(label=d["label"], reason=d["reason"], depth=d["depth"]) for d in walked],
                untouched_siblings=[label(nodes, x) for x in sibs],
                threshold=len(down) >= 2, route=route, warnings=warn, plan=plan)


def apply_edit(node_ref, new_brief, note="", launch=False, force=False):
    pv = preview_edit(node_ref, new_brief)
    if pv["status"] == "running" and not force:
        raise RuntimeError(pv["warnings"][0])
    nodes, _ = build()
    k = pv["node"]
    cp_before = new_wcp(f"before edit-and-rerun {k[:10]}")
    bid, done = apply_plan(pv["plan"], f"edit-{k[:10]}")
    extra = dict(backup=bid, applied=done, route=pv["route"], node_label=pv["node_label"])
    if pv["route"] == "orchestrator":
        msg = (f"A human overseer edited the brief for the subagent \"{nodes[k]['intent']}\" and asked "
               f"for it to be rerun. Its previous output has been reverted ({pv['discards_n']} files). "
               f"Spawn it again using exactly this brief:\n\n{new_brief}")
        extra["inbox_id"] = tell_raw("main" if nodes[k]["parent"].startswith("main:") else nodes[nodes[k]["parent"]]["agent_id"], msg)
    else:
        extra["rerun_script"] = write_rerun(k, new_brief)
        extra["branch"] = f"S{run_state()['session'] + 1} (rerun of {k[:10]})"
        if launch:
            subprocess.Popen(["bash", extra["rerun_script"]], cwd=ROOT, start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            extra["launched"] = True
    cp_after = new_wcp(f"after edit-and-rerun {k[:10]}")
    impact = {x: pv[x] for x in ("discards_n", "downstream", "untouched_siblings", "threshold", "route")}
    return record("edit_rerun", "human", k, impact, "confirm", cp_before, cp_after, note, extra)


def write_rerun(k, brief):
    p = os.path.join(CTL, f"rerun_{_safe(k)[:16]}.sh")
    bp = p[:-3] + ".brief.txt"
    open(bp, "w").write(brief)
    open(p, "w").write(
        "#!/bin/bash\n# Rerun of node %s with a human-edited brief. Generated by oversight/control.py.\n"
        "cd %s\nexport OVERSIGHT_RERUN_OF=%s\n"
        "claude -p \"$(cat %s)\" --permission-mode acceptEdits "
        "--allowedTools Bash Read Write Edit MultiEdit Glob Grep LS Task Agent TodoWrite < /dev/null\n"
        % (k, json.dumps(ROOT), json.dumps(k), json.dumps(bp)))
    os.chmod(p, 0o755)
    return p


# ---------------------------------------------------------------- 4. instruction ------------
def preview_tell(node_ref, text):
    evs = load_events()
    nodes, _ = build(evs)
    k = find_node(nodes, node_ref)
    if not k:
        raise ValueError(f"no such node: {node_ref}")
    n = nodes[k]
    scope = sorted(set(n["writes"]) | set(paths_in(n["prompt"])))
    _, walked = walk_impact(k, evs=evs)
    down = [d["key"] for d in walked]
    deliverable = n["status"] == "running"
    return dict(kind="instruction", node=k, node_label=label(nodes, k), status=n["status"], text=text,
                files_in_scope=scope[:20], downstream=[label(nodes, x) for x in down],
                deliverable=deliverable,
                warnings=[] if deliverable else [
                    f"this node is {n['status']}; there is no running agent to receive it. "
                    "Use edit-and-rerun to change what it produced."])


def tell_raw(agent_key, text):
    iid = f"i{now_ms()}"
    with open(os.path.join(INBOX, f"{_safe(agent_key)}.jsonl"), "a") as f:
        f.write(json.dumps(dict(id=iid, ts=now_ms(), text=text)) + "\n")
    return iid


def apply_tell(node_ref, text, note=""):
    pv = preview_tell(node_ref, text)
    if not pv["deliverable"]:
        raise RuntimeError(pv["warnings"][0])
    nodes, _ = build()
    k = pv["node"]
    key = "main" if nodes[k]["main"] else nodes[k]["agent_id"]
    iid = tell_raw(key, text)
    cp = latest_checkpoint()
    impact = {x: pv[x] for x in ("files_in_scope", "downstream")}
    return record("instruction", "human", k, impact, "confirm", cp, cp, note,
                  dict(inbox_id=iid, text=text, node_label=pv["node_label"]))


def record_cancel(kind, target, impact, note=""):
    cp = latest_checkpoint()
    return record(kind, "human", target, impact, "cancel", cp, cp, note)


# ---------------------------------------------------------------- dependency contracts --------
# The agent never declares a node's inputs, but the log records which VERSION of each file a node
# read and which version each node produced. That is enough for an honest contract:
#   Y depends on X   only if the version Y read is one X produced (or, in logs recorded before
#                    versions were captured, X was the last to write the file before Y read it)
#   contract broken  the file has changed since Y read it: Y's work rests on a stale input
# Impact walks these edges transitively over the whole current graph, so a node created later
# that consumes a downstream node's output is picked up automatically.
import hashlib as _hl


def _current_digest(f):
    ap = os.path.join(ROOT, f)
    try:
        blob = open(ap, "rb").read()
    except OSError:
        return None
    return _hl.sha256(blob).hexdigest()[:16]


def flows(evs=None):
    """Per node: files produced [(ts, file, digest)] and consumed [(ts, file, digest)]."""
    evs = load_events() if evs is None else evs
    nodes, live = build(evs)
    prod = collections.defaultdict(list)
    cons = collections.defaultdict(list)
    for e in evs:
        k = node_of(e, live)
        ts, ev = e["ov_ts"], e.get("ov_event")
        ti = e.get("tool_input") or {}
        if ev == "post_tool" and e.get("tool_name") in WRITE:
            f = rel(ti.get("file_path"))
            if in_ws(f):
                prod[k].append((ts, f, (e.get("ov_after") or {}).get(f)))
        if ev == "post_tool" and e.get("tool_name") == "Bash" and not e.get("ov_bash_writes_ambiguous"):
            av = e.get("ov_after") or {}
            for f in set(e.get("ov_bash_writes") or []) | set(e.get("ov_bash_writes_dropped") or []):
                if in_ws(f):
                    prod[k].append((ts, f, av.get(f)))
        if ev == "pre_tool":
            rd = e.get("ov_read_digests") or {}
            files = set(rd) | set(e.get("ov_bash_reads") or [])
            if e.get("tool_name") == "Read" and ti.get("file_path"):
                files.add(rel(ti["file_path"]))
            for f in files:
                if in_ws(f):
                    cons[k].append((ts, f, rd.get(f)))
    return nodes, prod, cons


def dependency_graph(evs=None):
    """Edges X -> Y, one per pair, with the files that bind them, a reason, and stale files."""
    nodes, prod, cons = flows(evs)
    by_file = collections.defaultdict(list)                 # file -> [(ts, producer, digest)]
    for k, lst in prod.items():
        for ts, f, d in lst:
            by_file[f].append((ts, k, d))
    for f in by_file:
        by_file[f].sort()
    cur = {}
    edges = {}
    for y, lst in cons.items():
        for ts, f, d in lst:
            cands = [(t, x, dd) for t, x, dd in by_file.get(f, []) if x != y]
            if not cands:
                continue
            src, exact = None, False
            if d:
                match = [c for c in cands if c[2] == d]
                if match:
                    prior = [c for c in match if c[0] <= ts]
                    hit = max(prior or match)                  # the write that produced the version Y read
                    src, exact = hit[1], True
            if src is None:
                before = [c for c in cands if c[0] <= ts]
                if not before:
                    continue                                   # Y read it before anyone wrote it
                last = before[-1]
                if d and last[2] and last[2] != d:
                    continue                                   # Y read some other version
                src, hit = last[1], last
            if f not in cur:
                cur[f] = _current_digest(f)
            stale = bool(d and cur[f] and cur[f] != d)
            prod_ts = hit[0]
            key = (src, y)
            e = edges.setdefault(key, dict(src=src, dst=y, files=set(), stale=set(), exact=True, uses=[]))
            e["files"].add(f)
            e["uses"].append((f, prod_ts, ts))       # (file, when its version was produced, when read)
            e["exact"] = e["exact"] and exact
            if stale:
                e["stale"].add(f)
    out = []
    for (x, y), e in edges.items():
        fs = sorted(e["files"])
        out.append(dict(src=x, dst=y, files=fs, stale=sorted(e["stale"]), exact=e["exact"], uses=e["uses"],
                        reason=f"{label(nodes, y).split(' (')[0]} reads {_short(fs)} produced by "
                               f"{label(nodes, x).split(' (')[0]}"
                               + (f"; {_short(sorted(e['stale']))} changed since it was read" if e["stale"] else "")))
    return nodes, out


def _short(fs, n=2):
    fs = [f.split("/")[-1] for f in fs]
    return ", ".join(fs[:n]) + (f" +{len(fs) - n}" if len(fs) > n else "")


def walk_impact(start, changed=None, evs=None, max_depth=6):
    """Nodes invalidated if `start`'s output changes, transitively, each with its reason chain.

    Causal: a node reached through an input it read at time t can only pass the damage on through
    outputs it produced at or after t. Outputs it wrote before reading the changed input do not
    depend on it. `changed` restricts the first hop to those files (default: all of start's output).
    """
    nodes, edges = dependency_graph(evs)
    out_of = collections.defaultdict(list)
    for e in edges:
        out_of[e["src"]].append(e)
    taint = {start: float("-inf")}       # node -> earliest time from which its outputs are affected
    res, frontier = [], [(start, 0)]
    while frontier:
        x, depth = frontier.pop(0)
        if depth >= max_depth:
            continue
        for e in out_of[x]:
            y = e["dst"]
            if y == start:
                continue
            hits = [(f, pt, rt) for f, pt, rt in e["uses"]
                    if pt >= taint[x] and (depth > 0 or changed is None or f in changed)]
            if not hits:
                continue
            t_read = min(rt for _, _, rt in hits)
            if y in taint and taint[y] <= t_read:
                continue                  # already reached at least as early
            first = y not in taint
            taint[y] = t_read
            files = sorted({f for f, _, _ in hits})
            src = label(nodes, x).split(" (")[0]
            reason = (f"reads {_short(files)} from {src}" if depth == 0 else
                      f"reads {_short(files)} from {src}, which must be redone")
            if first:
                res.append(dict(key=y, label=label(nodes, y), depth=depth + 1, reason=reason,
                                files=files, stale=e["stale"], exact=e["exact"]))
            frontier.append((y, depth + 1))
    return nodes, res


def node_impact(ref, evs=None):
    """Impact card for one node: if it is re-run or edited, what else is invalidated, and why."""
    evs = load_events() if evs is None else evs
    nodes, _ = build(evs)
    k = find_node(nodes, ref)
    if not k:
        raise ValueError(f"no such node: {ref}")
    _, down = walk_impact(k, evs=evs)
    n = nodes[k]
    cross = cross_session(nodes, k, n["writes"])
    _, edges = dependency_graph(evs)
    stale_in = [dict(src=label(nodes, e["src"]), files=e["stale"]) for e in edges if e["dst"] == k and e["stale"]]
    return dict(node=k, label=label(nodes, k), files_written=sorted(n["writes"]),
                downstream=down, direct=sum(1 for d in down if d["depth"] == 1),
                cross_session=[dict(key=x, label=label(nodes, x)) for x in cross],
                stale_inputs=stale_in, threshold=len(down) >= 2 or bool(cross))


def recommendations(caller, prompt, scope, existing, plan, evs=None):
    """Pros and cons of a split, from structure only (spec: parallelism, disjoint files, expected
    wall-clock saving; dependencies, coordination edges added, downstream re-runs)."""
    evs = load_events() if evs is None else evs
    nodes, prod, cons = flows(evs)
    scope = set(scope)
    sibs = [k for k in existing if k in nodes]
    pros, cons_ = [], []
    disjoint = [k for k in sibs if not (nodes[k]["writes"] & scope)]
    overlap = {k: sorted(nodes[k]["writes"] & scope) for k in sibs if nodes[k]["writes"] & scope}
    deps = {k: sorted({f for _, f, _ in prod.get(k, [])} & scope) for k in sibs}
    deps = {k: v for k, v in deps.items() if v}
    if disjoint:
        pros.append(f"shares no files with {len(disjoint)} earlier sibling(s) "
                    f"({_short([label(nodes, k).split(' (')[0] for k in disjoint], 3)}): they can run in parallel")
    if len(sibs) + 1 >= 2:
        pros.append(f"{len(sibs) + 1} units would run at once instead of one after another")
    durs = [(nodes[k]["stop"] - nodes[k]["start"]) / 60000 for k in sibs if nodes[k].get("stop") and nodes[k].get("start")]
    if len(durs) >= 2:
        pros.append(f"siblings so far took {', '.join(f'{d:.1f}' for d in durs)} min: about "
                    f"{sum(durs):.1f} min in sequence vs {max(durs):.1f} min in parallel")
    for k, fs in overlap.items():
        cons_.append(f"writes {_short(fs)} that {label(nodes, k).split(' (')[0]} also wrote: conflict risk")
    for k, fs in deps.items():
        cons_.append(f"depends on {label(nodes, k).split(' (')[0]}'s output ({_short(fs)}): adds a coordination edge")
    if deps:
        cons_.append(f"{len(deps)} coordination edge(s) added")
    _, down = walk_impact(caller, evs=evs)
    if down:
        cons_.append(f"{len(down)} downstream node(s) must re-run if the split changes the parent's output: "
                     + _short([d['label'].split(' (')[0] for d in down], 3))
    is_split = bool(sibs) or bool(re.search(r"\b(fan out|in parallel|parallel|subagents|split|spawn)\b", plan or "", re.I))
    return dict(is_split=is_split, pros=pros, cons=cons_)
