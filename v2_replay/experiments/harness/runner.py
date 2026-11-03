"""One run of one scenario: workspace, container, Claude Code (optionally with the oversight tool
live), scoring, result.json. A scenario supplies only what is specific to it; see Scenario.

  .venv/bin/python run.py <scenario> [common flags] [scenario flags]

Every run goes to outputs/week_<N>/<scenario>/<setting>/<task>/<variant>-<rep>/, where setting is
<model>-<cond>-<tool> (e.g. sonnet45-multi-notool, sonnet45-multi-v2-no) and N counts weeks from
Monday 2026-10-12 (week_1); week_0 holds everything run before that. Its workspace goes to
~/.cache/<scenario>_ws/<same path below outputs/>/testbed. The workspace is outside the repo on purpose: Claude Code
loads every CLAUDE.md from the working directory up to /, and this repo's CLAUDE.md describes the
experiments to the agent being measured.
"""
import argparse, datetime, hashlib, json, os, re, shutil, sys, time

from . import claude, docker

EXPERIMENTS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
OUTPUTS = os.path.join(EXPERIMENTS, "outputs")
WEEK_1 = datetime.date(2026, 10, 12)        # a Monday


def current_week(today=None):
    return max(1, ((today or datetime.date.today()) - WEEK_1).days // 7 + 1)


def model_tag(model):
    """claude-sonnet-4-5-20250929 -> sonnet45, claude-sonnet-5 -> sonnet5."""
    if not model:
        return "default"
    m = re.sub(r"-\d{8}$", "", model.replace("claude-", ""))
    return m.replace("-", "")


def tool_tag(a):
    """notool, or <tool>-<who answers a hold>: v2-no, v2-accept, v2-human."""
    if not a.oversight:
        return "notool"
    return "%s-%s" % (a.tool, "human" if a.interactive or a.answer == "human" else a.answer)


def setting(sc, a):
    if a.dummy:
        return "dummy"
    tag = "%s-%s-%s" % (model_tag(a.model), sc.cond(a), tool_tag(a))
    if getattr(a, "ask", None):
        tag += "-ask_" + a.ask
        if getattr(a, "ask_hint", False):
            tag += "-hint"
    return tag + "_" + a.exp if a.exp else tag


class Scenario:
    """What a scenario defines. `ctx` is a dict the scenario keeps its own state in across a run."""
    name = None                 # its directory under experiments/
    prefix = "x"                # container name prefix
    dummies = ()                # --dummy choices: pipeline checks without a model
    summary_keys = ()           # what run.py prints when a run ends
    answer_note = ""            # what a simulated user says when it declines a held spawn

    # -- a run --
    def add_args(self, ap): pass
    def load(self, a): return {}                                   # before anything else
    def result_fields(self, a, ctx): return {}                     # recorded in result.json
    def task(self, a): return self.name                           # which task within the scenario
    def variant(self, a): raise NotImplementedError               # the prompt or preference wording; dummy_<name> for --dummy
    def cond(self, a): return "multi"                             # hook.py: multi = the lead may not act
    def setup(self, a, ctx, ctr, ws): raise NotImplementedError   # container `ctr` with `ws` at /testbed
    def prompt(self, a, ctx): raise NotImplementedError
    def dummy(self, a, ctx, ctr): raise NotImplementedError       # instead of the agent
    def score(self, a, ctx, ctr, run_dir): raise NotImplementedError
    def rules(self, a, prompt): return ""                         # q1 for the tool, with --oversight
    def intents(self, a, ctx): return {}                          # --ask: {card name: the user's words}
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
    ap.add_argument("--week", type=int, default=current_week(), help="outputs/week_<N>; default: this week")
    ap.add_argument("--exp", default=None, help="optional suffix on the setting directory, for a one-off variation")
    ap.add_argument("--timeout", type=int, default=2400, help="seconds for the agent")
    ap.add_argument("--dummy", choices=list(sc.dummies) or None, help="skip the model; check the pipeline")
    ap.add_argument("--keep", action="store_true", help="keep the container and workspace")
    ap.add_argument("--interactive", action="store_true",
                    help="Claude Code's own UI in this terminal; with --oversight, holds are asked in its dialog")
    ap.add_argument("--oversight", action="store_true", help="install overlay/ in the workspace: a live run")
    ap.add_argument("--tool", choices=("v2", "baseline"), default="v2", help="--oversight: which version of the tool")
    ap.add_argument("--threshold", type=float, default=None, help="--tool baseline: hold at this score")
    ap.add_argument("--rules", default=None, help="q1 for ctl.py init; default: the scenario's")
    ap.add_argument("--viewer-port", type=int, default=4180, help="--interactive --oversight: the tool's graph")
    ap.add_argument("--answer", choices=["human", "no", "accept"], default="no",
                    help="who answers a held spawn: you (ctl.py answer), or a simulated user")
    ap.add_argument("--answer-note", default=sc.answer_note)
    ap.add_argument("--ask", default=None, help="give the agent an ask_user tool, answered by a simulated user "
                    "from this intent card (the scenario's intents(); headless only)")
    ap.add_argument("--simuser-model", default="claude-sonnet-5", help="--ask: the simulated user's model")
    ap.add_argument("--ask-hint", action="store_true", help="--ask: one neutral sentence in the system prompt "
                    "saying the agent can ask the user with the tool (harness/claude.py ASK_HINT)")
    sc.add_args(ap)
    return ap


def run_dir_for(sc, a):
    return os.path.join(OUTPUTS, "week_%d" % a.week, sc.name, setting(sc, a), sc.task(a),
                        "%s-%d" % (sc.variant(a), a.rep))


def main(sc, argv):
    if argv and argv[0] in sc.commands:
        return sc.commands[argv[0]](argv[1:])
    a = parser(sc).parse_args(argv)
    ctx = sc.load(a)
    run_dir = run_dir_for(sc, a)
    shutil.rmtree(run_dir, ignore_errors=True)
    os.makedirs(run_dir)
    ws = os.path.join(sc.ws_root, os.path.relpath(run_dir, OUTPUTS), "testbed")
    shutil.rmtree(ws, ignore_errors=True)
    os.makedirs(ws)
    ctr = "%s-%s" % (sc.prefix, hashlib.md5(run_dir.encode()).hexdigest()[:10])
    docker.remove(ctr)

    result = dict(scenario=sc.name, week=a.week, setting=setting(sc, a), exp=a.exp, rep=a.rep, model=a.model, dummy=a.dummy, interactive=a.interactive)
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
            result.update(run_agent(sc, a, prompt, ctr, ws, run_dir, ctx))
        result.update(sc.score(a, ctx, ctr, run_dir))
    except Exception as e:
        result["error"] = (result.get("error", "") + " " + repr(e)[-3000:]).strip()
    finally:
        if a.oversight and os.path.isdir(os.path.join(ws, "oversight")):
            from . import oversight_live
            oversight_live.collect(ws, run_dir)
            result["oversight_summary"] = (oversight_live.summary_baseline(run_dir) if a.tool == "baseline"
                                           else oversight_live.summary(run_dir))
        if os.environ.get("IB_RECORD") and os.path.isfile(os.path.join(ws, "oversight", "events.jsonl")):
            shutil.copytree(os.path.join(ws, "oversight"), os.path.join(run_dir, "record"),
                            ignore=shutil.ignore_patterns("store", ".manifest_*", ".snapstate.json"))
            result["recorded"] = sum(1 for _ in open(os.path.join(run_dir, "record", "events.jsonl")))
        json.dump(result, open(os.path.join(run_dir, "result.json"), "w"), indent=1)
        if not a.keep:
            docker.remove(ctr)
            shutil.rmtree(ws, ignore_errors=True)
    keys = ("dummy",) + tuple(sc.summary_keys) + ("cost_usd", "agent_s", "oversight_summary", "error")
    print(json.dumps({k: result.get(k) for k in keys}))
    return result


def run_agent(sc, a, prompt, ctr, ws, run_dir, ctx=None):
    """Claude Code on the task, with the oversight tool installed and its holds answered if --oversight."""
    out, answerer, viewer = {}, None, None
    if a.oversight:
        from . import oversight_live
        if a.tool == "baseline":
            lines = oversight_live.install_baseline(ws, prompt, a.threshold)
        else:
            rules = a.rules if a.rules is not None else sc.rules(a, prompt)
            lines = oversight_live.install(ws, rules, interactive=a.interactive, viewer_port=a.viewer_port)
        out.update(oversight=True, oversight_tool=a.tool, oversight_lines=[l["text"] for l in lines],
                   answer="dialog" if a.interactive else a.answer)
        os.makedirs(os.path.join(run_dir, "oversight"), exist_ok=True)
        if a.tool == "baseline":
            if not a.interactive:
                print("  baseline headless: a hold is an \"ask\", which -p treats as a refusal (no one to ask)", flush=True)
        elif a.interactive:
            viewer = oversight_live.start_viewer(ws, a.viewer_port)
        elif a.answer == "human":
            print(oversight_live.human_instructions(ws), flush=True)
        else:
            answerer = oversight_live.Answerer(ws, a.answer, a.answer_note,
                                               os.path.join(run_dir, "oversight", "answers.jsonl"))
            answerer.start()
    if a.interactive:
        print("\n  %s   %s   model: %s" % (sc.name, os.path.relpath(run_dir, OUTPUTS), a.model or "default"))
        if a.oversight:
            print("  Oversight is on; a held spawn is asked in Claude Code's own dialog.")
            print("  The graph: http://localhost:%d   (it opens by itself on a hold)" % a.viewer_port)
        print("  The task is sent as the first message. End the session with /exit; scoring follows.\n")
    if os.environ.get("IB_RECORD") and os.path.isdir(os.path.join(ws, ".git")):
        with open(os.path.join(ws, ".git", "info", "exclude"), "a") as f:     # keep the recorder out of the scored diff
            f.write("\noversight/\n")
    ask = None
    if getattr(a, "ask", None) and not a.interactive:
        cards = sc.intents(a, ctx or {})
        if a.ask not in cards:
            raise RuntimeError("no intent card %r; this task has %s" % (a.ask, sorted(cards)))
        ask = dict(intent=cards[a.ask], task=prompt, log=os.path.join(run_dir, "ask_user.jsonl"), model=a.simuser_model,
                   hint=getattr(a, "ask_hint", False))
        out.update(ask=a.ask, ask_intent=cards[a.ask], simuser_model=a.simuser_model, ask_hint=ask["hint"])
    try:
        out.update(claude.run(prompt, sc.cond(a), a.model, ctr, ws, run_dir, a.timeout, interactive=a.interactive, ask=ask))
    finally:
        if viewer:
            viewer.terminate()
        if answerer:
            answerer.stop()
    return out
