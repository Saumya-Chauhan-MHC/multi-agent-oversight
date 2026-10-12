from core.schema import event
from store.log import append, read_all, query


def test_append_then_read_all_oldest_first(tmp_path):
    p = str(tmp_path / "sub" / "e.jsonl")
    a = event("api", "info", "one", ts=1)
    b = event("db", "error", "two", ts=2)
    append(p, a)
    append(p, b)
    assert read_all(p) == [a, b]


def test_missing_file_reads_empty(tmp_path):
    assert read_all(str(tmp_path / "nope.jsonl")) == []


def test_query_is_newest_first(tmp_path):
    p = str(tmp_path / "e.jsonl")
    for i in range(3):
        append(p, event("api", "info", "m%d" % i, ts=i))
    assert [e["ts"] for e in query(p)] == [2, 1, 0]


def test_query_filters_and_limits(tmp_path):
    p = str(tmp_path / "e.jsonl")
    append(p, event("api", "debug", "a", ts=1))
    append(p, event("api", "error", "b", ts=2))
    append(p, event("db", "fatal", "c", ts=3))
    assert [e["message"] for e in query(p, source="api")] == ["b", "a"]
    assert [e["message"] for e in query(p, min_severity="error")] == ["c", "b"]
    assert [e["message"] for e in query(p, min_severity="error", limit=1)] == ["c"]
    assert query(p, source="api", min_severity="fatal") == []
