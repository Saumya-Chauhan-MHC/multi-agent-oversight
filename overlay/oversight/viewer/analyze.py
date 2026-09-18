#!/usr/bin/env python3
"""Post-session analysis of oversight/events.jsonl: the numbers behind the viewer, with the
interpretation rules from the plan. Run from the task folder:

    python3 oversight/viewer/analyze.py            # text report
    python3 oversight/viewer/analyze.py --json     # machine-readable

Sections: timeline, units (nodes) and their files, overlap between units, edges, rework, rule
denials, and a verdict block that states what the run says for the three questions:
  Q1 did the harness split the work at all?      Q2 do the units own disjoint files (DAG shape)?
  Q3 what did session 2 do with session 1's output? (only when 2+ launches are in the log)
"""
import json, os, sys, collections, itertools
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
p = os.path.join(ROOT, "oversight", "events.jsonl")
if not os.path.exists(p): print("no oversight/events.jsonl"); sys.exit(1)
evs = [json.loads(l) for l in open(p) if l.strip()]
evs.sort(key=lambda e: e["ov_ts"])
WRITE = ("Edit", "Write", "MultiEdit")
def fp(e): return (e.get("tool_input") or {}).get("file_path")
def in_ws(f):
    if not f:
        return False
    a = f if os.path.isabs(f) else os.path.join(ROOT, f)
    return os.path.normpath(a).startswith(os.path.normpath(ROOT) + os.sep)


def rel(f):
    """Relative inside the workspace; absolute (and obviously so) outside it."""
    if not f:
        return f
    if os.path.isabs(f):
        return os.path.relpath(f, ROOT) if in_ws(f) else f
    return f
def mins(ts, t0): return round((ts - t0) / 60000, 1)
def bwrites(e): return [rel(os.path.join(ROOT, f)) for f in (e.get("ov_bash_writes") or [])]
def bdropped(e): return [rel(os.path.join(ROOT, f)) for f in (e.get("ov_bash_writes_dropped") or [])]
def breads(e):  return [rel(os.path.join(ROOT, f)) for f in (e.get("ov_bash_reads") or [])]
def real_sub(e): return e.get("ov_subagent_real", True)
def human_prompt(t):
    """Subagent completions arrive as UserPromptSubmit too; they are not human steering."""
    t = (t or "").lstrip()
    return bool(t) and not t.startswith("<task-notification") and "<task-id>" not in t[:200]
def wrote_any(e):
    """True if this event created/changed files, by Write/Edit tool OR inside Bash."""
    return (e["ov_event"] == "pre_tool" and e.get("tool_name") in WRITE) or bool(e.get("ov_bash_writes"))

out = {"launches": {}}
by = collections.defaultdict(list)
for e in evs: by[e.get("ov_session_no", 1)].append(e)

for no, es in sorted(by.items()):
    t0 = es[0]["ov_ts"]; L = {"minutes": mins(es[-1]["ov_ts"], t0)}
    tools = [e for e in es if e["ov_event"] == "pre_tool"]
    L["tool_calls"] = len(tools)
    _allp = [(e.get("prompt") or "") for e in es if e["ov_event"] == "prompt"]
    L["prompts"] = [t[:160] for t in _allp if human_prompt(t)]
    L["system_prompts"] = len(_allp) - len(L["prompts"])
    # timeline
    def first(pred):
        for e in es:
            if pred(e): return mins(e["ov_ts"], t0)
        return None
    L["timeline_min"] = {
        "first_read": first(lambda e: (e["ov_event"] == "pre_tool" and e.get("tool_name") == "Read") or (e["ov_event"] == "pre_tool" and e.get("ov_bash_reads"))),
        "first_reference_probe": first(lambda e: e["ov_event"] == "pre_tool" and e.get("tool_name") == "Bash" and "executable" in (e.get("tool_input") or {}).get("command", "")),
        "first_write": first(wrote_any),
        "first_spawn": first(lambda e: e["ov_event"] == "subagent_start" and real_sub(e)),
        "first_compile": first(lambda e: e["ov_event"] == "pre_tool" and e.get("tool_name") == "Bash" and "compile.sh" in (e.get("tool_input") or {}).get("command", "")),
        "compactions": [mins(e["ov_ts"], t0) for e in es if e["ov_event"] == "pre_compact"],
        "end": mins(es[-1]["ov_ts"], t0),
    }
    L["reference_probes"] = sum(1 for e in tools if e.get("tool_name") == "Bash" and "executable" in (e.get("tool_input") or {}).get("command", "") or "oracle/reference" in (e.get("tool_input") or {}).get("command", ""))
    # subagent lifetimes, so an ambiguous Bash diff is not attributed during concurrency
    _alive = {}
    _seq = {}
    for e in es:
        if e["ov_event"] == "subagent_start" and real_sub(e):
            a = e.get("agent_id"); _seq[a] = _seq.get(a, 0) + 1
            _alive[(a, _seq[a])] = [e["ov_ts"], None]
        if e["ov_event"] == "subagent_stop" and real_sub(e):
            a = e.get("agent_id")
            if (a, _seq.get(a, 0)) in _alive:
                _alive[(a, _seq[a])][1] = e["ov_ts"]
    def concurrent(ts):
        return sum(1 for a, b in _alive.values() if a <= ts and (b is None or ts <= b))
    L["ambiguous_writes"] = []   # raw record of every unattributable Bash diff
    L["external_writes"] = {}    # path -> node, for files written outside the task folder
    # nodes: main + subagents
    nodes = {"main": {"type": "orchestrator", "prompt": "", "start": 0, "stop": L["minutes"], "writes": set(), "reads": set(), "writes_likely": set()}}
    pending = []
    live = {}  # agent_id -> node key currently receiving its events (ids get reused)
    for e in es:
        if e["ov_event"] == "pre_tool" and e.get("tool_name") in ("Agent", "Task"):
            pending.append(e)  # caller = e.get("agent_id") or "main" (nested spawns supported)
        if e["ov_event"] == "subagent_start" and real_sub(e):
            sp = pending.pop(0) if pending else None
            ti = (sp.get("tool_input") or {}) if sp else {}
            aid = e["agent_id"]
            key = aid
            if key in nodes:                      # id reused -> new node, keep the old one intact
                i = 2
                while f"{aid}#{i}" in nodes:
                    i += 1
                key = f"{aid}#{i}"
            live[aid] = key
            nodes[key] = {"type": e.get("agent_type", "subagent"), "parent": (sp.get("agent_id") if sp else None) or "main", "prompt": (ti.get("description") or ti.get("prompt") or "")[:200],
                                    "start": mins(e["ov_ts"], t0), "stop": None, "writes": set(), "reads": set(), "writes_likely": set()}
        if e["ov_event"] == "subagent_stop" and real_sub(e) and live.get(e.get("agent_id")) in nodes:
            _k = live[e["agent_id"]]
            nodes[_k]["stop"] = mins(e["ov_ts"], t0)
            nodes[_k]["summary"] = (e.get("last_assistant_message") or "")[:200]
        if e["ov_event"] in ("pre_tool", "post_tool"):
            nk = live.get(e.get("agent_id")) or e.get("agent_id") or "main"
            if nk not in nodes:
                nk = "main"
            n = nodes[nk]
            f = rel(fp(e))
            if f and e.get("tool_name") in WRITE and e["ov_event"] == "pre_tool":
                if in_ws(f):
                    n["writes"].add(f)
                else:
                    L["external_writes"][f] = nk  # scratch outside the task folder
            if f and e.get("tool_name") == "Read" and e["ov_event"] == "pre_tool": n["reads"].add(f)
            if bdropped(e):
                # written by this command but not named by it: same uncertainty as ambiguous
                L["ambiguous_writes"].append({"min": mins(e["ov_ts"], t0),
                                              "agent": e.get("agent_id") or "main",
                                              "node": live.get(e.get("agent_id")) or "main",
                                              "files": bdropped(e)})
            if e.get("ov_bash_writes_ambiguous") and concurrent(e["ov_ts"]) > 0:
                # the command named no workspace file and other agents were running:
                # the diff cannot tell whose write this was. Record, do not attribute.
                L["ambiguous_writes"].append({"min": mins(e["ov_ts"], t0),
                                              "agent": e.get("agent_id") or "main",
                                              "node": live.get(e.get("agent_id")) or "main",
                                              "files": bwrites(e)})
            else:
                for bf in bwrites(e):
                    if in_ws(bf):
                        n["writes"].add(bf)
                    else:
                        L["external_writes"][bf] = nk
            for bf in breads(e):
                if in_ws(bf):
                    n["reads"].add(bf)
    # Three-tier attribution. A file no command named, whose write window belongs to exactly one
    # node, is that node's "likely" write: nothing else could have produced it. Only a file whose
    # window is shared by two or more nodes is genuinely unattributable.
    _amb_by_file = collections.defaultdict(set)
    for a in L["ambiguous_writes"]:
        for f in a["files"]:
            _amb_by_file[f].add(a["node"])
    _confident = {f for v in nodes.values() for f in v["writes"]}

    def still_exists(f):
        a = f if os.path.isabs(f) else os.path.join(ROOT, f)
        return os.path.exists(a)

    L["transient_writes"] = []
    for f, owners in _amb_by_file.items():
        if f in _confident:
            continue                       # author already known; others merely overlapped
        if len(owners) == 1:
            if not still_exists(f):
                L["transient_writes"].append(f)   # scratch: seen once, gone now
                continue
            k = next(iter(owners))
            if k in nodes:
                nodes[k]["writes_likely"].add(f)
    # candidate conflicts: a file that could have been written by two or more different nodes.
    # Counts nodes with an attributed write plus nodes whose ambiguous concurrent diff named it.
    # A file whose author IS known (some command named it) needs no candidate flag: other agents'
    # ambiguous windows merely overlapped it. Only a file nobody named, touched during two or more
    # different agents' windows, is a genuine unattributable shared write - the `bash compile.sh`
    # case, where the command never mentions ./executable.
    _transient = set(L.get("transient_writes", []))
    L["candidate_conflicts"] = [
        {"file": f, "agents_running": sorted(ag)}
        for f, ag in sorted(_amb_by_file.items())
        if f not in _confident and f not in _transient and len(ag) > 1
    ]
    for f, ag in _amb_by_file.items():
        if f not in _confident and len(ag) > 1 and not still_exists(f):
            L["transient_writes"].append(f)
    L["nodes"] = {k: {**v, "writes": sorted(v["writes"]), "writes_likely": sorted(v["writes_likely"]), "reads": sorted(v["reads"])} for k, v in nodes.items()}
    L["attribution"] = {
        "confident": len({f for v in nodes.values() for f in v["writes"]}),
        "likely": len({f for v in nodes.values() for f in v["writes_likely"]}),
        "unattributed": len(L["candidate_conflicts"]),
    }
    subs = [k for k in nodes if k != "main"]
    L["subagents"] = len(subs)
    # parallelism: subagents whose lifetimes overlap
    par = 0
    for a, b in itertools.combinations(subs, 2):
        A, B = nodes[a], nodes[b]
        if A["start"] <= (B["stop"] if B["stop"] is not None else 1e9) and B["start"] <= (A["stop"] if A["stop"] is not None else 1e9): par += 1
    L["parallel_pairs"] = par
    # overlap between units (Jaccard on written files), and edges
    ov = []
    for a, b in itertools.combinations(subs, 2):
        A, B = nodes[a]["writes"], nodes[b]["writes"]
        if A or B: ov.append({"pair": [a, b], "shared": sorted(A & B), "jaccard": round(len(A & B) / len(A | B), 2)})
    L["write_overlap"] = ov
    edges = []
    for k, n in nodes.items():
        for j, m in nodes.items():
            if j == k: continue
            dep = n["reads"] & m["writes"]
            if dep and not (j == "main" and k != "main" and False): edges.append({"from": j, "to": k, "kind": "data", "files": sorted(dep)})
            con = n["writes"] & m["writes"]
            if con and k > j: edges.append({"from": j, "to": k, "kind": "conflict", "files": sorted(con)})
    L["edges"] = edges
    # rework inside the launch: same file written by main more than once late after a subagent wrote it
    L["denials"] = [{"min": mins(e["ov_ts"], t0), "tool": e.get("tool_name"), "cmd": ((e.get("tool_input") or {}).get("command") or (e.get("tool_input") or {}).get("url") or "")[:100]}
                    for e in es if e["ov_event"] == "pre_tool" and (e.get("tool_name") in ("WebFetch", "WebSearch") or any(w in ((e.get("tool_input") or {}).get("command") or "") for w in ("curl ", "wget ", "git clone", "go get", "pip install")))]
    out["launches"][no] = L

# cross-launch handoff
if len(by) > 1:
    _act = [n for n in sorted(by) if out["launches"][n]["tool_calls"] > 0] or sorted(by)
    s1w = set(); s1 = out["launches"][_act[0]]
    for n in s1["nodes"].values(): s1w |= set(n["writes"])
    s1w.discard(None)
    later = [e for no, es in by.items() if no > _act[0] for e in es if e["ov_event"] == "pre_tool"]
    lr = {rel(fp(e)) for e in later if e.get("tool_name") == "Read"} | {f for e in later for f in breads(e)}
    lw = {rel(fp(e)) for e in later if e.get("tool_name") in WRITE} | {f for e in later for f in bwrites(e)}
    reads = lr & s1w
    rewr = lw & s1w
    newf = lw - s1w - {None}
    report_read = any("AGENT_REPORT" in (x or "") for x in lr)
    out["handoff"] = {"s1_files": len(s1w), "s2_read": sorted(reads), "s2_rewrote": sorted(rewr), "s2_new_files": sorted(newf), "read_AGENT_REPORT": report_read}

# verdicts
V = []
ACTIVE = [n for n in sorted(by) if out["launches"][n]["tool_calls"] > 0] or sorted(by)
L1NO = ACTIVE[0]
L1 = out["launches"][L1NO]
if L1NO != min(by):
    V.append(f"Note: launches {[n for n in sorted(by) if n < L1NO]} had 0 tool calls (aborted/restarted launch); "
             f"the verdict below is for launch {L1NO}.")
if L1["subagents"] == 0:
    V.append("Q1 (did the harness split?): NO. One node did all the work. The DAG for this launch is a single node. "
             f"First write at {L1['timeline_min']['first_write']} min, end at {L1['timeline_min']['end']} min: "
             + ("the core was still being written when the run ended." if L1['timeline_min']['first_write'] is None else "the agent reached a build and still chose not to delegate."))
else:
    V.append(f"Q1: YES. {L1['subagents']} subagent(s), first at {L1['timeline_min']['first_spawn']} min; {L1['parallel_pairs']} pair(s) ran in parallel.")
    jac = [o["jaccard"] for o in L1["write_overlap"]]
    if jac:
        mx = max(jac)
        V.append("Q2 (disjoint files?): " + ("YES. No two subagents wrote the same file; units own disjoint files, the DAG has structure." if mx == 0 else
                 f"PARTLY. Max Jaccard overlap {mx}; shared files: {sorted({f for o in L1['write_overlap'] for f in o['shared']})}. These are the conflict edges; check whether they are a registry-style file every unit must touch."))
    elif L1["subagents"] == 1:
        w = L1["nodes"][subs_first := [k for k in L1["nodes"] if k != "main"][0]]["writes"]
        V.append("Q2: only one subagent, so no unit-vs-unit overlap to measure; it " + (f"wrote {w[:5]}" if w else "wrote nothing (read-only probe)") + ".")
    else:
        V.append("Q2: subagents wrote nothing (read-only probes); the split was for exploration, not implementation.")
    data = [e for e in L1["edges"] if e["kind"] == "data"]
    V.append(f"Edges: {len(data)} data edge(s) (a node read what another wrote), {len([e for e in L1['edges'] if e['kind']=='conflict'])} conflict edge(s).")
if L1.get("candidate_conflicts"):
    V.append("Q2 caveat: " + str(len(L1["candidate_conflicts"])) + " candidate conflict(s) could not be attributed - "
             + ", ".join(sorted({(os.path.dirname(c["file"]) or ".") + "/" for c in L1["candidate_conflicts"]})[:5])
             + ". These were written by a command that never named them, while two or more agents were running, "
               "so the log cannot say which produced them. The listed agents were merely active at the time.")
if "handoff" in out:
    h = out["handoff"]
    V.append(f"Q3 (handoff): session 2 read {len(h['s2_read'])} of session 1's {h['s1_files']} files, re-wrote {len(h['s2_rewrote'])}, created {len(h['s2_new_files'])} new; AGENT_REPORT.md read: {h['read_AGENT_REPORT']}. "
             + ("Handoff carried (attach)." if len(h['s2_read']) and len(h['s2_rewrote']) <= len(h['s2_read']) else "Session 2 mostly redid session 1 (restart)."))
if len(L1["prompts"]) > 1:
    V.append(f"Steering: {len(L1['prompts'])} human prompts in launch {L1NO} (T0 expects exactly 1). Extra: {[p[:60] for p in L1['prompts'][1:]]}")
if L1["denials"]: V.append(f"Rule denials: {len(L1['denials'])} attempt(s) to reach the network or the source; see 'denials'.")
if L1["timeline_min"]["compactions"]: V.append(f"Context compactions at {L1['timeline_min']['compactions']} min: the agent lost verbatim history there; treat as within-session handoffs.")
out["verdict"] = V

if "--json" in sys.argv:
    print(json.dumps(out, indent=1, default=list)); sys.exit(0)
for no, L in out["launches"].items():
    print(f"=== launch {no}: {L['minutes']} min, {L['tool_calls']} tool calls, {L['subagents']} subagents, {L['reference_probes']} reference probes")
    print("  timeline (min):", {k: v for k, v in L["timeline_min"].items()})
    if L.get("attribution"):
        A = L["attribution"]
        print(f"  attribution: {A['confident']} confident, {A['likely']} likely, {A['unattributed']} unattributed"
              + (f", {len(L['transient_writes'])} transient (deleted scratch, unattributed)" if L.get("transient_writes") else ""))
    if L.get("external_writes"):
        ex = collections.Counter(L["external_writes"].values())
        print(f"  outside the task folder: {len(L['external_writes'])} file(s); " +
              ", ".join(f"{k[:8]}:{v}" for k, v in ex.most_common()))
    for k, n in L["nodes"].items():
        print(f"  node {k} [{n['type']}] {n['start']}-{n['stop']} min | prompt: {n['prompt'][:90]!r}")
        print(f"     wrote {n['writes'][:12]}{' ...' if len(n['writes'])>12 else ''}")
        if n.get("writes_likely"):
            print(f"     likely (unnamed, sole window) {n['writes_likely'][:8]}{' ...' if len(n['writes_likely'])>8 else ''}  [{len(n['writes_likely'])}]")
        print(f"     read  {len(n['reads'])} files")
    for e in L["edges"]: print(f"  edge {e['kind']}: {e['from']} -> {e['to']} via {e['files'][:5]}")
    for o in L["write_overlap"]:
        if o["shared"]: print(f"  overlap {o['pair']}: jaccard {o['jaccard']} shared {o['shared']}")
    for d in L["denials"]: print(f"  denied @{d['min']} min: {d['tool']} {d['cmd']}")
    cc = L.get("candidate_conflicts", [])
    if cc:
        groups = collections.defaultdict(lambda: {"n": 0, "ag": set(), "eg": None})
        for c in cc:
            d = os.path.dirname(c["file"]) or "."
            g = groups[d]
            g["n"] += 1
            g["ag"] |= set(c["agents_running"])
            g["eg"] = g["eg"] or os.path.basename(c["file"])
        print(f"  unattributed writes: {len(cc)} file(s) in {len(groups)} location(s), "
              "written by a command that named none of them while 2+ agents ran")
        for d, g in sorted(groups.items(), key=lambda x: -x[1]["n"]):
            agents = ", ".join(a[:8] for a in sorted(g["ag"]))
            print(f"    {d}/  {g['n']} file(s) (e.g. {g['eg']}); agents running: {agents}")
    for a in L.get("ambiguous_writes", []):
        print(f"  unattributed write @{a['min']} min (agent {a['agent'][:8]}, concurrent): {a['files'][:6]}")
if "handoff" in out: print("=== handoff:", json.dumps(out["handoff"]))
print("=== verdict")
for v in out["verdict"]: print(" -", v)
