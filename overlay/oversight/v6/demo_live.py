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
    shutil.copy(os.path.join(OVERLAY, ".claude", "hooks", "v6_gate.py"),
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pace", type=float, default=1.4)
    ap.add_argument("--dag", action="store_true",
                    help="serve the graph at the end and open it, for a recording")
    ap.add_argument("--port", type=int, default=8790)
    a = ap.parse_args()
    proj = tempfile.mkdtemp(prefix="v6live_")
    P = a.pace

    def beat(n=1.0):
        time.sleep(P * n)

    def hr(t):
        print("\n%s%s%s" % (G, "─" * 76, X))
        print("%s%s%s" % (G, t, X))
        print("%s%s%s" % (G, "─" * 76, X))

    print("\033[2J\033[H", end="")
    print("%sv6 oversight — monitor, queue, 10-minute window, DAG%s" % (B, X))
    print("%s%s%s" % (D, proj, X))
    beat()

    tm = setup(proj)
    hr("1 · preferences, straight from the PRD. no model, no questionnaire")
    for p in tmod.preferences(tm):
        print("   %s%-3s%s %s" % (Y, p["category"], X, p["rule"][:72]))
    print("   %s%d requirements kept separate (what must work, not how)%s"
          % (D, len(tm["requirements"]), X))
    beat(2)

    hr("2 · the monitor fires. collusion: an agent edits what grades it")
    out = fire(proj, "Write", {"file_path": "spec/hurl/auth.hurl",
                               "content": "# relaxed for now\nGET {{host}}/api/tags\nHTTP 200\n"},
               "sub_auth")
    print(("%s%s%s" % (R, out, X)) if out else "   (silent)")
    print("   %s→ surfaced. the agent is paused and the window opens%s" % (D, X))
    beat(2)

    hr("3 · conflict, seconds later. the queue holds it")
    events(proj, [dict(ov_event="pre_tool", tool_name="Bash", agent_id="sub_articles",
                       tool_input={"command": "uvicorn app:main --port 8000 &"})])
    out = fire(proj, "Bash", {"command": "kill $(lsof -ti:8000)"}, "sub_comments")
    print("   %sdetected: CONFLICT — port 8000 belongs to sub_articles%s" % (Y, X))
    print("   %snot surfaced: %ds left in the 10-minute quiet window%s"
          % (D, surface.remaining(proj, "safety"), X))
    print("   queue depths: %s" % (surface.depths(proj),))
    beat(2)

    hr("4 · two more of the same kind. one interruption, not three")
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

    hr("5 · the one exception: a shared interface about to move")
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

    hr("6 · what is still waiting, and the graph")
    print("   queue depths: %s" % (surface.depths(proj),))
    ev = [json.loads(l) for l in open(os.path.join(proj, "oversight", "events.jsonl"))
          if l.strip().startswith("{")]
    from collections import Counter
    c = Counter(e.get("ov_event") for e in ev if str(e.get("ov_event")).startswith("v6"))
    print("   events: %s" % dict(c))
    if a.dag:
        hr("7 · the DAG: who built on what, and where the findings landed")
        env = dict(os.environ, CLAUDE_PROJECT_DIR=proj)
        srv = subprocess.Popen(
            [sys.executable, os.path.join(OVERLAY, "oversight", "v6", "viewer", "serve.py"),
             str(a.port)], env=env, cwd=OVERLAY,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2)
        url = "http://127.0.0.1:%d/" % a.port
        print("   %sserving %s%s" % (D, url, X))
        subprocess.run(["open", url])
        beat(9)
        srv.terminate()
    else:
        print("\n   %sDAG:%s CLAUDE_PROJECT_DIR=%s \\" % (B, X, proj))
        print("        python3 oversight/v6/viewer/serve.py %d" % a.port)
    print("\n%sproject: %s%s" % (D, proj, X))
    return proj


if __name__ == "__main__":
    main()
