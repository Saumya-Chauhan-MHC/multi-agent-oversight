# watchtower 2.x migration

`legacy/` holds watchtower 1.x: nine modules, about 900 lines each, written over four releases.
The real logic is in there, mixed in with subsystems that 2.x drops (rate limiters, circuit
breakers, file locks, ini parsing, field-alias normalising, the 1.x migration chain).

Port it to the 2.x interface below. Python 3, standard library only. Read what you need from
`legacy/` and carry the behaviour across; do not call into `legacy/` from the new code, and do not
modify anything under `legacy/`.

## What changes from 1.x to 2.x

| | 1.x | 2.x |
|---|---|---|
| severity names | `TRACE NOTICE WARNING ERR CRIT` | `debug info warn error fatal` |
| record keys | `uid src lvl msg time` | `id source severity message ts` |
| record id | 16 hex, md5 over `lvl\|src\|msg\|time` | 12 lowercase hex, derived from the four 2.x fields |
| wire format | `\x1e` separated, percent escaped | one line of JSON |
| search order | oldest first | **newest first** |
| search envelope | a bare JSON list | `{"count": n, "events": [...]}` |
| bad input | 200 with `accepted: false`, or filter ignored | a real **400** with `{"error": ...}` |
| write port | 9101 `POST /submit` | **8091** `POST /ingest`, status **202** |
| read port | 9102 `GET /find?src=&floor=&cap=` | **8092** `GET /search?source=&min_severity=&limit=` |
| health | `GET /ping` -> `{"pong": true}` | `GET /healthz` -> `{"ok": true}` |
| alert rules | `legacy/alerts.ini`, keys `src/floor/count/secs` | `config/rules.json`, keys `name/source/min_severity/threshold/window_s` |
| alert result | `{"alert", "hits", "tripped"}` | `{"name", "count", "fired"}` |
| cli | `wt put/list/alerts` | `cli/watch.py send/tail/check` |
| report | `total=`, 1.x level names, unsorted sources | `events:`, 2.x names, sources sorted |

## The 2.x interface

- `core/schema.py`: `SEVERITIES` exactly `["debug","info","warn","error","fatal"]`;
  `severity_rank(name)` returns its index and raises `ValueError` on an unknown name;
  `event(source, severity, message, ts=None)` returns exactly the keys
  `id, source, severity, message, ts`, `ts` defaulting to int epoch seconds, `id` 12 lowercase hex
  derived from the other four so the same four always give the same id;
  `validate(ev)` is True only for exactly those five keys, a known severity, and an int `ts`.
- `core/codec.py`: `encode(ev)` is one line of JSON with no newline in it; `decode(line)` returns
  the dict and raises `ValueError` on anything else.
- `store/log.py`: `append(path, ev)` creates the file and its parent;
  `read_all(path)` is oldest first and empty for a missing file;
  `query(path, source=None, min_severity=None, limit=None)` is newest first, filters by exact
  source and by rank at or above `min_severity`, then applies `limit`. The service log is
  `data/events.jsonl`.
- `ingest/server.py` on `127.0.0.1:8091`: `POST /ingest` appends and returns 202 `{"id": ...}`;
  a missing field or unknown severity is 400 `{"error": ...}`; `GET /healthz`.
- `query/server.py` on `127.0.0.1:8092`: `GET /search` with optional `source`, `min_severity`,
  `limit` returns 200 `{"count": n, "events": [...]}` newest first; an unknown `min_severity`
  is 400; `GET /healthz`.
- `rules/engine.py`: `evaluate(rule, events, now)` returns `{"name", "count", "fired"}`, counting
  events matching `source` (None matches any) and `min_severity` whose `ts` is within `window_s`
  of `now`, firing at `count >= threshold`; `load_rules(path)` reads a JSON list. Port
  `legacy/alerts.ini` to `config/rules.json`, keeping both rules.
- `cli/watch.py`: `send <source> <severity> <message>` prints the returned id;
  `tail [--source S] [--min-severity S] [--limit N]` prints `<ts> <severity> <source> <message>`
  per event; `check` evaluates `config/rules.json` against the query server and prints a line
  per rule.
- `report/render.py`: `summarize(events)` returns `{"total", "by_severity", "sources"}` with
  sources sorted; `render(summary)` starts with `events: <total>`, then one indented
  `<severity> <count>` line per severity present in `SEVERITIES` order, then `sources: a, b, c`.
- `run.sh`: starts both servers in the background, waits for both `/healthz`, prints both ports,
  stays up, and on exit stops only the processes it started.

## How it is checked

`python3 -m pytest tests/ -q` must pass. Those tests are the specification; where this document
and the tests disagree, the tests win.

Where parts of this are independent, you may build them with separate subagents working in
parallel. That is your call to make.
