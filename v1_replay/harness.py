#!/usr/bin/env python3
"""Offline replay: feed a frozen trajectory to a tool adapter one event at a time.

  python3 harness.py --trajectory DIR --prompt PROMPT.md --rules RULES.json --run N
                     [--quiet 120] [--judge claude-sonnet-5] [--limit K] --out FILE

Rules: no lookahead (the tool's log holds only events before the current one), the recorded
clock, no user answers, a fresh folder per run. The harness never reads the labels.
"""
import argparse, json, os, shutil, tempfile, time
from adapter_v6 import V6

ACTS = ("Bash", "Write", "Edit", "MultiEdit", "Task", "Agent")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trajectory", required=True); ap.add_argument("--prompt", required=True)
    ap.add_argument("--rules", required=True); ap.add_argument("--run", type=int, default=1)
    ap.add_argument("--quiet", type=int, default=120); ap.add_argument("--judge", default="claude-sonnet-5")
    ap.add_argument("--limit", type=int); ap.add_argument("--out", required=True)
    a = ap.parse_args()
    lines = open(os.path.join(a.trajectory, "events.jsonl")).read().splitlines()
    orig_root = json.loads(lines[0]).get("cwd")
    work = tempfile.mkdtemp(prefix="replay_v6_run%d_" % a.run)
    shutil.rmtree(work); os.makedirs(work)
    tool = V6()
    tool.setup(work, a.prompt, dict(quiet_s=a.quiet, judge_model=a.judge, rules_file=a.rules, tool_commit="1639cf9"))
    hist = os.path.join(work, "oversight", "events.jsonl")
    t0 = json.loads(lines[0])["ov_ts"]
    out = open(a.out, "w"); n = 0; start = time.time()
    for idx, raw in enumerate(lines):
        # the run's own folder becomes the replay folder, as CLAUDE_PROJECT_DIR == cwd in a live run
        line = raw.replace(orig_root, work)
        e = json.loads(line)
        if e.get("ov_event") == "pre_tool" and e.get("tool_name") in ACTS:
            if a.limit and n >= a.limit:
                break
            row = tool.decide(e, hist, e["ov_ts"] / 1000.0, idx)
            row = dict(idx=idx, t_s=round((e["ov_ts"] - t0) / 1000), agent=(e.get("agent_id") or "orchestrator")[:8],
                       tool=e.get("tool_name"), action=str((e.get("tool_input") or {}).get("command") or
                       (e.get("tool_input") or {}).get("file_path") or (e.get("tool_input") or {}).get("description") or "")
                       .replace(work, ".")[:160], **row)
            out.write(json.dumps(row) + "\n"); out.flush(); n += 1
            if row["stage"] not in ("filtered", "no_finding"):
                print("%4d %4ss %-8s %-18s %s" % (idx, row["t_s"], row["agent"], row["stage"], row["action"][:70]), flush=True)
        with open(hist, "a") as f:            # appended after the decision: the tool never sees t itself
            f.write(line + "\n")
    print("run %d: %d decision points in %.1f min, workdir %s" % (a.run, n, (time.time() - start) / 60, work))


if __name__ == "__main__":
    main()
