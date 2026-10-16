#!/usr/bin/env python3
"""Build a SWE-Marathon stripe-clone arm and run it.

Chosen over slack-clone because it grades better on this machine. slack-clone has five gates and
two of them (crash, chaos) need /proc and never ran here, so 40% of the suite was dark. stripe-
clone has twelve gates, all twelve run natively, and the reference solution scores 82 of 83, so
the ceiling is known and nearly perfect. It also ships no Computer-Use verifier, which is what
made the other clone tasks unusable without a browser harness.

  python3 setup_arm.py <name> [--tool] [--minutes N]

--tool wires the v5 gate, which reads instruction.md (copied in as PROMPT.md) and needs no
RULES.md, plus the inbox that delivers its relayed corrections.
"""
import argparse, json, os, shutil, subprocess, sys, time

ROOT = os.path.expanduser("~/research/stripe_arms")
TASK = "/tmp/stripe_task"
OVER = os.path.expanduser("~/research/multi-agent-oversight/overlay")

REC = ["session_start", "prompt", "pre_tool", "post_tool", "subagent_start", "subagent_stop",
       "stop"]
EV = {"session_start": "SessionStart", "prompt": "UserPromptSubmit", "pre_tool": "PreToolUse",
      "post_tool": "PostToolUse", "subagent_start": "SubagentStart",
      "subagent_stop": "SubagentStop", "stop": "Stop"}

# The task is one service, so fan-out has to be asked for. The resource families are the seams
# the instruction itself draws, and they share one storage layer and one error-code convention,
# which is where miscoordination lives.
FANOUT = """

---
Run this as a parallel build. Spawn one subagent per area, in a single message so they work at
the same time, and give each only its own area:

  customers and payment methods      refunds and charges
  payment intents and capture        products, prices and subscriptions
  webhooks, events and restricted keys

They share the storage layer, the id-prefix scheme and the error-code convention described above,
so those have to stay consistent across all of them. Do not have one subagent do everything.
"""


def settings(tool, v3=False):
    h = {}
    for a in REC:
        h.setdefault(EV[a], [{"hooks": []}])[0]["hooks"].append(
            {"type": "command",
             "command": 'python3 "${CLAUDE_PROJECT_DIR}/.claude/hooks/record.py" ' + a})
    if tool:
        py = 'python3 "${CLAUDE_PROJECT_DIR}/.claude/hooks/%s"'
        if v3:
            h["PreToolUse"][0]["hooks"].append(
                {"type": "command", "command": py % "v3_gate.py", "timeout": 180})
            h["PostToolUse"][0]["hooks"].append({"type": "command", "command": py % "v3_land.py"})
            h.setdefault("SubagentStop", [{"hooks": []}])[0]["hooks"].append(
                {"type": "command", "command": py % "v3_done.py", "timeout": 180})
        else:
            h["PreToolUse"][0]["hooks"].append({"type": "command", "command": py % "v5_gate.py"})
        h["PostToolUse"][0]["hooks"].append({"type": "command", "command": py % "inbox.py"})
    return {"hooks": h}


def build(name, tool, v3=False):
    d = os.path.join(ROOT, name)
    if os.path.exists(d):
        sys.exit("%s already exists" % d)
    shutil.copytree(os.path.join(TASK, "environment", "task"), d)
    # v5 reads the task description straight from this file. No RULES.md is written for either
    # arm, and both arms get the identical prompt.
    shutil.copy(os.path.join(TASK, "instruction.md"), os.path.join(d, "PROMPT.md"))
    with open(os.path.join(d, "PROMPT.md"), "a") as f:
        f.write(FANOUT)
    os.makedirs(os.path.join(d, ".claude", "hooks"), exist_ok=True)
    gate_hooks = (["v3_gate.py", "v3_land.py", "v3_done.py", "catchup.py", "inbox.py"] if v3
                  else ["v5_gate.py", "inbox.py"])
    for hk in ["record.py"] + (gate_hooks if tool else []):
        shutil.copy(os.path.join(OVER, ".claude", "hooks", hk), os.path.join(d, ".claude", "hooks"))
    if tool:
        shutil.copytree(os.path.join(OVER, "oversight"), os.path.join(d, "oversight"),
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    json.dump(settings(tool, v3), open(os.path.join(d, ".claude", "settings.json"), "w"), indent=1)
    if tool and v3:
        # v3 indexes on preference objects, which its extractor used to produce from the brief.
        # from_task.py builds the same objects from the task description's own bullets, with no
        # model involved, so the quote is exact by construction. Everything downstream of it in
        # v3 is untouched.
        sys.path.insert(0, os.path.join(d, "oversight"))
        from v3 import from_task
        out, n, src = from_task.write(d)
        print("  task model: %d preferences from %s (no extractor)" % (n, src), flush=True)
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("--tool", action="store_true")
    ap.add_argument("--minutes", type=int, default=75)
    # The AGENTS' model, not the judge's. With Sonnet the control scored 82 of 83, the same as
    # the reference solution, so no tool could show an improvement: there was nothing to improve.
    # A weaker executor lowers the baseline and makes the question a real one. The judge and the
    # stand-in developer stay on sonnet in both arms, so oversight quality is held constant and
    # the only thing varying is the agent doing the work.
    ap.add_argument("--model", default="")
    ap.add_argument("--v3", action="store_true",
                    help="the version on main: queue, three bands, metric gate. Its extractor is "
                         "replaced by from_task.py, which builds the same task model from the "
                         "task description deterministically.")
    a = ap.parse_args()
    d = build(a.name, a.tool, a.v3)
    env = dict(os.environ, CLAUDE_PROJECT_DIR=d)
    if a.tool:
        env["OV_SIMUSER"] = "1"
    print("=== %s: tool=%s%s, model=%s, %d min ===\n%s"
          % (a.name, a.tool, " (v3)" if a.v3 else (" (v5)" if a.tool else ""),
             a.model or "default", a.minutes, d), flush=True)
    t0 = time.time()
    with open(os.path.join(d, "run.log"), "w") as log:
        try:
            cmd = ["claude", "-p", open(os.path.join(d, "PROMPT.md")).read(),
                   "--permission-mode", "acceptEdits"]
            if a.model:
                cmd += ["--model", a.model]
            subprocess.run(cmd,
                           stdout=log, stderr=subprocess.STDOUT, cwd=d, env=env,
                           timeout=a.minutes * 60)
            to = False
        except subprocess.TimeoutExpired:
            to = True
    print("done in %.1f min, timeout=%s" % ((time.time() - t0) / 60, to), flush=True)


if __name__ == "__main__":
    main()
