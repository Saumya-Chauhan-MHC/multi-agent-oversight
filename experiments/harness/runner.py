"""One run of one scenario: workspace, container, Claude Code (optionally with the oversight tool
live), scoring, result.json. A scenario supplies only what is specific to it; see Scenario.

  .venv/bin/python run.py <scenario> [common flags] [scenario flags]

Every scenario's runs go to <scenario>/runs/<scenario.run_path>/ and its workspaces to
~/.cache/<scenario>_ws/<same path>/testbed. The workspace is outside the repo on purpose: Claude Code
loads every CLAUDE.md from the working directory up to /, and this repo's CLAUDE.md describes the
experiments to the agent being measured.
"""
import argparse, hashlib, json, os, shutil, sys, time

from . import claude, docker

EXPERIMENTS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))


class Scenario:
    """What a scenario defines. `ctx` is a dict the scenario keeps its own state in across a run."""
    name = None                 # its directory under experiments/
    prefix = "x"                # container name prefix
    dummies = ()                # --dummy choices: pipeline checks without a model
    default_exp = "default"
    summary_keys = ()           # what run.py prints when a run ends
    answer_note = ""            # what a simulated user says when it declines a held spawn

    # -- a run --
    def add_args(self, ap): pass
    def load(self, a): return {}                                   # before anything else
    def result_fields(self, a, ctx): return {}                     # recorded in result.json
    def run_path(self, a): raise NotImplementedError              # list of path parts under runs/
    def cond(self, a): return "multi"                             # hook.py: multi = the lead may not act
    def setup(self, a, ctx, ctr, ws): raise NotImplementedError   # container `ctr` with `ws` at /testbed
    def prompt(self, a, ctx): raise NotImplementedError
    def dummy(self, a, ctx, ctr): raise NotImplementedError       # instead of the agent
    def score(self, a, ctx, ctr, run_dir): raise NotImplementedError
    def rules(self, a, prompt): return ""                         # q1 for the tool, with --oversight
    commands = {}                                                  # extra subcommands: {"--rescore": fn(argv)}

    # -- offline replay through the oversight tool (replay.py) --
    replay_variants = ("default",)
    replay_actions = True                                          # False: spawn gate only
    def oversight_lines(self, run, variant): raise NotImplementedError
    def violating(self, call, run): return False
    def role(self, description): return ""

    # -- batch.py --
    def prepare_job(self, argv): pass
    def sample(self, n, seed): raise NotImplementedError

    # -- paths --
    @property
    def dir(self):
        return os.path.join(EXPERIMENTS, self.name)

    @property
    def runs(self):
        return os.path.join(self.dir, "runs")

    @property
    def ws_root(self):
        return os.path.realpath(os.path.expanduser("~/.cache/%s_ws" % self.name))


def load_scenario(name):
    import importlib
    if EXPERIMENTS not in sys.path:
        sys.path.insert(0, EXPERIMENTS)
    try:
        return importlib.import_module("%s.scenario" % name).SCENARIO
    except ModuleNotFoundError as e:
        sys.exit("no scenario %r (%s)" % (name, e))


def parser(sc):
    ap = argparse.ArgumentParser(prog="run.py %s" % sc.name)
    ap.add_argument("--model", default=None, help="claude --model; default is the CLI's default")
    ap.add_argument("--rep", type=int, default=0)
    ap.add_argument("--exp", default=sc.default_exp, help="runs/<exp>/... groups runs of one setting")
    ap.add_argument("--timeout", type=int, default=2400, help="seconds for the agent")
    ap.add_argument("--dummy", choices=list(sc.dummies) or None, help="skip the model; check the pipeline")
    ap.add_argument("--keep", action="store_true", help="keep the container and workspace")
    ap.add_argument("--interactive", action="store_true",
                    help="Claude Code's own UI in this terminal; with --oversight, holds are asked in its dialog")
    ap.add_argument("--oversight", action="store_true", help="install overlay/ in the workspace: a live run")
    ap.add_argument("--tool", choices=("v2", "v3"), default="v2", help="--oversight: which version of the tool")
    ap.add_argument("--task-model", default=None, help="--tool v3: a task_model.json to use instead of extracting one")
    ap.add_argument("--rules", default=None, help="q1 for ctl.py init; default: the scenario's")
    ap.add_argument("--viewer-port", type=int, default=4180, help="--interactive --oversight: the tool's graph")
    ap.add_argument("--answer", choices=["human", "no", "accept"], default="no",
                    help="who answers a held spawn: you (ctl.py answer), or a simulated user")
    ap.add_argument("--answer-note", default=sc.answer_note)
    sc.add_args(ap)
    return ap


def run_dir_for(sc, a):
    return os.path.join(sc.runs, *sc.run_path(a))


def main(sc, argv):
    if argv and argv[0] in sc.commands:
        return sc.commands[argv[0]](argv[1:])
    a = parser(sc).parse_args(argv)
    ctx = sc.load(a)
    run_dir = run_dir_for(sc, a)
    shutil.rmtree(run_dir, ignore_errors=True)
    os.makedirs(run_dir)
    ws = os.path.join(sc.ws_root, os.path.relpath(run_dir, sc.runs), "testbed")
    shutil.rmtree(ws, ignore_errors=True)
    os.makedirs(ws)
    ctr = "%s-%s" % (sc.prefix, hashlib.md5(run_dir.encode()).hexdigest()[:10])
    docker.remove(ctr)

    result = dict(scenario=sc.name, exp=a.exp, rep=a.rep, model=a.model, dummy=a.dummy, interactive=a.interactive)
    result.update(sc.result_fields(a, ctx))
    result["container"] = ctr
    try:
        t0 = time.time()
        sc.setup(a, ctx, ctr, ws)
        result["setup_s"] = round(time.time() - t0, 1)
        prompt = sc.prompt(a, ctx)
        open(os.path.join(run_dir, "prompt.txt"), "w").write(prompt)
        if a.dummy:
            sc.dummy(a, ctx, ctr)
        else:
            result.update(run_agent(sc, a, prompt, ctr, ws, run_dir))
        result.update(sc.score(a, ctx, ctr, run_dir))
    except Exception as e:
        result["error"] = (result.get("error", "") + " " + repr(e)[-3000:]).strip()
    finally:
        if a.oversight and os.path.isdir(os.path.join(ws, "oversight")):
            from . import oversight_live
            oversight_live.collect(ws, run_dir)
            result["oversight_summary"] = (oversight_live.summary_v3(run_dir) if a.tool == "v3"
                                           else oversight_live.summary(run_dir))
        json.dump(result, open(os.path.join(run_dir, "result.json"), "w"), indent=1)
        if not a.keep:
            docker.remove(ctr)
            shutil.rmtree(ws, ignore_errors=True)
    keys = ("dummy",) + tuple(sc.summary_keys) + ("cost_usd", "agent_s", "oversight_summary", "error")
    print(json.dumps({k: result.get(k) for k in keys}))
    return result


def run_agent(sc, a, prompt, ctr, ws, run_dir):
    """Claude Code on the task, with the oversight tool installed and its holds answered if --oversight."""
    out, answerer, viewer = {}, None, None
    if a.oversight:
        from . import oversight_live
        if a.tool == "v3":
            lines = oversight_live.install_v3(ws, prompt, a.task_model)
        else:
            rules = a.rules if a.rules is not None else sc.rules(a, prompt)
            lines = oversight_live.install(ws, rules, interactive=a.interactive, viewer_port=a.viewer_port)
        out.update(oversight=True, oversight_tool=a.tool, oversight_lines=[l["text"] for l in lines],
                   answer="dialog" if a.interactive else a.answer)
        os.makedirs(os.path.join(run_dir, "oversight"), exist_ok=True)
        if a.tool == "v3":
            if a.interactive:
                viewer = oversight_live.start_viewer_v3(ws, a.viewer_port)
            else:
                print("  v3 headless: a hold is an \"ask\", which -p treats as a refusal (no one to ask)", flush=True)
        elif a.interactive:
            viewer = oversight_live.start_viewer(ws, a.viewer_port)
        elif a.answer == "human":
            print(oversight_live.human_instructions(ws), flush=True)
        else:
            answerer = oversight_live.Answerer(ws, a.answer, a.answer_note,
                                               os.path.join(run_dir, "oversight", "answers.jsonl"))
            answerer.start()
    if a.interactive:
        print("\n  %s   %s   model: %s" % (sc.name, os.path.relpath(run_dir, sc.runs), a.model or "default"))
        if a.oversight and a.tool == "v3":
            print("  Oversight v3 is on. A hold is Claude Code's own permission dialog; a notice is a")
            print("  system message that pauses nothing. Its event log: oversight/events.jsonl in the workspace.")
            print("  The graph: http://localhost:%d   (read-only; open it yourself, nothing opens it on a hold)" % a.viewer_port)
        elif a.oversight:
            print("  Oversight is on; a held spawn is asked in Claude Code's own dialog.")
            print("  The graph: http://localhost:%d   (it opens by itself on a hold)" % a.viewer_port)
        print("  The task is sent as the first message. End the session with /exit; scoring follows.\n")
    try:
        out.update(claude.run(prompt, sc.cond(a), a.model, ctr, ws, run_dir, a.timeout, interactive=a.interactive))
    finally:
        if viewer:
            viewer.terminate()
        if answerer:
            answerer.stop()
    return out
