"""Install the oversight tool (overlay/) into a run's workspace, answer its holds, collect its logs.

Used by `run.py --oversight`. The tool is installed the way overlay/README's quick start does it:
.claude/ and oversight/ copied into the project, `ctl.py init` for the user's lines. Three settings
differ from an interactive session, because the run is headless:

  surface_mode = file     -p has no permission dialog, so a held spawn waits for a decision file
                          (ctl.py answer, or the answerer below) instead of Claude Code's prompt
  open_dag_on_hold = off  no browser
  cap_minutes = 0         run.py's own --timeout bounds the run

Action holds are a deny with the evidence as the reason; they need no answer. Spawn holds wait for
one, up to decision_timeout_s, and then proceed unanswered (the tool fails open).
"""
import glob, json, os, shutil, subprocess, sys, threading, time

HERE = os.path.dirname(os.path.realpath(__file__))
OVERLAY = os.path.join(os.path.dirname(os.path.dirname(HERE)), "overlay")


def install(ws, rules, decision_timeout_s=1200, interactive=False, viewer_port=4180):
    """interactive=True keeps the tool's own defaults for a person at the terminal: a held spawn is
    asked in Claude Code's permission dialog (surface_mode ask) and the graph opens on a hold."""
    for d in (".claude", "oversight"):
        shutil.copytree(os.path.join(OVERLAY, d), os.path.join(ws, d),
                        ignore=shutil.ignore_patterns("__pycache__", "memory", "judgements", "control",
                                                      "events.jsonl", "*.pyc"))
    # Keep the tool out of the agent's diff and out of scoring.
    with open(os.path.join(ws, ".git", "info", "exclude"), "a") as f:
        f.write("\n.claude/\noversight/\n")
    answers = {"q1": rules or ""}
    p = subprocess.run([sys.executable, os.path.join(ws, "oversight", "ctl.py"), "init", "--defaults",
                        "--answers", json.dumps(answers)], cwd=ws, capture_output=True, text=True,
                       env=dict(os.environ, CLAUDE_PROJECT_DIR=ws))
    if p.returncode != 0:
        raise RuntimeError("ctl.py init failed:\n" + p.stdout[-2000:] + p.stderr[-2000:])
    sys.path.insert(0, os.path.join(ws, "oversight"))
    try:
        import memory
        memory.MEM = os.path.join(ws, "oversight", "memory")
        memory.SETTINGS = os.path.join(memory.MEM, "settings.json")
        if interactive:
            memory.save_settings(dict(surface_mode="ask", open_dag_on_hold=True, viewer_port=viewer_port))
        else:
            memory.save_settings(dict(surface_mode="file", open_dag_on_hold=False,
                                      decision_timeout_s=decision_timeout_s))
    finally:
        sys.path.pop(0)
    open(os.path.join(ws, "oversight", "cap_minutes"), "w").write("0\n")
    return json.load(open(os.path.join(ws, "oversight", "memory", "session_model.json")))


class Answerer(threading.Thread):
    """A simulated user for held spawns: answers every pending hold with the same decision."""

    def __init__(self, ws, decision, note, log_path, delay_s=5):
        super().__init__(daemon=True)
        self.ws, self.decision, self.note, self.delay_s = ws, decision, note, delay_s
        self.log_path, self.stop_flag, self.seen = log_path, threading.Event(), set()

    def run(self):
        pending = os.path.join(self.ws, "oversight", "control", "pending")
        decisions = os.path.join(self.ws, "oversight", "control", "decisions")
        while not self.stop_flag.is_set():
            for p in glob.glob(os.path.join(pending, "*.json")):
                rid = os.path.basename(p)[:-5]
                if rid in self.seen:
                    continue
                self.seen.add(rid)
                try:
                    req = json.load(open(p))
                except Exception:
                    self.seen.discard(rid)
                    continue
                time.sleep(self.delay_s)
                os.makedirs(decisions, exist_ok=True)
                json.dump(dict(answer=self.decision, note=self.note, ts=int(time.time() * 1000)),
                          open(os.path.join(decisions, rid + ".json"), "w"))
                with open(self.log_path, "a") as f:
                    f.write(json.dumps(dict(ts=time.time(), rid=rid, child=req.get("child"),
                                            answer=self.decision, note=self.note,
                                            evidence=(req.get("judgement") or {}).get("evidence"))) + "\n")
            self.stop_flag.wait(1.0)

    def stop(self):
        self.stop_flag.set()


def human_instructions(ws):
    return ("\noversight is live. A held spawn waits for you (up to the decision timeout). In another terminal:\n"
            "  cd %s\n"
            "  python3 oversight/ctl.py pending\n"
            "  python3 oversight/ctl.py answer <rid> no --note \"...\"     # or accept\n"
            "  python3 oversight/viewer/serve.py 4173                     # optional, the graph\n" % ws)


def start_viewer(ws, port):
    """The tool's graph, served from the workspace, for the person running the session."""
    return subprocess.Popen([sys.executable, os.path.join(ws, "oversight", "viewer", "serve.py"), str(port)],
                            cwd=ws, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def collect(ws, run_dir):
    """Copy what the tool wrote before the workspace is deleted."""
    src, dst = os.path.join(ws, "oversight"), os.path.join(run_dir, "oversight")
    os.makedirs(dst, exist_ok=True)
    for name in ("judgements", "control", "memory", "events.jsonl"):
        s = os.path.join(src, name)
        if os.path.isdir(s):
            shutil.copytree(s, os.path.join(dst, name), dirs_exist_ok=True)
        elif os.path.exists(s):
            shutil.copy2(s, dst)


def summary(run_dir):
    """Holds and checks the tool produced, from its own judgement records."""
    out = dict(holds=0, checks=0, silent_departs=0, judged=0, spawn_holds=0, action_holds=0)
    for p in glob.glob(os.path.join(run_dir, "oversight", "judgements", "*.json")):
        try:
            j = json.load(open(p))
        except Exception:
            continue
        out["judged"] += 1
        if j.get("band") == "hold":
            out["holds"] += 1
            out["action_holds" if j.get("kind") == "action" else "spawn_holds"] += 1
        elif j.get("band") == "check":
            out["checks"] += 1
        elif j.get("verdict") == "departs":
            out["silent_departs"] += 1
    ans = os.path.join(run_dir, "oversight", "answers.jsonl")
    out["answered"] = sum(1 for _ in open(ans)) if os.path.exists(ans) else 0
    return out
