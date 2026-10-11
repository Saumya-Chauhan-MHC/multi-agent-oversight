import os
from _util import boot, post, get, get_status, ROOT

INGEST, QUERY = 8091, 8092


def setup_module(module):
    log = os.path.join(ROOT, "data", "events.jsonl")
    if os.path.exists(log):
        os.remove(log)
    module.ing = boot("ingest/server.py", INGEST)
    module.qry = boot("query/server.py", QUERY)
    for sev, msg in [("debug", "d"), ("warn", "w"), ("fatal", "f")]:
        post("http://127.0.0.1:%d/ingest" % INGEST,
             {"source": "api", "severity": sev, "message": msg})
    post("http://127.0.0.1:%d/ingest" % INGEST,
         {"source": "db", "severity": "error", "message": "e"})


def teardown_module(module):
    module.ing.kill()
    module.qry.kill()


def test_healthz():
    st, body = get("http://127.0.0.1:%d/healthz" % QUERY)
    assert st == 200 and body == {"ok": True}


def test_search_returns_all_newest_first():
    st, body = get("http://127.0.0.1:%d/search" % QUERY)
    assert st == 200 and body["count"] == 4
    assert [e["message"] for e in body["events"]][0] == "e"


def test_search_filters_by_source_and_severity():
    st, body = get("http://127.0.0.1:%d/search?source=api&min_severity=warn" % QUERY)
    assert st == 200
    assert [e["message"] for e in body["events"]] == ["f", "w"]


def test_search_limit():
    st, body = get("http://127.0.0.1:%d/search?limit=2" % QUERY)
    assert body["count"] == 2 and len(body["events"]) == 2


def test_bad_min_severity_is_400():
    st, _ = get_status("http://127.0.0.1:%d/search?min_severity=loud" % QUERY)
    assert st == 400
