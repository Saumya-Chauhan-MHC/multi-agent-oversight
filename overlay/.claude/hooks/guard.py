#!/usr/bin/env python3
"""No-internet guard. The official ProgramBench run launches the container with `--network none`
and the rules forbid fetching the project's source. Claude Code on your laptop has network, so this
PreToolUse hook denies the tool calls that would use it:

  * WebFetch / WebSearch tools                          -> always denied
  * Bash commands that download or install from the net -> denied (curl, wget, git clone,
    go get / go install, pip install, cargo install / add, npm install, brew, apt-get)

Everything else is allowed. `go build`, `go mod tidy` on stdlib-only code, `cargo build` with no
dependencies, python3 etc. do not need the network and are not touched.
The deny reason is shown to the agent, so it learns the rule the same way the official prompt states it.
"""
import sys, json, re

try:
    data = json.load(sys.stdin)
except Exception:
    data = {}
tool = data.get("tool_name", "")
inp = data.get("tool_input") or {}

NET = re.compile(
    r"\b(curl|wget|git\s+clone|git\s+fetch|go\s+get|go\s+install\s+\S*@|pip3?\s+install|cargo\s+(install|add)|"
    r"npm\s+(i|install|ci)\b|brew\s+install|apt(-get)?\s+install|gem\s+install)\b")

deny = None
if tool in ("WebFetch", "WebSearch"):
    deny = "No internet access in this task (ProgramBench rule: the executable and its bundled docs are the only sources)."
elif tool == "Bash" and NET.search(inp.get("command", "")):
    deny = ("No internet access in this task: do not download, clone or install anything. "
            "Use only what is already installed and the bundled documentation.")

if deny:
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": deny}}))
sys.exit(0)
