from core.schema import event
from report.render import summarize, render

EVENTS = [
    event("api", "error", "a", ts=3),
    event("api", "info", "b", ts=2),
    event("db", "info", "c", ts=1),
]


def test_summarize():
    s = summarize(EVENTS)
    assert s["total"] == 3
    assert s["by_severity"] == {"error": 1, "info": 2}
    assert s["sources"] == ["api", "db"]


def test_render_shape():
    text = render(summarize(EVENTS))
    lines = [l for l in text.splitlines() if l.strip()]
    assert lines[0] == "events: 3"
    body = [l.strip() for l in lines[1:] if not l.startswith("sources")]
    assert body == ["info 2", "error 1"]          # SEVERITIES order, absent ones omitted
    assert lines[-1] == "sources: api, db"


def test_render_empty():
    text = render(summarize([]))
    assert text.splitlines()[0] == "events: 0"
