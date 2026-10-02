#!/usr/bin/env python3
"""Local viewer. Run from the task folder:  python3 oversight/viewer/serve.py

Then open http://localhost:4173 . It re-reads the logs on every request and has no dependencies.
The page shows the work graph with each node's mark, and the catch-up panel in
"since you last looked" mode. Its buttons write the same files the terminal writes.
"""
import http.server, json, os, sys
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import view, align                                              # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 4173


class H(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/state":
            return self.send_json(view.state(ROOT))
        if path == "/events":
            return self.send_json(align.load_events(ROOT))
        if path in ("/", "/index.html"):
            body = open(os.path.join(ROOT, "oversight", "viewer", "index.html"), "rb").read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            q = json.loads(self.rfile.read(n) or b"{}")
            if self.path == "/look":
                return self.send_json(view.mark_looked(ROOT, q.get("node")))
            if self.path == "/caught-up":
                return self.send_json(view.mark_looked(ROOT, None))
            if self.path == "/answer":
                return self.send_json(view.answer_item(
                    ROOT, q.get("rid"), q.get("dkey"), q.get("answer"), q.get("note", ""),
                    q.get("lines"), q.get("if_accepted"), q.get("caller")))
            return self.send_json({"error": "unknown request"}, 400)
        except (ValueError, RuntimeError, KeyError) as e:
            return self.send_json({"error": str(e)}, 400)

    def send_json(self, obj, code=200):
        body = json.dumps(obj, default=list).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print("oversight viewer: http://localhost:%d  (reading %s/oversight)" % (PORT, ROOT))
    http.server.ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
