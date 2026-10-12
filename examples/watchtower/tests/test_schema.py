import pytest
from core.schema import SEVERITIES, severity_rank, event, validate


def test_severity_order_is_exact():
    assert SEVERITIES == ["debug", "info", "warn", "error", "fatal"]
    assert severity_rank("debug") == 0
    assert severity_rank("fatal") == 4
    assert severity_rank("warn") < severity_rank("error")


def test_unknown_severity_raises():
    with pytest.raises(ValueError):
        severity_rank("loud")


def test_event_has_exactly_five_keys():
    ev = event("api", "warn", "slow response", ts=1000)
    assert set(ev) == {"id", "source", "severity", "message", "ts"}
    assert ev["source"] == "api"
    assert ev["severity"] == "warn"
    assert ev["message"] == "slow response"
    assert ev["ts"] == 1000


def test_event_id_is_stable_12_hex():
    a = event("api", "warn", "m", ts=5)
    b = event("api", "warn", "m", ts=5)
    c = event("api", "error", "m", ts=5)
    assert a["id"] == b["id"]
    assert a["id"] != c["id"]
    assert len(a["id"]) == 12
    assert a["id"] == a["id"].lower()
    int(a["id"], 16)


def test_default_ts_is_an_int():
    assert isinstance(event("api", "info", "x")["ts"], int)


def test_validate():
    assert validate(event("db", "info", "ok", ts=1)) is True
    assert validate({"id": "x", "source": "db"}) is False
    bad = event("db", "info", "ok", ts=1)
    bad["severity"] = "loud"
    assert validate(bad) is False
    extra = event("db", "info", "ok", ts=1)
    extra["host"] = "h1"
    assert validate(extra) is False
