#!/usr/bin/env python3
"""The graph, for v3. Read-only: it shows state, it never decides anything.

The v2 viewer read the five typed lines and the catch-up counter, neither of which exists now, so
it was not ported, it was replaced. This one reads what v3 actually has: the task model, the agents
and what each one owns, who depends on whose work, and every judgement with the band it landed on.

It opens on a hold, which is the one moment the design says is worth leaving the terminal for.
Nothing here is a dashboard to watch: a graph left open all session becomes wallpaper.
"""
import json, os, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(HERE))))   # the project root, which holds oversight/
from oversight.v4 import rules, policy4 as policy
from oversight.v3 import taskmodel as tmod
from oversight import align

PROJ = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()


def state():
    tm = rules.load(PROJ)
    ev = align.read_events(PROJ) if hasattr(align, "read_events") else _events()
    dep = tmod.dependency_map(ev)
    js = [e for e in ev if e.get("ov_event") == "v4_judgement"]
    answers = [e for e in ev if e.get("ov_event") == "v4_user"]

    agents, spawned = {}, {}
    for e in ev:
        if e.get("ov_event") == "pre_tool" and e.get("tool_name") in ("Agent", "Task"):
            ti = e.get("tool_input") or {}
            spawned[len(spawned)] = (ti.get("description") or "")[:46]
    for e in ev:
        a = e.get("agent_id") or "orchestrator"
        if e.get("ov_event") != "pre_tool":
            continue
        n = agents.setdefault(a, dict(id=a, short=a[:9], writes=set(), reads=set(),
                                      flags=[], bands={}))
        ti = e.get("tool_input") or {}
        f = (ti.get("file_path") or "").split("/")[-1]
        if f and e.get("tool_name") in ("Write", "Edit", "MultiEdit"):
            n["writes"].add(f)
    for j in js:
        a = j.get("agent") or "orchestrator"
        n = agents.setdefault(a, dict(id=a, short=a[:9], writes=set(), reads=set(),
                                      flags=[], bands={}))
        b = j.get("band") or "silent"
        n["bands"][b] = n["bands"].get(b, 0) + 1
        if b != "silent":
            n["flags"].append(dict(band=b, trigger=j.get("trigger"), metric=j.get("metric"),
                                   risk=j.get("risk"),
                                   grounds=[j.get("rule")] if j.get("rule") else [],
                                   said=(j.get("said") or "")[:220],
                                   owner=j.get("owner"),
                                   action=(j.get("action") or "")[:120],
                                   consequence=(j.get("why") or "")[:220],
                                   correction=(j.get("fix") or "")[:180]))
    for n in agents.values():
        n["writes"] = sorted(n["writes"])[:9]
        n["reads"] = sorted(n["reads"])[:6]

    edges = []
    for who, files in (dep.get("depends_on") or {}).items():
        for other, owned in (dep.get("wrote") or {}).items():
            if other == who:
                continue
            shared = [f for f in files if f in owned]
            if shared:
                edges.append(dict(src=who, dst=other, files=[s.split("/")[-1] for s in shared][:4]))

    # v4 has no queue to show. What is worth showing instead is which rules the developer has
    # already answered about, because that answer is what keeps a rule from asking twice.
    asked = policy.asked(PROJ)
    return dict(
        agents=sorted(agents.values(), key=lambda n: (n["id"] != "orchestrator", n["id"])),
        edges=edges,
        requirements=[dict(id=r["id"], text=r["text"], check=r.get("check"),
                           status=r.get("status")) for r in tm.get("requirements", [])],
        preferences=[dict(id=p["id"], category=p["category"], rule=p["rule"],
                          source=p.get("source"), quoted=bool(p.get("quote")))
                     for p in rules.stated(tm)],
        ownership=tm.get("ownership") or {},
        answered=[dict(rule=r, decision=a.get("decision"), note=(a.get("note") or "")[:120])
                  for r, a in sorted(asked.items())],
        totals=dict(judgements=len(js),
                    bands={b: sum(1 for j in js if (j.get("band") or "silent") == b)
                           for b in ("silent", "hold")},
                    answers={a.get("decision"): sum(1 for x in answers
                                                    if x.get("decision") == a.get("decision"))
                             for a in answers}))


def _events():
    p = os.path.join(PROJ, "oversight", "events.jsonl")
    out = []
    if os.path.exists(p):
        for l in open(p):
            try:
                out.append(json.loads(l))
            except Exception:
                pass
    return out


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/state":
            body, ct = json.dumps(state()).encode(), b"application/json"
        else:
            body, ct = open(os.path.join(HERE, "index.html"), "rb").read(), b"text/html"
        self.send_response(200)
        self.send_header("Content-Type", ct.decode())
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 7391
    print("graph on http://127.0.0.1:%d  (project: %s)" % (port, PROJ))
    server = HTTPServer(("127.0.0.1", port), H)
    # v3_gate links this page from a hold, and only when a viewer is running: it finds the port here.
    marker = os.path.join(policy.ctl(PROJ), "viewer_port")
    open(marker, "w").write("%d %d\n" % (port, os.getpid()))
    import signal
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))      # stopped by a harness: still clean up
    try:
        server.serve_forever()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        try:
            os.remove(marker)
        except OSError:
            pass
