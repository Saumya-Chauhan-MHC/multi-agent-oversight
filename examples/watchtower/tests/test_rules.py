import json
from core.schema import event
from rules.engine import evaluate, load_rules


def test_fires_at_threshold():
    rule = {"name": "api_errors", "source": "api", "min_severity": "error",
            "threshold": 2, "window_s": 60}
    evs = [event("api", "error", "a", ts=100), event("api", "fatal", "b", ts=120)]
    out = evaluate(rule, evs, now=130)
    assert out == {"name": "api_errors", "count": 2, "fired": True}


def test_below_threshold_does_not_fire():
    rule = {"name": "api_errors", "source": "api", "min_severity": "error",
            "threshold": 3, "window_s": 60}
    evs = [event("api", "error", "a", ts=100), event("api", "fatal", "b", ts=120)]
    assert evaluate(rule, evs, now=130)["fired"] is False


def test_window_excludes_old_events():
    rule = {"name": "api_errors", "source": "api", "min_severity": "error",
            "threshold": 1, "window_s": 10}
    evs = [event("api", "error", "old", ts=1)]
    out = evaluate(rule, evs, now=1000)
    assert out["count"] == 0 and out["fired"] is False


def test_other_source_and_lower_severity_excluded():
    rule = {"name": "api_errors", "source": "api", "min_severity": "error",
            "threshold": 1, "window_s": 60}
    evs = [event("db", "fatal", "a", ts=100), event("api", "warn", "b", ts=100)]
    assert evaluate(rule, evs, now=100)["count"] == 0


def test_null_source_matches_any():
    rule = {"name": "anything", "source": None, "min_severity": "warn",
            "threshold": 2, "window_s": 60}
    evs = [event("db", "warn", "a", ts=100), event("api", "error", "b", ts=100)]
    assert evaluate(rule, evs, now=100)["fired"] is True


def test_load_rules_from_file(tmp_path):
    p = tmp_path / "r.json"
    p.write_text(json.dumps([{"name": "x", "source": None, "min_severity": "warn",
                              "threshold": 1, "window_s": 5}]))
    loaded = load_rules(str(p))
    assert isinstance(loaded, list) and loaded[0]["name"] == "x"


def test_shipped_rules_file_loads():
    rules = load_rules("config/rules.json")
    assert isinstance(rules, list) and len(rules) >= 1
    for r in rules:
        assert set(r) == {"name", "source", "min_severity", "threshold", "window_s"}
