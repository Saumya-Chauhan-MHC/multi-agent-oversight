#!/usr/bin/env python3
"""Render the control-vs-treatment comparison and the real-grader results."""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ARMS = json.load(open(os.path.join(ROOT, "arms.json")))
A, B = ARMS["control"], ARMS["treatment"]


def rep(arm):
    p = os.path.join(arm["dir"], "grade", "report.json")
    return json.load(open(p)) if os.path.exists(p) else {}


RA, RB = rep(A), rep(B)

out = []
w = out.append

w("# Two arms, and the real verifier")
w("")
w("## Why there are two arms")
w("")
w("The trajectory the golden set is annotated against came from a run with the v2 hooks installed.")
w("Those hooks judged 37 decisions and put **every one of them in the silent band**: zero holds,")
w("zero checks, zero `permissionDecision` fields, nothing printed. So the agent was never")
w("interrupted and never waited, which is most of what matters.")
w("")
w("But not all of it. That run also had `inject.py` on `SessionStart`, which put five preference")
w("lines into the orchestrator's opening context. The agent read them. That is a real confound: a")
w("run told \"a subagent never edits a file it does not own\" is not a run that was told nothing,")
w("even if nothing was ever enforced. Calling it a clean control would have been wrong.")
w("")
w("So both arms were run fresh, same task, same brief, same contracts file, same budget:")
w("")
w("| | control | treatment |")
w("|---|---|---|")
w("| hooks | `record.py` only, on every event | the full v3 set: `v3_gate` on PreToolUse, `v3_land` on PostToolUse, `v3_done` on SubagentStop |")
w("| anything injected into the agent's context | **nothing** | nothing (v3 does not inject; the preferences are the tool's, not the agent's) |")
w("| anything that can pause a tool call | **nothing** | `v3_gate`, at the hold band |")
w("| task model | none | extracted from `PROMPT.md` + `CONTRACTS.md` before the run |")
w("")
w("Recording-only is not the same as no tool at all, and the difference is worth stating: the hooks")
w("still run, so each tool call pays a few milliseconds. They return nothing, decide nothing and")
w("say nothing. An unobserved run cannot be annotated, so this is the closest thing to a control")
w("that produces a labellable trajectory.")
w("")

w("## What the two runs did")
w("")
w("| | control (no tool) | treatment (v3) |")
w("|---|---|---|")
for name, key in (("events recorded", "events"), ("decisions judged-eligible", "decisions"),
                  ("all tool calls", "tool_calls"), ("subagents spawned", "spawns"),
                  ("files written or edited", "files_touched"),
                  ("wall clock, minutes", "minutes"),
                  ("judge calls", "judgements"), ("reached the user", "shown")):
    w("| %s | %s | %s |" % (name, A.get(key), B.get(key)))
w("")
if B.get("bands"):
    w("Treatment bands: %s." % B["bands"])
    w("")

w("## The real verifier, minus the Computer-Use rubric")
w("")
w("The official grader is `tasks/slack-clone/tests/test.sh`, a container entrypoint. It boots the")
w("agent's `start.sh`, runs five correctness gates as pytest suites, and then blends a Computer-Use")
w("rubric into the reward 50/50. `eval/grader/run_gates.py` runs the five correctness gates and")
w("nothing else: the CUA verifier is excluded, and the two Playwright gates (`test_e2e.py`,")
w("`journey_*.py`) need a chromium build this machine does not have and are reported as not run")
w("rather than quietly dropped.")
w("")
w("| Gate | Official files | What it establishes |")
w("|---|---|---|")
w("| api | `test_api.py`, `test_profiles.py`, `test_read_state.py`, `test_channels_extra.py`, `test_files.py`, `test_slash.py`, `test_groups.py`, `test_invitations.py`, `test_roles.py`, `test_cluster.py`, `test_ordering.py`, `test_load.py` | auth, channels, messages, threads, reactions, DMs, search, permissions, live WebSocket fan-out, dense per-channel `seq` |")
w("| irc | `test_irc.py` | RFC 2812 subset and bidirectional bridging with web messages |")
w("| crash | `test_crash.py` | SIGKILL an HTTP node; the other two keep serving and `start.sh` respawns it |")
w("| chaos | `test_chaos.py` | SIGKILL redis; fan-out recovers through the SQLite fallback within 5s |")
w("| frontend | `test_frontend.py` | SPA structure, served and parseable, no browser needed |")
w("")
w("These are black-box HTTP, WebSocket and IRC socket tests against `127.0.0.1:8000`. They do not")
w("read the implementation, so they are indifferent to how the work was divided, which is what makes")
w("them usable as a task-success metric for an oversight experiment.")
w("")

w("### Results")
w("")
w("| | control | treatment |")
w("|---|---|---|")
w("| `start.sh` present | %s | %s |" % (RA.get("start_sh_present"), RB.get("start_sh_present")))
w("| booted via | %s | %s |" % (RA.get("booted_via"), RB.get("booted_via")))
w("| three nodes healthy | %s%s | %s%s |" % (
    RA.get("health"), "" if RA.get("health_seconds") is None else " (%ss)" % RA["health_seconds"],
    RB.get("health"), "" if RB.get("health_seconds") is None else " (%ss)" % RB["health_seconds"]))
w("| IRC port open | %s | %s |" % (RA.get("irc_port_open"), RB.get("irc_port_open")))
w("| anti-cheat | %s | %s |" % (RA.get("anti_cheat"), RB.get("anti_cheat")))
w("| gates passed | %s/%s | %s/%s |" % (RA.get("gates_passed"), RA.get("gates_total"),
                                        RB.get("gates_passed"), RB.get("gates_total")))
w("| tests passed | %s/%s | %s/%s |" % (RA.get("tests_passed"), RA.get("tests_total"),
                                        RB.get("tests_passed"), RB.get("tests_total")))
w("| official reward (binary) | %s | %s |" % (RA.get("official_reward"), RB.get("official_reward")))
w("")
w("Per gate, tests passed of total:")
w("")
w("| gate | control | treatment |")
w("|---|---|---|")
ga = {g["gate"]: g for g in RA.get("gates", [])}
gb = {g["gate"]: g for g in RB.get("gates", [])}
for k in ("api", "irc", "crash", "chaos", "frontend"):
    f = lambda g: "-" if k not in g else "%s/%s%s" % (g[k]["passed"], g[k]["total"],
                                                      "" if g[k]["ok"] else "  (gate failed)")
    w("| %s | %s | %s |" % (k, f(ga), f(gb)))
w("")

w("## What one pair of runs can and cannot show")
w("")
w("**Cannot:** that the tool improved or harmed task success. Two runs of one task differ for many")
w("reasons, and with n=1 per arm there is no way to separate the tool from the variance. Any gate")
w("difference below is a description of these two runs.")
w("")
w("**Can:** three things worth having.")
w("")
w("1. **Whether the tool costs anything obvious.** Wall clock, judge-call volume, and whether the")
w("   run completed at all are directly observable on one pair.")
w("2. **Whether the surfaced decisions were about things that mattered.** This is the useful")
w("   comparison: take what the tool said in the treatment arm, then read the treatment arm's gate")
w("   failures, and ask whether they are the same subject. That is a claim about relevance, not")
w("   about effect size, and one run can support it.")
w("3. **Whether the task produces fan-out at all.** Both arms spawned subagents, which matters")
w("   because the three purpose-built tasks earlier in this project produced zero spawns between")
w("   them. The slack-clone brief does divide work, so it is the right subject for this tool.")
w("")

open(os.path.join(HERE, "ARMS_AND_GRADER.md"), "w").write("\n".join(out) + "\n")
print("wrote ARMS_AND_GRADER.md (%d lines)" % len(out))
