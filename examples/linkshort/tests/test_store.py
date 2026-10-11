import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from store.schema import make_code, record
from store import db


def test_code_is_seven_chars():
    c = make_code("https://example.com/a")
    assert isinstance(c, str) and len(c) == 7


def test_code_is_stable_within_a_run():
    assert make_code("https://example.com/b") == make_code("https://example.com/b")


def test_record_shape():
    r = record("https://example.com/c", "abcdefg")
    assert set(r.keys()) == {"code", "url", "created", "hits"}
    assert r["hits"] == 0 and r["code"] == "abcdefg"


def test_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "PATH", str(tmp_path / "links.json"), raising=False)
    r = record("https://example.com/d", "zzzzzzz")
    db.put(r)
    assert db.get("zzzzzzz")["url"] == "https://example.com/d"
    assert db.get("nosuch") is None
