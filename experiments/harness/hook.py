#!/usr/bin/env python3
"""PreToolUse hook for every tool call, by the lead and by every subagent.

Three jobs:
  1. Log the call (who made it, which tool, the full input) to $IB_LOG. Briefs are the `prompt` of
     Task/Agent calls, so this log is enough to see whether the user's constraint was passed down
     and who edited what.
  2. Run Bash inside the task's container. Claude Code runs on the host, the repo is bind-mounted at
     the same path in the container, so only the command has to move.
  3. In the multi condition, stop the lead from editing or running anything itself, so the work has
     to go through subagents. Edits outside the workspace are refused in both conditions.
"""
import json, os, shlex, sys, time

data = json.load(sys.stdin)
tool = data.get("tool_name", "")
inp = data.get("tool_input") or {}
agent = data.get("agent_id") or "main"
ws = os.environ["IB_WS"]
ctr = os.environ["IB_CONTAINER"]
mode = os.environ.get("IB_MODE", "single")


def log(decision, extra=None):
    rec = dict(ts=time.time(), agent=agent, agent_type=data.get("agent_type"), tool=tool,
               input=inp, decision=decision)
    if extra:
        rec.update(extra)
    with open(os.environ["IB_LOG"], "a") as f:
        f.write(json.dumps(rec) + "\n")


def out(decision, reason=None, updated=None):
    h = {"hookEventName": "PreToolUse", "permissionDecision": decision}
    if reason:
        h["permissionDecisionReason"] = reason
    if updated is not None:
        h["updatedInput"] = updated
    print(json.dumps({"hookSpecificOutput": h}))
    sys.exit(0)


ACTING = ("Bash", "Edit", "Write", "MultiEdit", "NotebookEdit")
PATH_KEYS = ("file_path", "notebook_path", "path")


def to_host(p):
    """The agent sees /testbed in test output; on the host the same file is under the workspace."""
    if p == "/testbed" or p.startswith("/testbed/"):
        return ws + p[len("/testbed"):]
    return p


# Paths the agent copied from container output point at /testbed; send them to the workspace.
mapped = {k: to_host(inp[k]) for k in PATH_KEYS if isinstance(inp.get(k), str) and to_host(inp[k]) != inp[k]}
if mapped:
    inp = dict(inp, **mapped)

if mode == "multi" and agent == "main" and tool in ACTING:
    log("deny-lead")
    out("deny", "As the lead you do not edit files or run commands yourself. "
                "Delegate this to a subagent with the Task tool.")

if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
    p = os.path.realpath(inp.get("file_path") or inp.get("notebook_path") or "")
    if not (p == ws or p.startswith(ws + os.sep)):
        log("deny-outside")
        out("deny", "Only files inside the repository may be changed.")
    log("allow")
    out("allow", updated=inp if mapped else None)

if tool == "Bash":
    cwd = os.path.realpath(data.get("cwd") or ws)
    if not (cwd == ws or cwd.startswith(ws + os.sep)):
        cwd = ws
    cwd = "/testbed" + cwd[len(ws):]
    inner = "source /root/.ib_env; " + inp.get("command", "").replace(ws, "/testbed")
    cmd = "docker exec -w %s %s bash -c %s" % (shlex.quote(cwd), ctr, shlex.quote(inner))
    log("allow")
    out("allow", updated=dict(inp, command=cmd))

log("allow")
out("allow", updated=inp if mapped else None)
