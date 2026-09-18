#!/usr/bin/env python3
"""Local viewer for oversight/events.jsonl.  Run from the task folder:  python3 oversight/viewer/serve.py
Then open http://localhost:4173 . Re-reads the log on every refresh; no dependencies."""
import http.server, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import control as C  # noqa: E402  interventions: shared with oversight/ctl.py
# task root = two levels up from oversight/viewer/
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 4173

class H(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/events"):
            evs = []
            p = os.path.join(ROOT, "oversight", "events.jsonl")
            if os.path.exists(p):
                for ln in open(p, errors="ignore"):
                    ln = ln.strip()
                    if ln:
                        try: evs.append(json.loads(ln))
                        except Exception: pass
            return self.send_json(evs)
        if self.path.startswith("/plan"):
            p = os.path.join(ROOT, "plan.md")
            return self.send_json({"plan": open(p).read() if os.path.exists(p) else ""})
        if self.path.startswith("/checkpoints"):
            p = os.path.join(ROOT, "oversight", "checkpoints.txt")
            return self.send_json({"checkpoints": open(p).read().splitlines() if os.path.exists(p) else []})
        if self.path.startswith("/control/status"):
            gm = os.path.join(ROOT, "oversight", "gate_mode")
            return self.send_json(dict(run=C.run_state(), gate=C.flag("gate_mode"),
                                       recommend=C.flag("recommend_mode"), pending=C.pending()))
        if self.path.startswith("/control/checkpoints"):
            return self.send_json(C.checkpoints())
        if self.path.startswith("/control/graph"):
            nodes, edges = C.dependency_graph()
            return self.send_json(edges)
        if self.path.startswith("/control/impact"):
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            try:
                return self.send_json(C.node_impact(q.get("node", [""])[0]))
            except ValueError as e:
                return self.send_json({"error": str(e)}, 400)
        if self.path.startswith("/control/interventions"):
            return self.send_json(C.interventions())
        if self.path in ("/", "/index.html"):
            body = open(os.path.join(ROOT, "oversight", "viewer", "index.html"), "rb").read()
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
        self.send_response(404); self.end_headers()
    def do_POST(self):
        """Interventions from the viewer. Same functions as the terminal, so same records."""
        try:
            n = int(self.headers.get("Content-Length") or 0)
            q = json.loads(self.rfile.read(n) or b"{}")
            k = q.get("kind")
            if self.path == "/control/gate":
                C.set_flag("gate_mode", q.get("state"))
                return self.send_json({"ok": True})
            if self.path == "/control/recommend":
                C.set_flag("recommend_mode", q.get("state"))
                return self.send_json({"ok": True})
            if self.path == "/control/decide":
                recs = [C.decide(r, q["decision"], q.get("note", ""), q.get("reset_to")) for r in q["rids"]]
                return self.send_json({"ok": True, "records": recs})
            if self.path == "/control/preview":
                if k == "reset":
                    return self.send_json(C.preview_reset(q["target"]))
                if k == "edit":
                    return self.send_json(C.preview_edit(q["node"], q["brief"]))
                if k == "instruction":
                    return self.send_json(C.preview_tell(q["node"], q["text"]))
            if self.path == "/control/apply":
                if k == "reset":
                    return self.send_json(C.apply_reset(q["target"], q.get("note", ""), q.get("force", False)))
                if k == "edit":
                    return self.send_json(C.apply_edit(q["node"], q["brief"], q.get("note", ""),
                                                       q.get("launch", False), q.get("force", False)))
                if k == "instruction":
                    return self.send_json(C.apply_tell(q["node"], q["text"], q.get("note", "")))
            if self.path == "/control/cancel":
                return self.send_json(C.record_cancel(k, q.get("target"), q.get("impact"), "cancelled at preview"))
            return self.send_json({"error": "unknown request"}, 400)
        except (ValueError, RuntimeError, KeyError) as e:
            return self.send_json({"error": str(e)}, 400)

    def send_json(self, obj, code=200):
        body = json.dumps(obj, default=list).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def log_message(self, *a): pass

if __name__ == "__main__":
    print(f"oversight viewer: http://localhost:{PORT}  (reading {ROOT}/oversight/events.jsonl)")
    http.server.ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
