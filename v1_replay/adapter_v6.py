#!/usr/bin/env python3
"""v6 adapter: setup() and decide() around .claude/hooks/v6_gate.py at a pinned commit.

decide() returns one decision-log row. All of it comes from what the tool did:
  stage   filtered | no_finding | judge_cleared | judge_unavailable | queued | shown
  found   the finding this point produced, if any
  shown   notices put in front of the user here, one entry per item in a merged notice
  queue   items waiting per channel afterwards
"""
import json, os, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.expanduser("~/research/multi-agent-oversight/overlay")
ACTS = ("Bash", "Write", "Edit", "MultiEdit", "Task", "Agent")


class V6:
    name = "v6"

    def setup(self, workdir, prompt, config):
        self.w, self.cfg = workdir, config
        os.makedirs(os.path.join(workdir, ".claude", "hooks"))
        shutil.copy(os.path.join(TOOL, ".claude", "hooks", "v6_gate.py"), os.path.join(workdir, ".claude", "hooks"))
        shutil.copytree(os.path.join(TOOL, "oversight"), os.path.join(workdir, "oversight"),
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "snap", "events.jsonl", "tests"))
        shutil.copy(prompt, os.path.join(workdir, "PROMPT.md"))
        shutil.copy(config["rules_file"], os.path.join(workdir, "oversight", "task_model.json"))
        open(os.path.join(workdir, "oversight", "events.jsonl"), "w").close()
        sys.path.insert(0, os.path.join(workdir, "oversight"))
        from v5.context import read_only_command
        self.read_only = read_only_command
        tm = json.load(open(config["rules_file"]))
        self.cat = {p["id"]: p["category"] for p in tm["preferences"]}
        self.pending = []          # findings not yet shown, with the idx where found

    def _queues(self):
        out = {}
        for ch in ("safety", "preference"):
            p = os.path.join(self.w, "control6", "queue_%s.json" % ch)
            out[ch] = json.load(open(p)) if os.path.exists(p) else []
        return out

    def decide(self, payload, history_path, now, idx):
        ti = payload.get("tool_input") or {}
        tool = payload.get("tool_name")
        if tool not in ACTS:
            return dict(stage="filtered", found=[], shown=[], queue={k: len(v) for k, v in self._queues().items()})
        # swe3 round 2: the gate itself exits on read-only commands, after printing any still-open line,
        # so read-only points go through the gate too (the decision is the gate's, as in a live run).
        ro = tool == "Bash" and self.read_only(ti.get("command"))
        before_q = self._queues()
        n0 = sum(1 for _ in open(history_path))
        env = dict(os.environ, CLAUDE_PROJECT_DIR=self.w, OV_REPLAY_NOW=str(now),
                   OV_QUIET_S=str(self.cfg["quiet_s"]), OV_JUDGE_MODEL=self.cfg["judge_model"])
        env.pop("OV_SIMUSER", None)
        p = subprocess.run([sys.executable, os.path.join(HERE, "clock_wrap.py"),
                            os.path.join(self.w, ".claude", "hooks", "v6_gate.py")],
                           input=json.dumps(payload), capture_output=True, text=True, env=env, cwd=self.w, timeout=300)
        new = [json.loads(l) for l in open(history_path).readlines()[n0:]]
        fnd = next((e for e in new if e.get("ov_event") == "v6_finding"), None)
        jud = next((e for e in new if e.get("ov_event") == "v6_judged"), None)
        sur = next((e for e in new if e.get("ov_event") == "v6_surfaced"), None)
        found = []
        if fnd:
            from v6.safety import action_target            # swe3 round 3: same target as the gate
            target = action_target(tool, ti)
            cleared = jud and ((jud.get("kind") == "preference" and not jud.get("departs")) or
                               (jud.get("kind") == "safety" and jud.get("allowed")))
            pid = (jud or {}).get("pid"); pids = (jud or {}).get("pids") or ([pid] if pid else [])
            f = dict(idx=idx, agent=fnd.get("agent"), kind=fnd.get("kind"), risk=fnd.get("risk"),
                     reason=fnd.get("reason"), detail=fnd.get("detail"), action=target, pid=pid, pids=pids,
                     category=self.cat.get(pid) if pid else None, judge_why=(jud or {}).get("why"),
                     cleared=bool(cleared))
            f["key"] = ("risk:%s:%s" % (f["risk"], f["reason"])) if f["kind"] == "safety" else "pref:%s" % (pid or f["reason"])
            found.append(f)
            if not cleared:
                self.pending.append(f)
        shown = []
        if sur:
            key = sur["key"]
            for f in [x for x in self.pending if x["key"] == key]:
                shown.append(dict(found_at=f["idx"], agent=f["agent"], kind=f["kind"], risk=f["risk"],
                                  pid=f["pid"], pids=f.get("pids"), category=f["category"], action=f["action"], detail=f["detail"],
                                  reason=f["reason"]))
                self.pending.remove(f)
        still = next((e for e in new if e.get("ov_event") == "v6_still_open"), None)
        if still and not sur:
            for o in still["items"]:
                shown.append(dict(found_at=None, agent=None, kind=o.get("kind"), risk=o.get("risk"), pid=o.get("pid"), pids=o.get("pids"),
                                  category=o.get("category"), action=o.get("action"), detail=o.get("detail"),
                                  reason="still_open", still_open=True))
        if sur:
            stage = "shown"
        elif still:
            stage = "still_open"
        elif ro:
            stage = "filtered"
        elif fnd and found[0]["cleared"]:
            stage = "judge_cleared"
        elif fnd and jud and str(jud.get("why", "")).startswith("judge unavailable"):
            stage = "judge_unavailable"
        elif fnd:
            stage = "queued"
        else:
            stage = "no_finding"
        return dict(stage=stage, found=found, shown=shown,
                    queue={k: len(v) for k, v in self._queues().items()},
                    notice=(json.loads(p.stdout).get("systemMessage") if p.stdout.strip().startswith("{") else None),
                    gate_err=p.stderr[-300:] if p.returncode else None)
