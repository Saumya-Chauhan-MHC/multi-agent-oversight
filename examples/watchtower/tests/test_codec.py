import pytest
from core.codec import encode, decode
from core.schema import event


def test_round_trip_on_one_line():
    ev = event("api", "info", "hello world", ts=7)
    line = encode(ev)
    assert "\n" not in line
    assert decode(line) == ev


def test_message_with_newline_still_encodes_to_one_line():
    ev = event("api", "info", "line one\nline two", ts=7)
    line = encode(ev)
    assert "\n" not in line
    assert decode(line)["message"] == "line one\nline two"


def test_decode_rejects_junk():
    with pytest.raises(ValueError):
        decode("not json at all")
