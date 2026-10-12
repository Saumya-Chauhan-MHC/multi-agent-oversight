#!/usr/bin/env python3
"""SubagentStop: the one trigger that fires on a claim rather than an action.

An agent saying it is finished is a decision too: if what it depends on moved after its last
green run and nothing wider has been checked since, the claim is stale and the correction is to
re-verify rather than to stop writing.
"""
import sys, json, os, time

def _fail_open(*a):
    sys.exit(0)


sys.excepthook = lambda *a: sys.exit(0)
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
PROJ = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
sys.path.insert(0, PROJ)
sys.path.insert(0, os.path.join(PROJ, "oversight"))
try:
    from oversight.v3 import taskmodel as tmod, filter as filt, policy, judge3
    from oversight import align
except Exception:
    sys.exit(0)

tm = tmod.load(PROJ)
if not tmod.preferences(tm):
    sys.exit(0)
events = align.load_events(PROJ)
who = data.get("agent_id") or "orchestrator"
trigger = filt.completion_check(tm, events, who)
if not trigger:
    sys.exit(0)

d = trigger["detail"]
action = ("%s claims done. Its last passing test run was at %s; %s changed %s at %s; "
          "no wider check has run since." % (who, d["my_last_pass"], d["by"], d["file"], d["at"]))
verdict = judge3.judge(tm, action, trigger, "", {"name": who})
band = policy.band(verdict, PROJ)
flag = dict(rid="done-%d" % int(time.time() * 1000), ts=policy.now(), agent=who, tool="completion",
            action=action[:300], trigger="stale_claim", risk="miscoordination", band=band,
            **{k: verdict.get(k) for k in ("verdict", "confidence", "prefs", "evidence", "metric",
                                           "consequence", "correction", "cost", "source")})
align.append_event(PROJ, dict(ov_event="v3_judgement", **flag))
if band == "silent":
    sys.exit(0)
policy.enqueue(PROJ, flag)
sys.exit(0)
