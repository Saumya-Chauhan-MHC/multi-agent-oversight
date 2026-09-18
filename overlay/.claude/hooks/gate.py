#!/usr/bin/env python3
"""Split gate (PreToolUse, matcher Agent|Task).

Runs on every proposed subagent spawn.

  Always   the split's forward impact is computed and recorded as a `split_proposed` event, so
           the viewer can surface it whether or not the run is paused.
  Gate on  (oversight/gate_mode = "on") the spawn is also PAUSED until a human decides, from the
           viewer or `python3 oversight/ctl.py`. The agent is genuinely blocked: this hook does not
           return until a decision file appears. It never proceeds on its own; if no decision ever
           arrives it denies the spawn.

Decisions:
  accept       the hook returns nothing and the spawn proceeds
  accept_all   as accept, and every further spawn from the same parent proceeds without pausing
               until that parent finishes (a standing approval the human chose explicitly)
  modify       denied; the agent reads the human's note as the reason and re-plans
  reject       denied; the agent is told not to run it
  reset        the workspace is restored to a checkpoint first, then the spawn is denied with why

Agents propose a split one child per message (the last run: nine lexers over 146 s), so a human
deciding the first child has not seen the rest. The request therefore carries the parent's stated
plan (the text it wrote just before spawning) and the children accepted so far.

Time spent paused is added to the session's cap start, so waiting for a human is not charged to
the agent.
"""
import sys, json, os, time, glob

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
if data.get("tool_name") not in ("Agent", "Task"):
    sys.exit(0)
root = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
ov = os.path.join(root, "oversight")


def read(p, default=""):
    try:
        return open(p).read().strip()
    except Exception:
        return default


gate_on = read(os.path.join(ov, "gate_mode"), "off") == "on"
try:
    no = int(read(os.path.join(ov, "session_no.txt"), "1"))
except Exception:
    no = 1


# Fail closed. Claude Code lets a tool call proceed when its hook crashes or is killed (tested: a
# hook killed by its timeout let the spawn run). With the gate on, an unreviewed spawn slipping
# through is the failure we most want to avoid, so any unexpected error denies instead.
def _fail_closed(exc_type, exc, tb):
    if gate_on:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
              "permissionDecisionReason": f"The oversight gate hit an internal error ({exc_type.__name__}: {exc}) "
              "and held this spawn rather than let it through unreviewed. Tell the human; do not retry "
              "until they have looked."}}))
    sys.exit(0)


sys.excepthook = _fail_closed

sys.path.insert(0, ov)
import control  # noqa: E402

ti = data.get("tool_input") or {}
nodes, live = control.build()
caller = (live.get(data.get("agent_id")) if data.get("agent_id") else None) or f"main:{no}"
desc, prompt = ti.get("description") or "", ti.get("prompt") or ""


def stated_plan():
    """The text the parent wrote in or just before the message that proposes this spawn."""
    tp = data.get("transcript_path") or ""
    if data.get("agent_id") and tp.endswith(".jsonl"):
        hits = glob.glob(os.path.join(tp[:-6], "subagents", f"agent-{data['agent_id']}*.jsonl"))
        tp = hits[0] if hits else ""
    if not tp or not os.path.exists(tp):
        return ""
    try:
        msgs = [json.loads(l) for l in open(tp) if l.strip()]
    except Exception:
        return ""
    tid = data.get("tool_use_id")
    idx = len(msgs)
    for i, m in enumerate(msgs):
        for c in ((m.get("message") or {}).get("content") or []):
            if isinstance(c, dict) and c.get("type") == "tool_use" and c.get("id") == tid:
                idx = i + 1
    texts = []
    for m in reversed(msgs[max(0, idx - 6):idx]):
        if m.get("type") != "assistant":
            continue
        t = " ".join(c.get("text", "") for c in ((m.get("message") or {}).get("content") or [])
                     if isinstance(c, dict) and c.get("type") == "text").strip()
        if t:
            texts.append(t)
        if len(texts) >= 2:
            break
    return "\n\n".join(reversed(texts))[:1200]


impact = control.split_impact(caller, desc, prompt)
impact["stated_plan"] = stated_plan()
impact["split_so_far"] = [dict(key=k, label=control.label(nodes, k), status=nodes[k]["status"])
                          for k in nodes if nodes[k].get("parent") == caller]
# pros / cons (spec: for splits only). Always computed and recorded; shown when recommend_mode is on.
impact.update(control.recommendations(caller, prompt, impact["files_in_scope"],
                                      [x["key"] for x in impact["split_so_far"]], impact["stated_plan"]))

# impact is always surfaced: record it whether or not the run will pause
with open(os.path.join(ov, "events.jsonl"), "a") as f:
    f.write(json.dumps(dict(ov_event="split_proposed", ov_ts=control.now_ms(), ov_session_no=no,
                            session_id=data.get("session_id", "control"), agent_id=data.get("agent_id"),
                            tool_use_id=data.get("tool_use_id"), description=desc, caller=caller,
                            gated=gate_on, impact=impact)) + "\n")
if not gate_on:
    sys.exit(0)

# do not pause a call the time cap is about to deny anyway
try:
    cap = int(read(os.path.join(ov, "cap_minutes"), "0"))
    start = int(read(os.path.join(ov, f"cap_start_{no}.txt"), str(int(time.time()))))
    paused = int(read(os.path.join(ov, f"paused_{no}.txt"), "0"))
    if cap > 0 and cap * 60 - (int(time.time()) - start - paused) <= 0:
        sys.exit(0)
except Exception:
    pass

# a standing approval the human chose explicitly: "accept all further spawns from this parent"
sa = os.path.join(control.CTL, f"standing_{control._safe(caller)}.json")
if os.path.exists(sa):
    par = nodes.get(caller)
    if par and par["status"] == "running":
        control.record("split", "agent", caller, impact, "accept (standing approval)",
                       control.latest_checkpoint(), control.latest_checkpoint(),
                       "covered by the human's accept-all for this parent", dict(parent=caller, child=desc))
        sys.exit(0)
    try:
        os.remove(sa)          # the parent finished; the approval does not outlive it
    except Exception:
        pass

rid = f"s{no}-{int(time.time() * 1000)}-{os.getpid()}"
req = dict(rid=rid, ts=control.now_ms(), session=no, caller=caller, description=desc,
           prompt=prompt, subagent_type=ti.get("subagent_type"), impact=impact)
pp = os.path.join(control.PENDING, f"{rid}.json")
json.dump(req, open(pp, "w"), indent=1)

# Wait for a human. There is no auto-proceed: only a decision releases the spawn. The deadline sits
# just under the hook's own timeout in settings.json (86400 s), and reaching it DENIES the spawn.
deadline = int(read(os.path.join(ov, "gate_timeout"), "86000") or 86000)
dp = os.path.join(control.DECISIONS, f"{rid}.json")
t0 = time.time()
dec = None
while time.time() - t0 < deadline:
    if os.path.exists(dp):
        try:
            dec = json.load(open(dp))
            break
        except Exception:
            pass
    time.sleep(0.5)
waited = int(time.time() - t0)

pf = os.path.join(ov, f"paused_{no}.txt")
try:
    total = int(read(pf, "0") or 0) + waited      # read BEFORE opening for write, which truncates
    open(pf, "w").write(str(total))
except Exception:
    pass
try:
    os.remove(pp)
except Exception:
    pass


def deny(reason):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                             "permissionDecision": "deny",
                                             "permissionDecisionReason": reason}}))
    sys.exit(0)


if dec is None:
    control.record("split", "agent", caller, impact, "no decision (denied)", control.latest_checkpoint(),
                   control.latest_checkpoint(), f"no human decision within {deadline}s",
                   dict(request=rid, parent=caller, child=desc))
    deny("This spawn was held for human review and no decision arrived, so it was not started. "
         "Continue without it, or propose it again later.")

d, note = dec.get("decision"), (dec.get("note") or "").strip()
if d in ("accept", "accept_all"):
    sys.exit(0)
if d == "modify":
    deny("A human reviewing this split asked for changes before it runs:\n" + (note or "(no details)") +
         "\nRevise the delegation accordingly and re-issue the Agent call, or do the work yourself if that is what they asked.")
if d == "reject":
    deny("A human reviewing this split rejected it" + (f": {note}" if note else ".") +
         " Do not spawn this subagent; continue without it.")
if d == "reset":
    deny(f"A human reset the workspace to checkpoint {dec.get('reset_to') or 'an earlier point'}: every file "
         "changed after that point was restored to its earlier state, so recent edits are gone. "
         "Re-check the workspace and re-plan from the restored state before delegating."
         + (f" Their note: {note}" if note else ""))
sys.exit(0)
