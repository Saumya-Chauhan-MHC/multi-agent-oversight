import os
from _util import boot, post, get, ROOT

PORT = 8091


def setup_module(module):
    module.proc = boot("ingest/server.py", PORT)


def teardown_module(module):
    module.proc.kill()


def test_healthz():
    st, body = get("http://127.0.0.1:%d/healthz" % PORT)
    assert st == 200 and body == {"ok": True}


def test_ingest_accepts_and_returns_id():
    st, body = post("http://127.0.0.1:%d/ingest" % PORT,
                    {"source": "api", "severity": "error", "message": "boom"})
    assert st == 202
    assert len(body["id"]) == 12
    assert os.path.exists(os.path.join(ROOT, "data", "events.jsonl"))


def test_ingest_rejects_bad_severity():
    st, body = post("http://127.0.0.1:%d/ingest" % PORT,
                    {"source": "api", "severity": "loud", "message": "x"})
    assert st == 400 and "error" in body


def test_ingest_rejects_missing_field():
    st, body = post("http://127.0.0.1:%d/ingest" % PORT, {"source": "api"})
    assert st == 400 and "error" in body
