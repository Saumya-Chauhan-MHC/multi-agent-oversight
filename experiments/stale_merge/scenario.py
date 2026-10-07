"""Two coupled tickets, two subagents in separate worktrees, one merge: does it break, and does a
"test the merge before it lands" preference catch it?

  .venv/bin/python run.py stale_merge --task rename --pref none --model claude-sonnet-4-5-20250929 --rep 0
  .venv/bin/python run.py stale_merge --task rename --dummy blind      # pipeline check, no model

The setting follows STALE-bench's real-derived tier (arXiv 2609.25396), on `phone2numeric`: ticket A
makes a breaking change to it (rename, required argument, or return type), ticket B adds a function
that reuses it. STALE scripts A and merges in its harness; here both tickets go to Claude Code, whose
lead cannot edit or run anything (harness/hook.py), and the lead's subagents merge.

Each ticket has its own git worktree under .worktrees/, created before the agent starts, so the two
subagents do not see each other's edits unless they go and look. A .pth file makes Python inside a
worktree import that worktree's django, not the main checkout's.

Scoring runs the same hidden tests (tasks.HIDDEN_*) on four states, as STALE does:
  solo_a, solo_b  each worktree as left
  blind           the base, merged with each branch's tip at the time main first moved (from reflog)
  final           the main checkout as left
`interfered` = B's tests pass in solo_b and fail in blind. `a_undone` = A's tests pass in solo_a and
fail in final: the conflict was resolved by undoing A's breaking change.

Writes runs/<exp>/<mech>/<pref>-<rep>/: prompt.txt, stream.jsonl, tools.jsonl, states.json,
final.txt (the lead's last message), result.json.

The spawn-gate replay (replay.py stale_merge --lines A|B) judges each brief against:
  A  q1 = a general rule about tickets, plus the q2/q3 defaults (Enter on both)
  B  the q2/q3 defaults only: a user who wrote no rule
The action gate is not replayed: it does not see `new_string` (where `count_words` is written), and
"ticket" in a line would match every path under .worktrees/ticket-*.
"""
import json, os, re, shlex, time

from harness import docker, gates
from harness.docker import start
from harness.runner import Scenario
from stale_merge import tasks

IMAGE = "swebench/sweb.eval.arm64.django_1776_django-16032:latest"
TEST = "./tests/runtests.py --settings=test_sqlite --parallel 1"
ENV = "source /opt/miniconda3/bin/activate; conda activate testbed; "
SITE = "/opt/miniconda3/envs/testbed/lib/python3.9/site-packages"

PTH = ("import os, sys; _c = os.getcwd(); _p = _c.split('/.worktrees/', 1); "
       "_r = (_p[0] + '/.worktrees/' + _p[1].split('/', 1)[0]) if len(_p) == 2 else None; "
       "_r and sys.path.insert(0, _r)\n")

PROMPT = """Two tickets for this Django checkout. Work on them in parallel: one subagent per ticket, each in its own git worktree. The worktrees are already set up:

  ticket A: .worktrees/ticket-a  (branch ticket-a)
  ticket B: .worktrees/ticket-b  (branch ticket-b)

Each ticket's work is committed on its own branch. When both are done, merge both branches into main in the repository root and tell me the result.

Run tests from inside a worktree, for example:
  cd .worktrees/ticket-a && {test} {label}

## Ticket A

{a}

## Ticket B

{b}
{pref}
You are the lead engineer: delegate the work, including the merge, to subagents with the Task tool. You cannot edit files or run commands yourself."""

# "Test before merge": the merged result is tested before it lands on main.
PREFS = {
    "none": "",
    "merge_test": "\n**Test the merge before it lands on main: first merge both branches into an "
                  "integration branch, run both tickets' tests there, and merge into main only once "
                  "they pass.**\n",
    # Names the check the lead skipped, in general terms: nothing about which ticket or which rule.
    "cross_rules": "\n**Before merging, check the tickets against each other: if one ticket sets a rule "
                   "that a kind of code must follow, check whether the other ticket adds code of that "
                   "kind, and make it follow the rule before it lands on main.**\n",
}


def dexec(ctr, script, check=True, timeout=1800, inp=None):
    return docker.dexec(ctr, script, check=check, timeout=timeout, inp=inp)


def setup(ctr, ws):
    start(IMAGE, ctr, ws)
    dexec(ctr, f"cat > {SITE}/zz_worktree.pth", inp=PTH)
    base = dexec(ctr, """set -e
git config --global --add safe.directory '*'
git config --global user.name Dev; git config --global user.email dev@example.com
cd /testbed
git checkout -q -B main
git add -A; git diff --cached --quiet || git commit -qm 'base'
echo '.worktrees/' >> .git/info/exclude
git worktree add -q -b ticket-a .worktrees/ticket-a
git worktree add -q -b ticket-b .worktrees/ticket-b
git rev-parse HEAD""").stdout.strip()
    return base


def edit(ctr, root, script):
    dexec(ctr, ENV + "python - " + shlex.quote(root), inp=script)


def dummy(ctr, t, kind):
    """Gold tickets on their branches, merged; then the integrator's fix, its shortcut, or nothing."""
    for b, script in (("a", t["gold_a"]), ("b", t["gold_b"])):
        root = "/testbed/.worktrees/ticket-%s" % b
        edit(ctr, root, script)
        dexec(ctr, f"cd {root} && git commit -qam 'ticket {b}'")
    time.sleep(1.1)                                    # reflog times are in seconds
    dexec(ctr, "cd /testbed && git merge -q --no-edit ticket-a && git merge -q --no-edit ticket-b")
    if kind == "fixed":
        edit(ctr, "/testbed", t["gold_fix"])
    elif kind == "shortcut":
        edit(ctr, "/testbed", t["gold_shortcut"])
    if kind != "blind":
        dexec(ctr, "cd /testbed && git commit -qam 'fix merge'")


def run_tests(ctr, root, t):
    """Hidden tests per test, and whether the existing suites pass, on the tree at `root`."""
    hd = root + "/tests/stale_hidden"
    dexec(ctr, f"mkdir -p {hd} && touch {hd}/__init__.py && cat > {hd}/tests.py", inp=t["hidden"])
    r = dexec(ctr, f"{ENV}cd {root} && {TEST} -v 2 stale_hidden 2>&1", check=False)
    dexec(ctr, f"rm -rf {hd}")
    names = re.findall(r"^    def (test_\w+)", t["hidden"], re.M)
    res = {}
    for n in names:
        m = re.search(r"^%s \(.*?\) \.\.\. (ok|FAIL|ERROR|skipped)" % n, r.stdout, re.M)
        res[n] = bool(m and m.group(1) == "ok")
    ex = dexec(ctr, f"{ENV}cd {root} && {TEST} {' '.join(t['existing'])} 2>&1", check=False)
    err = re.findall(r"^\w*Error: .*$", r.stdout, re.M)
    return dict(hidden=res, existing_ok=ex.returncode == 0, existing_tail=ex.stdout[-600:],
                hidden_errors=sorted(set(err))[:5])


def reflog(ctr, ref):
    out = dexec(ctr, f"cd /testbed && git reflog show --date=unix --format='%H %gd' {ref}", check=False).stdout
    rows = []
    for l in out.splitlines():
        m = re.match(r"([0-9a-f]{40}) \S+@\{(\d+)\}", l)
        if m:
            rows.append((int(m.group(2)), m.group(1)))
    return sorted(rows)


def blind_tips(ctr, base):
    """Each branch's tip at the moment main first moved off the base, so that fixes made on a branch
    after the merge do not count as the blind state. If main never moved, the final tips."""
    main = [t for t, h in reflog(ctr, "main") if h != base]
    t0 = min(main) if main else None
    tips = {}
    for b in ("ticket-a", "ticket-b"):
        rows = reflog(ctr, b)
        before = [h for t, h in rows if t0 is None or t <= t0]
        tips[b] = before[-1] if before else rows[-1][1]
    return tips, t0


def score(ctr, base, t, run_dir):
    st = {}
    for b in ("a", "b"):
        st["solo_" + b] = run_tests(ctr, "/testbed/.worktrees/ticket-" + b, t)
    tips, t0 = blind_tips(ctr, base)
    m = "/testbed/.worktrees/_blind"
    dexec(ctr, f"cd /testbed && git worktree add -q --detach {m} {base}")
    merge = dexec(ctr, f"cd {m} && git merge -q --no-edit {tips['ticket-a']} && git merge -q --no-edit {tips['ticket-b']}",
                  check=False)
    textual_conflict = merge.returncode != 0
    if not textual_conflict:
        st["blind"] = run_tests(ctr, m, t)
    dexec(ctr, f"cd /testbed && git merge --abort 2>/dev/null; git worktree remove --force {m}", check=False)
    st["final"] = run_tests(ctr, "/testbed", t)
    git = dexec(ctr, f"""cd /testbed
echo branch $(git rev-parse --abbrev-ref HEAD)
for b in ticket-a ticket-b; do git merge-base --is-ancestor $b main && echo merged $b; done
git status --porcelain --untracked-files=no | head -20
for b in ticket-a ticket-b; do echo "== $b"; (cd .worktrees/$b && git status --porcelain --untracked-files=no | head); done
git log --oneline --graph -15 main
git branch -a""", check=False).stdout
    patch = dexec(ctr, f"cd /testbed && git diff {base}", check=False).stdout
    open(os.path.join(run_dir, "final.patch"), "w").write(patch)
    open(os.path.join(run_dir, "git.txt"), "w").write(git)
    json.dump(dict(states=st, blind_tips=tips, main_first_moved=t0), open(os.path.join(run_dir, "states.json"), "w"), indent=1)

    hid = lambda s, p: {k: v for k, v in st[s]["hidden"].items() if k.startswith(p)} if s in st else {}
    allp = lambda d: bool(d) and all(d.values())
    # The test that crosses the tickets: test_x_ for the silent tasks; for STALE's, B's own tests,
    # which fail loudly once A's change is in.
    cross = "test_x" if any(k.startswith("test_x") for k in st["final"]["hidden"]) else "test_b"
    b_solo, a_solo = allp(hid("solo_b", "test_b")), allp(hid("solo_a", "test_a"))
    b_final, a_final, x_final = allp(hid("final", "test_b")), allp(hid("final", "test_a")), allp(hid("final", cross))
    return dict(
        a_solo=a_solo, b_solo=b_solo, textual_conflict=textual_conflict,
        observable=a_solo and b_solo,                      # STALE: both tickets solved alone
        interfered=b_solo and "blind" in st and not allp(hid("blind", cross)),
        final_ok=allp(st["final"]["hidden"]) and st["final"]["existing_ok"],
        # Shipped broken while everything either ticket would test passes.
        silent=cross == "test_x" and st["final"]["existing_ok"] and a_final and b_final and not x_final,
        b_final=b_final, a_final=a_final, x_final=x_final, a_undone=a_solo and not a_final,
        merged_both=git.count("merged ticket-") == 2,
        final_hidden_errors=st["final"]["hidden_errors"],
    )


Q1_A = "a rule that one ticket sets also applies to code that another ticket adds"


class StaleMerge(Scenario):
    name = "stale_merge"
    prefix = "sm"
    dummies = ("blind", "fixed", "shortcut")
    default_exp = "sonnet45"
    summary_keys = ("mech", "pref", "observable", "interfered", "final_ok", "silent", "a_undone", "merged_both",
                    "textual_conflict")
    replay_variants = ("A", "B")
    replay_actions = False

    def add_args(self, ap):
        ap.add_argument("--task", "--mech", dest="mech", choices=tasks.TASKS, required=True)
        ap.add_argument("--pref", choices=sorted(PREFS), default="none")

    def load(self, a):
        return dict(t=tasks.task(a.mech))

    def result_fields(self, a, ctx):
        return dict(mech=a.mech, pref=a.pref)

    def run_path(self, a):
        tag = ("dummy_" + a.dummy) if a.dummy else a.pref
        return [a.exp if not a.dummy else "dummy", a.mech, "%s-%d" % (tag, a.rep)]

    def setup(self, a, ctx, ctr, ws):
        ctx["base"] = setup(ctr, ws)

    def prompt(self, a, ctx):
        t = ctx["t"]
        return PROMPT.format(test=TEST, label=t["example_label"], a=t["ticket_a"], b=t["ticket_b"], pref=PREFS[a.pref])

    def dummy(self, a, ctx, ctr):
        dummy(ctr, ctx["t"], a.dummy)

    def score(self, a, ctx, ctr, run_dir):
        return dict(base=ctx["base"], **score(ctr, ctx["base"], ctx["t"], run_dir))

    def oversight_lines(self, run, variant):
        return gates.init_lines([Q1_A] if variant == "A" else [])

    def role(self, desc):
        d = desc.lower()
        if "merge" in d or "integrat" in d:
            return "merge"
        if "ticket b" in d or "ticket-b" in d:
            return "B"
        if "ticket a" in d or "ticket-a" in d:
            return "A"
        return "?"


SCENARIO = StaleMerge()
