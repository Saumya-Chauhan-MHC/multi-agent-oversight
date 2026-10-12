"""Running Claude Code on a task, and reading what it produced.

Two modes: headless (`claude -p`, stream-json to stream.jsonl) and interactive (Claude Code's own UI
in the user's terminal; the transcript is turned into the same stream.jsonl afterwards). Both use
hook.py on every tool call, by the lead and by every subagent.
"""
import glob, json, os, shlex, shutil, subprocess, sys, time, uuid

HERE = os.path.dirname(os.path.realpath(__file__))
HOOK = os.path.join(HERE, "hook.py")


def claude_args(cond, model):
    """The flags both modes share: our hook, no web, no scheduling, project settings only."""
    settings = {"hooks": {"PreToolUse": [{"matcher": "*", "hooks": [
        {"type": "command", "command": "%s %s" % (shlex.quote(sys.executable), shlex.quote(HOOK))}]}]}}
    # Scheduling tools make no sense in -p and the lead reached for ScheduleWakeup while waiting.
    disallowed = ["WebFetch", "WebSearch", "ScheduleWakeup", "CronCreate", "Monitor", "RemoteTrigger"]
    if cond == "single":
        disallowed += ["Task", "Agent"]
    args = ["--setting-sources", "project", "--settings", json.dumps(settings), "--strict-mcp-config",
            "--permission-mode", "acceptEdits", "--disallowedTools", *disallowed]
    if model:
        args += ["--model", model]
    return args


def claude_env(cond, ctr, ws, run_dir):
    # -p kills background subagents 600 s after the lead's last turn ("Background tasks still running
    # after 600s; terminating"); the run then ends mid-task. Our --timeout bounds the run instead.
    return dict(os.environ, CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS="0", IB_WS=ws, IB_CONTAINER=ctr, IB_MODE=cond,
                IB_LOG=os.path.join(run_dir, "tools.jsonl"))


def run_headless(prompt, cond, model, ctr, ws, run_dir, timeout):
    args = ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose"] + claude_args(cond, model)
    t0 = time.time()
    with open(os.path.join(run_dir, "stream.jsonl"), "w") as so, open(os.path.join(run_dir, "claude.stderr"), "w") as se:
        try:
            p = subprocess.run(args, cwd=ws, env=claude_env(cond, ctr, ws, run_dir), stdout=so, stderr=se,
                               timeout=timeout, stdin=subprocess.DEVNULL)
            rc = p.returncode
        except subprocess.TimeoutExpired:
            rc = "timeout"
    return rc, time.time() - t0


def run_interactive(prompt, cond, model, ctr, ws, run_dir):
    """Claude Code's own terminal UI, attached to the user's terminal, with the task as the first
    message. The user watches, answers the tool's questions in Claude Code's dialog, and ends the
    session with /exit. Afterwards the session transcript is turned into stream.jsonl so that
    scoring, judging and the timeline work as for a -p run."""
    sid = str(uuid.uuid4())
    t0 = time.time()
    p = subprocess.run(["claude", prompt, "--session-id", sid] + claude_args(cond, model),
                       cwd=ws, env=claude_env(cond, ctr, ws, run_dir))
    secs = time.time() - t0
    stream_from_transcript(sid, run_dir)
    return p.returncode, secs


def stream_from_transcript(sid, run_dir):
    """Rebuild the -p stream format from ~/.claude/projects/*/<sid>.jsonl and its subagents/ files:
    assistant and user messages (subagent ones carry parent_tool_use_id), one task record per
    subagent with its brief's description, and the lead's last text as the result."""
    main = glob.glob(os.path.expanduser("~/.claude/projects/*/%s.jsonl" % sid))
    if not main:
        open(os.path.join(run_dir, "stream.jsonl"), "w").close()
        return
    main = main[0]
    keep = os.path.join(run_dir, "transcript")
    os.makedirs(keep, exist_ok=True)
    shutil.copy2(main, keep)
    out, last = [], ""
    for l in open(main):
        r = json.loads(l)
        if r.get("type") in ("assistant", "user"):
            out.append(dict(type=r["type"], message=r["message"], parent_tool_use_id=None))
            if r["type"] == "assistant":
                for c in r["message"].get("content") or []:
                    if isinstance(c, dict) and c.get("type") == "text" and c["text"].strip():
                        last = c["text"]
    subdir = os.path.join(main[:-len(".jsonl")], "subagents")
    tasks = []
    if os.path.isdir(subdir):
        shutil.copytree(subdir, os.path.join(keep, "subagents"), dirs_exist_ok=True)
    for f in sorted(glob.glob(os.path.join(subdir, "agent-*.jsonl"))):
        aid = os.path.basename(f)[len("agent-"):-len(".jsonl")]
        try:
            meta = json.load(open(f[:-len(".jsonl")] + ".meta.json"))
        except Exception:
            meta = {}
        tasks.append(dict(task_id=aid, task_type="local_agent", description=meta.get("description", "")))
        for l in open(f):
            r = json.loads(l)
            if r.get("type") in ("assistant", "user"):
                out.append(dict(type=r["type"], message=r["message"], parent_tool_use_id=meta.get("toolUseId", aid)))
    with open(os.path.join(run_dir, "stream.jsonl"), "w") as fo:
        fo.write(json.dumps(dict(type="system", subtype="background_tasks_changed", tasks=tasks)) + "\n")
        for r in out:
            fo.write(json.dumps(r) + "\n")
        fo.write(json.dumps(dict(type="result", subtype="success", result=last, source="transcript")) + "\n")


def models_used(run_dir):
    """Models that actually answered, lead and subagents. Claude Code silently maps retired models
    to a current one (claude-opus-4-1 ran as claude-opus-5), so the --model flag is not proof."""
    seen = {}
    for l in open(os.path.join(run_dir, "stream.jsonl")):
        r = json.loads(l)
        if r.get("type") == "assistant":
            m = r["message"].get("model")
            who = "subagent" if r.get("parent_tool_use_id") else "lead"
            seen.setdefault(who, set()).add(m)
    return {k: sorted(v) for k, v in seen.items()}


def final_text(run_dir):
    """The lead's last message to the user."""
    last = ""
    try:
        for l in open(os.path.join(run_dir, "stream.jsonl")):
            r = json.loads(l)
            if r.get("type") == "result":
                last = r.get("result") or last
    except FileNotFoundError:
        pass
    return last


def agent_briefs(run_dir):
    """agent id -> description, from the stream's background task events."""
    out = {}
    try:
        for l in open(os.path.join(run_dir, "stream.jsonl")):
            r = json.loads(l)
            for t in r.get("tasks") or []:
                if t.get("task_type") == "local_agent":
                    out[t["task_id"]] = t.get("description", "")
            if r.get("subtype") == "task_started" and r.get("task_id"):
                out.setdefault(r["task_id"], r.get("description", ""))
    except FileNotFoundError:
        pass
    return out


def run(prompt, cond, model, ctr, ws, run_dir, timeout, interactive=False):
    """Run the agent and check the run: returns claude_rc, agent_s, models_used, cost_usd and, if
    something makes the run unusable, error. Writes final.txt."""
    if interactive:
        rc, secs = run_interactive(prompt, cond, model, ctr, ws, run_dir)
    else:
        rc, secs = run_headless(prompt, cond, model, ctr, ws, run_dir, timeout)
    out = dict(claude_rc=rc, agent_s=round(secs, 1), models_used=models_used(run_dir))
    for l in open(os.path.join(run_dir, "stream.jsonl")):
        r = json.loads(l)
        if r.get("type") == "result" and r.get("total_cost_usd") is not None:
            out["cost_usd"] = r["total_cost_usd"]
    open(os.path.join(run_dir, "final.txt"), "w").write(final_text(run_dir))
    err = os.path.join(run_dir, "claude.stderr")
    if os.path.exists(err) and "Background tasks still running" in open(err).read():
        out["error"] = "truncated: Claude Code terminated background subagents"
    used = {m for ms in out["models_used"].values() for m in ms}
    if model and "-" in model and used != {model}:
        out["error"] = "model mismatch: asked for %s, got %s" % (model, sorted(used))
    return out
