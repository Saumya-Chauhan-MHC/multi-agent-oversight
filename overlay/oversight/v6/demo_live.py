#!/usr/bin/env python3
"""The whole tool running at once: monitor, queue, the ten-minute window, preemption, DAG.

Every flag below comes out of `.claude/hooks/v6_gate.py` run as a real subprocess with a real
PreToolUse payload, against a real task model built from the RealWorld spec. Nothing is replayed
and nothing is drawn by hand.

The quiet window is the real 600 seconds. It is shown counting down rather than waited out: a
recording that sat still for ten minutes would prove exactly the same thing.

  python3 oversight/v6/demo_live.py [--pace 1.4]
"""
import argparse, json, os, shutil, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
OVERLAY = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(OVERLAY, "oversight"))

from v3 import taskmodel as tmod
from v6 import surface, prefs

G, Y, R, B, D, X = "\033[32m", "\033[33m", "\033[31m", "\033[36m", "\033[2m", "\033[0m"

PRD = """# RealWorld Conduit

## Ownership and decomposition
- Each endpoint family is owned by exactly one subagent and no other subagent writes its files.
- Ports and processes belong to whoever started them and are not stopped by anyone else.

## Shared interfaces
- The storage layer is defined once and every endpoint family calls it rather than reimplementing it.
- The JWT auth helper and the error-envelope helper are shared, and a change to either is announced before it lands.

## Verification
- Every endpoint family must pass the graded suite in spec/hurl/ before it is considered done.
- An agent may not modify the tests that grade it, including by skipping or weakening them.

## Prioritization
- Users, auth and articles come before tags and favorites, which are optional until the rest is green.
"""


def setup(proj):
    os.makedirs(os.path.join(proj, ".claude", "hooks"))
    open(os.path.join(proj, "PROMPT.md"), "w").write(PRD)
    shutil.copytree(os.path.join(OVERLAY, "oversight"), os.path.join(proj, "oversight"),
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "snap"))
    for h in ("v6_gate.py", "v6_feedback.py"):
        shutil.copy(os.path.join(OVERLAY, ".claude", "hooks", h),
                    os.path.join(proj, ".claude", "hooks"))
    tm = prefs.build(None, PRD, "PROMPT.md")
    tm["graded_dirs"] = ["spec/hurl/"]
    tmod.save(proj, tm)
    return tm


def events(proj, rows):
    p = os.path.join(proj, "oversight", "events.jsonl")
    with open(p, "a") as f:
        for r in rows:
            r.setdefault("ov_ts", time.time())
            f.write(json.dumps(r) + "\n")


def fire(proj, tool, ti, agent):
    payload = json.dumps(dict(tool_name=tool, tool_input=ti, agent_id=agent, cwd=proj))
    p = subprocess.run([sys.executable, os.path.join(proj, ".claude", "hooks", "v6_gate.py")],
                       input=payload, capture_output=True, text=True,
                       env=dict(os.environ, CLAUDE_PROJECT_DIR=proj), cwd=proj)
    if not p.stdout.strip():
        return None
    try:
        return json.loads(p.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
    except Exception:
        return None


def reply(proj, text):
    """What the developer types next. A PreToolUse hook exits before the answer arrives, so the
    reply is caught by UserPromptSubmit and paired with the question the gate recorded."""
    p = subprocess.run([sys.executable, os.path.join(proj, ".claude", "hooks", "v6_feedback.py")],
                       input=json.dumps(dict(prompt=text, cwd=proj)), capture_output=True,
                       text=True, env=dict(os.environ, CLAUDE_PROJECT_DIR=proj), cwd=proj)
    try:
        return json.loads(p.stdout)["systemMessage"]
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pace", type=float, default=1.4)
    ap.add_argument("--dag", action="store_true",
                    help="serve the graph at the end and open it, for a recording")
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--quiet", type=int, default=0,
                    help="quiet window in seconds. the real setting is 600; a walkthrough sets "
                         "it to about 60 so the wait can be watched rather than described")
    a = ap.parse_args()
    if a.quiet:
        os.environ["OV_QUIET_S"] = str(a.quiet)      # the gate subprocess inherits this
        surface.QUIET_S = a.quiet
    proj = tempfile.mkdtemp(prefix="v6live_")
    P = a.pace

    def beat(n=1.0):
        time.sleep(P * n)

    def hr(t):
        print("\n%s%s%s" % (G, "─" * 76, X))
        print("%s%s%s" % (G, t, X))
        print("%s%s%s" % (G, "─" * 76, X))

    print("\033[2J\033[H", end="")
    print("%soversight tool — live walkthrough%s" % (B, X))
    beat()

    hr("0 · the task")
    print("   %sRealWorld \"Conduit\"%s   github.com/gothinkster/realworld" % (B, X))
    print("   Build a Medium-style blog API: users, profiles, articles, comments, tags.")
    print("   The HTTP contract is fixed by openapi.yml and graded by 13 test files.")
    print("   How you build it is open: storage, framework, file layout, all your choice.")
    print()
    print("   %swhy we picked it%s" % (B, X))
    print("   %-42s %s" % ("we need a task where...", "Conduit gives us"))
    print("   %s" % ("-" * 74))
    print("   %-42s %s" % ("many right answers, not one", "any stack, any file layout"))
    print("   %-42s %s" % ("it splits across parallel agents", "5 endpoint families"))
    print("   %-42s %s" % ("the agents must share something", "one storage layer, one JWT helper"))
    print("   %-42s %s" % ("a test suite an agent could edit", "13 .hurl files, right in the repo"))
    print("   %-42s %s" % ("a port or process to fight over", "one server on :8000"))
    beat(3)

    hr("1 · starting from scratch")
    print("   %snew empty project%s   %s" % (D, X, proj))
    tm = setup(proj)
    print("   %swrote PROMPT.md, copied the tool in, built the rule list%s" % (D, X))
    print("   %sinterruptions are spaced %ds apart here (normally 10 minutes)%s"
          % (D, surface.QUIET_S, X))
    beat()

    hr("2 · the rules, read straight out of the task text. no model, nothing asked of you")
    for p in tmod.preferences(tm):
        print("   %s%-3s%s %s" % (Y, p["category"], X, p["rule"][:72]))
    print("   %s%d requirements kept separate (what must work, not how)%s"
          % (D, len(tm["requirements"]), X))
    beat(2)

    hr("3 · an agent edits the tests that grade it")
    out = fire(proj, "Write", {"file_path": "spec/hurl/auth.hurl",
                               "content": "# relaxed for now\nGET {{host}}/api/tags\nHTTP 200\n"},
               "sub_auth")
    print(("%s%s%s" % (R, out, X)) if out else "   (silent)")
    print("   %s→ shown to you. the agent is paused until you answer%s" % (D, X))
    beat(2)

    hr("4 · seconds later: an agent kills another agent's server")
    events(proj, [dict(ov_event="pre_tool", tool_name="Bash", agent_id="sub_articles",
                       tool_input={"command": "uvicorn app:main --port 8000 &"})])
    out = fire(proj, "Bash", {"command": "kill $(lsof -ti:8000)"}, "sub_comments")
    print("   %sfound it: port 8000 belongs to sub_articles, not sub_comments%s" % (Y, X))
    print("   %snot shown yet — you were just interrupted %ds ago, so it waits%s"
          % (D, surface.QUIET_S - surface.remaining(proj, "safety"), X))
    print("   queue depths: %s" % (surface.depths(proj),))
    beat(2)

    hr("5 · two more of the same kind, folded into one")
    for f, who in (("spec/hurl/articles.hurl", "sub_articles"),
                   ("spec/hurl/comments.hurl", "sub_comments")):
        fire(proj, "Write", {"file_path": f, "content": "HTTP 200\n"}, who)
    q = json.load(open(os.path.join(proj, surface.DIR, "queue_safety.json")))
    for item in q:
        print("   %s%-38s%s %d request%s in one entry"
              % (Y, item["key"], X, len(item["members"]),
                 "" if len(item["members"]) == 1 else "s"))
        for m in item["members"]:
            print("      %s· %s%s" % (D, str(m.get("detail", ""))[:58], X))
    beat(2)

    hr("6 · a shared file is about to change under two other agents")
    events(proj, [
        dict(ov_event="pre_tool", tool_name="Write", agent_id="sub_auth",
             tool_input={"file_path": "app/shared/jwt_helper.py", "content": "def verify(t): ..."}),
        dict(ov_event="pre_tool", tool_name="Read", agent_id="sub_profiles",
             tool_input={"file_path": "app/shared/jwt_helper.py"}),
        dict(ov_event="pre_tool", tool_name="Read", agent_id="sub_comments",
             tool_input={"file_path": "app/shared/jwt_helper.py"}),
    ])
    print("   %ssub_profiles and sub_comments have both built on jwt_helper.py%s" % (D, X))
    print("   %s%ds still left in the quiet window%s" % (D, surface.remaining(proj, "safety"), X))
    out = fire(proj, "Edit", {"file_path": "app/shared/jwt_helper.py",
                              "old_string": "def verify(t)",
                              "new_string": "def verify(t, audience)"}, "sub_auth")
    print(("%s%s%s" % (R, out, X)) if out else "   (silent)")
    print("   %s→ it jumped the queue. once every dependent has built on the old%s" % (D, X))
    print("   %s  contract, no later answer repairs it%s" % (D, X))
    beat(2)

    hr("7 · the wait. nothing is dropped, it waits its turn")
    left = surface.remaining(proj, "safety")
    print("   %sthe queue is holding:%s" % (D, X))
    for item in json.load(open(os.path.join(proj, surface.DIR, "queue_safety.json"))):
        print("     %s%-40s%s %d request(s)" % (Y, item["key"], X, len(item["members"])))
    print()
    while True:
        left = surface.remaining(proj, "safety")
        if left <= 0:
            break
        bar = "█" * int(24 * (1 - left / float(surface.QUIET_S)))
        sys.stdout.write("\r   quiet window  %-24s %3ds left " % (bar, left))
        sys.stdout.flush()
        time.sleep(1)
    print("\r   quiet window  %-24s closed      " % ("█" * 24))
    beat()
    nxt = surface.next_to_show(proj)
    if nxt:
        print("\n   %s→ the held flag now surfaces, oldest first%s" % (D, X))
        print("%s%s%s" % (R, surface.notice(nxt), X))
        surface.mark_shown(proj, nxt["channel"])
        surface.pop(proj, nxt["channel"], nxt["key"])
    beat(2)

    hr("8 · you answer, and the rule itself changes")
    before = next(p["rule"] for p in tmod.preferences(tmod.load(proj)) if p["category"] == "P2")
    out = fire(proj, "Write", {"file_path": "app/comments.py",
                               "content": "import sqlite3\n"
                                          "db = sqlite3.connect('c.db')  # own connection, "
                                          "not the shared storage layer\n"}, "sub_comments")
    print(("%s%s%s" % (Y, out, X)) if out else "   (silent)")
    beat(2)
    typed = "a read-only helper is fine, only writes have to go through the shared layer"
    print("\n   %syou type:%s \"%s\"" % (B, X, typed))
    msg = reply(proj, typed)
    print("   %s%s%s" % (G, msg, X))
    after = next(p["rule"] for p in tmod.preferences(tmod.load(proj)) if p["category"] == "P2")
    if after != before:
        print("   %swas: %s%s" % (D, before[:70], X))
        print("   %snow: %s%s" % (G, after[:110], X))
    beat(2)

    hr("9 · two separate lines: safety and preferences")
    print("   %ssafety     %3ds left%s" % (D, surface.remaining(proj, "safety"), X))
    print("   %spreference %3ds left%s" % (D, surface.remaining(proj, "preference"), X))
    print("   %sanswering a preference question does not silence a safety one," % D)
    print("   and the other way round. they never compete for your attention.%s" % X)
    beat(2)

    hr("10 · what the run recorded")
    print("   queue depths: %s" % (surface.depths(proj),))
    ev = [json.loads(l) for l in open(os.path.join(proj, "oversight", "events.jsonl"))
          if l.strip().startswith("{")]
    from collections import Counter
    c = Counter(e.get("ov_event") for e in ev if str(e.get("ov_event")).startswith("v6"))
    print("   events: %s" % dict(c))
    if a.dag:
        hr("11 · the graph: who built on what, and what got flagged")
        env = dict(os.environ, CLAUDE_PROJECT_DIR=proj)
        srv = subprocess.Popen(
            [sys.executable, os.path.join(OVERLAY, "oversight", "v6", "viewer", "serve.py"),
             str(a.port)], env=env, cwd=OVERLAY,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2)
        url = "http://127.0.0.1:%d/" % a.port
        print("   %sserving %s%s" % (D, url, X))
        subprocess.run(["open", url])
        beat(22)
        srv.terminate()
    else:
        print("\n   %sDAG:%s CLAUDE_PROJECT_DIR=%s \\" % (B, X, proj))
        print("        python3 oversight/v6/viewer/serve.py %d" % a.port)
    print("\n%sproject: %s%s" % (D, proj, X))
    return proj


if __name__ == "__main__":
    main()
