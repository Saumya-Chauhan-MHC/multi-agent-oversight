#!/usr/bin/env python3
"""A stdio MCP server with one tool, `ask_user`, so a headless run has a way to ask the user.

`claude -p` has no AskUserQuestion, so in every headless run an agent that wanted a decision from the
user could only stop and say so. This puts the channel back: the agent asks, a simulated user answers
in the user's own words from the run's intent card, and the agent carries on. Every question and
answer goes to $IB_ASK_LOG.

The simulated user (Claude Code headless, no tools) sees only the intent card, the task as the user
sent it, and the question. It answers what the card says, says "I don't know" or "your call" for what
the card does not cover, and never volunteers instructions beyond the card. If it fails, the answer is
the card itself, verbatim.

Environment: IB_INTENT (the card text), IB_TASK (the user's prompt), IB_ASK_LOG, IB_SIMUSER_MODEL.
hook.py keeps the tool for the lead only (IB_ASK_SUBAGENTS=1 lifts that): in Claude Code subagents
cannot ask the user either.
"""
import json, os, subprocess, sys, tempfile, time

MODEL = os.environ.get("IB_SIMUSER_MODEL", "claude-sonnet-5")
TOOL = {
    "name": "ask_user",
    "description": ("Ask the user a question and wait for their answer. Use it when you need a decision or "
                    "information only the user has. The user sees only your question, so make it "
                    "self-contained; offer options if there are any."),
    "inputSchema": {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]},
}

SYSTEM = """You are the developer who gave a coding agent a task. The agent has paused to ask you something.

What you want, in your own words (this is everything you know you want):
{intent}

Answer the agent's question as this developer would, in one to three short sentences, plainly.
- Say what your words above say, applied to the question.
- If the question is about something your words above do not settle, say you don't mind / it's the
  agent's call, or give the obvious answer a developer would; do not invent new requirements.
- Do not do the task, do not mention being simulated, do not add instructions beyond your words above."""


def answer(question):
    intent, task = os.environ.get("IB_INTENT", ""), os.environ.get("IB_TASK", "")
    user = "THE TASK YOU SENT THE AGENT:\n%s\n\nTHE AGENT ASKS:\n%s" % (task[:4000], question[:4000])
    env = dict(os.environ, MAX_THINKING_TOKENS="0")
    for k in ("CLAUDE_PROJECT_DIR", "IB_WS", "IB_CONTAINER", "IB_LOG"):
        env.pop(k, None)
    cmd = ["claude", "-p", "--output-format", "json", "--model", MODEL, "--strict-mcp-config",
           "--setting-sources", "", "--disallowedTools", "Bash", "Edit", "Write", "Read", "Glob", "Grep",
           "Task", "Agent", "WebFetch", "WebSearch", "NotebookEdit",
           "--append-system-prompt", SYSTEM.format(intent=intent)]
    t0 = time.time()
    try:
        p = subprocess.run(cmd, input=user, capture_output=True, text=True, timeout=120, env=env,
                           cwd=tempfile.gettempdir())
        text = json.loads(p.stdout).get("result") if p.returncode == 0 else None
        src = "simuser" if text else "card"
    except Exception:
        text, src = None, "card"
    text = (text or "").strip() or intent
    return text, src, round(time.time() - t0, 1)


def send(msg):
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        try:
            m = json.loads(line)
        except Exception:
            continue
        mid, meth = m.get("id"), m.get("method")
        if meth == "initialize":
            send(dict(jsonrpc="2.0", id=mid, result=dict(
                protocolVersion=(m.get("params") or {}).get("protocolVersion", "2024-11-05"),
                capabilities={"tools": {}}, serverInfo={"name": "user", "version": "1"})))
        elif meth == "tools/list":
            send(dict(jsonrpc="2.0", id=mid, result={"tools": [TOOL]}))
        elif meth == "tools/call":
            q = ((m.get("params") or {}).get("arguments") or {}).get("question", "")
            a, src, secs = answer(q)
            log = os.environ.get("IB_ASK_LOG")
            if log:
                with open(log, "a") as f:
                    f.write(json.dumps(dict(ts=time.time(), question=q, answer=a, source=src, secs=secs)) + "\n")
            send(dict(jsonrpc="2.0", id=mid, result={"content": [{"type": "text", "text": a}]}))
        elif mid is not None:
            if meth == "ping":
                send(dict(jsonrpc="2.0", id=mid, result={}))
            else:
                send(dict(jsonrpc="2.0", id=mid, error={"code": -32601, "message": "method not found"}))


if __name__ == "__main__":
    main()
