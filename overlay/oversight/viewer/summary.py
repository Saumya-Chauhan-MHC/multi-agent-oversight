#!/usr/bin/env python3
"""Text summary of oversight/events.jsonl (same facts as the viewer, for pasting into chat).
Run from the task folder:  python3 oversight/viewer/summary.py"""
import json, os, sys, collections
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # task root
p = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "oversight", "events.jsonl")
evs = [json.loads(l) for l in open(p) if l.strip()]


def bw(e):
    """Files this event wrote, via Write/Edit tools OR inside Bash (see record.py).
    Ambiguous Bash diffs taken while a subagent was running are skipped - they cannot be
    attributed to one node (analyze.py reports them separately)."""
    out = set()
    fp = (e.get("tool_input") or {}).get("file_path")
    if e.get("ov_event") == "pre_tool" and e.get("tool_name") in ("Edit", "Write", "MultiEdit") and fp:
        out.add(os.path.relpath(fp, ROOT) if os.path.isabs(fp) else fp)
    if not e.get("ov_bash_writes_ambiguous"):
        out |= set(e.get("ov_bash_writes") or [])
    return out


def br(e):
    out = set()
    fp = (e.get("tool_input") or {}).get("file_path")
    if e.get("ov_event") == "pre_tool" and e.get("tool_name") == "Read" and fp:
        out.add(os.path.relpath(fp, ROOT) if os.path.isabs(fp) else fp)
    out |= set(e.get("ov_bash_reads") or [])
    return out


def unnamed(e):
    """Files written but not named by the command: ambiguous diffs plus the dropped remainder
    of a mixed command. Attributable only when no other agent's window covers them."""
    out = set(e.get("ov_bash_writes_dropped") or [])
    if e.get("ov_bash_writes_ambiguous"):
        out |= set(e.get("ov_bash_writes") or [])
    return out


def human(e):
    t = (e.get("prompt") or "").lstrip()
    return bool(t) and not t.startswith("<task-notification") and "<task-id>" not in t[:200]
by = collections.defaultdict(list)
for e in evs: by[e.get("ov_session_no", 1)].append(e)
agents = {}
for n, es in sorted(by.items()):
    tools = [e for e in es if e["ov_event"] == "pre_tool"]
    spawns = [e for e in es if e["ov_event"] == "subagent_start"]
    writes = set().union(*[bw(e) for e in es]) if es else set()
    dur = (es[-1]["ov_ts"] - es[0]["ov_ts"]) / 60000 if es else 0
    un = collections.defaultdict(set)
    for e in es:
        for f in unnamed(e):
            un[f].add(e.get("agent_id") or "main")
    likely = {f for f, ag in un.items() if f not in writes and len(ag) == 1}
    unattr = {f for f, ag in un.items() if f not in writes and len(ag) > 1}
    print(f"session {n}: {dur:.0f} min, {len(tools)} tool calls, {len(spawns)} subagents, {len(writes - {None})} files written")
    if likely or unattr:
        print(f"   attribution: {len(writes - {None})} confident, {len(likely)} likely (unnamed, sole window), {len(unattr)} unattributed")
    for e in [x for x in es if x["ov_event"] == "prompt" and human(x)]:
        print(f"   human: {(e.get('prompt') or '')[:100]!r}")
    for e in spawns:
        a = e.get("agent_id"); agents[a] = n
        w = set().union(*[bw(x) for x in es if x.get("agent_id") == a]) if any(x.get("agent_id") == a for x in es) else set()
        r = set().union(*[br(x) for x in es if x.get("agent_id") == a]) if any(x.get("agent_id") == a for x in es) else set()
        print(f"   subagent {a} ({e.get('agent_type')}): wrote {sorted(os.path.basename(x) for x in w)}, read {len(r)} files")
    compacts = sum(1 for e in es if e["ov_event"] == "pre_compact")
    if compacts: print(f"   context compactions: {compacts}")
if len(by) > 1:
    s1_writes = set().union(*[bw(e) for e in by[1]]) if by.get(1) else set()
    later = [e for n, es in by.items() if n > 1 for e in es]
    reads = (set().union(*[br(e) for e in later]) if later else set()) & s1_writes
    rewr = (set().union(*[bw(e) for e in later]) if later else set()) & s1_writes
    print(f"handoff: session 2+ read {len(reads)} of session 1's {len(s1_writes)} files and re-wrote {len(rewr)} of them")
