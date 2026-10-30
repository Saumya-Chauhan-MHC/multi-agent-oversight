#!/usr/bin/env python3
"""The DAG, for v6. Read-only: it shows state, it never decides anything.

v3's viewer reads `v3_judgement` and `v3_user`. v6 emits `v6_finding`, `v6_judged` and
`v6_surfaced`, so pointing the old one at a v6 run drew an empty graph and reported nothing. This
reads what v6 actually writes, and adds the two things the SSOT asks the graph to show that v3
had nowhere to put: which channel a finding went down, and which preferences have moved since the
PRD.

  python3 oversight/v6/viewer/serve.py [port]
"""
import json, os, sys
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(HERE))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(HERE))),
                                "oversight"))
from oversight.v3 import taskmodel as tmod
from oversight.v6 import surface, prefs

PROJ = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
RISK_COLOR = {"collusion": "#ff7b72", "miscoordination": "#d29922", "conflict": "#a371f7"}


def events():
    p = os.path.join(PROJ, "oversight", "events.jsonl")
    out = []
    if os.path.exists(p):
        for l in open(p):
            try:
                out.append(json.loads(l))
            except Exception:
                pass
    return out


def state():
    tm = tmod.load(PROJ)
    ev = events()
    dep = tmod.dependency_map(ev)
    findings = [e for e in ev if e.get("ov_event") == "v6_finding"]
    judged = [e for e in ev if e.get("ov_event") == "v6_judged"]
    surfaced = [e for e in ev if e.get("ov_event") == "v6_surfaced"]

    agents = {}
    for e in ev:
        who = e.get("agent_id") or "orchestrator"
        n = agents.setdefault(who, dict(id=who, writes=set(), reads=set(), findings=[]))
        ti = e.get("tool_input") or {}
        f = ti.get("file_path") or ""
        if e.get("ov_event") == "pre_tool" and f:
            (n["writes"] if e.get("tool_name") in ("Write", "Edit", "MultiEdit")
             else n["reads"]).add(f.split("/")[-1])
    for f in findings:
        n = agents.setdefault(f.get("agent") or "orchestrator",
                              dict(id=f.get("agent"), writes=set(), reads=set(), findings=[]))
        n["findings"].append(dict(kind=f.get("kind"), risk=f.get("risk"),
                                  reason=f.get("reason"), detail=str(f.get("detail"))[:60]))
    for n in agents.values():
        n["writes"] = sorted(n["writes"])[:8]
        n["reads"] = sorted(n["reads"])[:6]

    edges = []
    for who, files in (dep.get("depends_on") or {}).items():
        for other, owned in (dep.get("wrote") or {}).items():
            if other == who:
                continue
            shared = [f for f in files if f in owned]
            if shared:
                edges.append(dict(src=who, dst=other,
                                  files=[s.split("/")[-1] for s in shared][:4]))

    return dict(
        agents=sorted(agents.values(), key=lambda n: (n["id"] != "orchestrator", n["id"])),
        edges=edges,
        preferences=[dict(id=p.get("id"), category=p.get("category"), rule=p.get("rule"),
                          source=p.get("source"), moved=len(p.get("history") or []))
                     for p in tmod.preferences(tm)],
        moved=prefs.changed(tm),
        queues=surface.depths(PROJ),
        totals=dict(findings=len(findings),
                    safety=sum(1 for f in findings if f.get("kind") == "safety"),
                    preference=sum(1 for f in findings if f.get("kind") == "preference"),
                    judged=len(judged),
                    allowed=sum(1 for j in judged if j.get("allowed")),
                    surfaced=len(surfaced)))


def svg(st):
    """The graph itself. Agents as nodes, shared files as edges, findings as badges."""
    nodes = st["agents"]
    W = 1180
    H = 150 + 110 * max(1, (len(nodes) + 2) // 3) + 110
    pos, parts = {}, []
    for i, n in enumerate(nodes):
        x, y = 90 + (i % 3) * 360, 70 + (i // 3) * 120
        pos[n["id"]] = (x, y)
    shared = {}
    for e in st["edges"]:
        if e["src"] in pos and e["dst"] in pos:
            x1, y1 = pos[e["src"]]
            x2, y2 = pos[e["dst"]]
            parts.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#d29922" '
                         'stroke-width="1.4" opacity="0.5" marker-end="url(#a)"/>'
                         % (x1 + 110, y1 + 46, x2 + 110, y2))
            for f in e["files"]:
                shared.setdefault(f, set()).add(e["src"])
    # One line per shared file, listing how many agents depend on it. Labelling each edge at its
    # midpoint drew every label on top of every other and made the graph unreadable.
    hot = sorted(shared.items(), key=lambda kv: -len(kv[1]))[:6]
    for i, (f, who) in enumerate(hot):
        col = "#ff7b72" if len(who) >= 2 else "#d29922"
        parts.append('<text x="20" y="%d" fill="%s" font-size="12" font-family="Menlo">'
                     '%s &larr; %d agent%s</text>'
                     % (H - 96 + i * 16, col, f[:38], len(who), "" if len(who) == 1 else "s"))
    for n in nodes:
        x, y = pos[n["id"]]
        risky = [f for f in n["findings"] if f["kind"] == "safety"]
        col = RISK_COLOR.get(risky[0]["risk"], "#7ee787") if risky else "#30363d"
        parts.append('<rect x="%d" y="%d" width="220" height="46" rx="8" fill="#161b22" '
                     'stroke="%s" stroke-width="2"/>' % (x, y, col))
        parts.append('<text x="%d" y="%d" fill="#d7dde3" font-size="13" '
                     'font-family="Menlo">%s</text>' % (x + 12, y + 20, n["id"][:24]))
        parts.append('<text x="%d" y="%d" fill="#7d8590" font-size="10" '
                     'font-family="Menlo">%s</text>'
                     % (x + 12, y + 36, ("writes " + ", ".join(n["writes"][:3]))[:34]))
        if risky:
            parts.append('<text x="%d" y="%d" fill="%s" font-size="10" font-family="Menlo">%s</text>'
                         % (x + 150, y + 36, col, risky[0]["risk"][:12]))
    return ('<svg width="%d" height="%d"><defs><marker id="a" markerWidth="8" markerHeight="8" '
            'refX="8" refY="3" orient="auto"><path d="M0,0 L0,6 L8,3 z" fill="#d29922"/></marker>'
            '</defs>%s</svg>' % (W, H, "".join(parts)))


def page():
    st = state()
    t = st["totals"]
    rows = "".join(
        '<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'
        % (p["category"] or "", p["id"], (p["rule"] or "")[:96],
           ("moved %d" % p["moved"]) if p["moved"] else p["source"] or "PRD")
        for p in st["preferences"])
    moved = "".join(
        '<li><b>%s</b>: <s>%s</s> &rarr; %s<br><i>because: "%s"</i></li>'
        % (m["id"], (m["original"] or "")[:70], (m["now"] or "")[:90], m["because"])
        for m in st["moved"]) or "<li>none yet</li>"
    return """<!doctype html><html><head><meta charset=utf-8><title>v6 oversight</title>
<style>body{background:#0d1117;color:#d7dde3;font:14px Menlo,monospace;margin:28px}
h2{color:#7ee787;font-size:15px;margin:26px 0 8px}table{border-collapse:collapse;width:100%%}
td{border-bottom:1px solid #21262d;padding:4px 8px;font-size:12px}
.k{display:inline-block;background:#161b22;border:1px solid #30363d;border-radius:6px;
padding:6px 12px;margin-right:8px}s{color:#7d8590}i{color:#d29922}</style></head><body>
<h2>v6 oversight &mdash; %s</h2>
<div><span class=k>findings %d</span><span class=k>safety %d</span>
<span class=k>preference %d</span><span class=k>judged %d</span>
<span class=k>allowed by judge %d</span><span class=k>surfaced %d</span>
<span class=k>queue safety %d / preference %d</span></div>
<h2>work graph</h2>%s
<h2>preferences</h2><table>%s</table>
<h2>preferences that have moved</h2><ul>%s</ul>
</body></html>""" % (os.path.basename(PROJ), t["findings"], t["safety"], t["preference"],
                     t["judged"], t["allowed"], t["surfaced"],
                     st["queues"]["safety"], st["queues"]["preference"],
                     svg(st), rows, moved)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/state"):
            body, ct = json.dumps(state(), default=str).encode(), "application/json"
        else:
            body, ct = page().encode(), "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8787
    print("graph on http://127.0.0.1:%d  (project: %s)" % (port, PROJ))
    HTTPServer(("127.0.0.1", port), H).serve_forever()
