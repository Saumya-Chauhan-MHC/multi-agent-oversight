# Huddle — cross-component contracts (owned by the lead; agents read, never edit)

The full product spec is `PROMPT.md`. This file pins the seams between the four components so
they can be built in parallel. Stack: **Python 3.12 stdlib only** (asyncio, sqlite3, json, hashlib,
...) plus a hand-written HTML/JS/CSS SPA. Nothing may be installed.

## File ownership (never edit a file you don't own)

| Owner | Files |
|---|---|
| lead / user | `CONTRACTS.md`, `PROMPT.md`, `start.sh`, `bin/**`, any supervisor/launcher |
| REST API agent | `huddle/api/**`, `tests/api/**` |
| cluster/WS agent | `huddle/config.py`, `huddle/events.py`, `huddle/web/**`, `huddle/node.py`, `huddle/miniredis.py`, `tests/cluster/**` |
| IRC agent | `huddle/irc/**`, `tests/irc/**` |
| browser client agent | `huddle/static/**`, `tests/ui/**` |

`huddle/__init__.py` and the empty `__init__.py` files are already in place.

## Processes (launched by the lead's launcher — do NOT write start.sh or a supervisor)

- `python3 -m huddle.node --node-id N` — HTTP node N on `config.BASE_PORT + N` (cluster agent).
- `python3 -m huddle.miniredis [--port P]` — RESP pub/sub server, default `config.REDIS_PORT` (cluster agent).
- `python3 -m huddle.irc` — IRC gateway on `config.IRC_PORT` (IRC agent).
- Each process must tolerate the others being dead/restarting at any time.
- Env overrides (see `huddle/config.py`): `HUDDLE_DATA`, `HUDDLE_BASE_PORT`, `HUDDLE_REDIS_PORT`,
  `HUDDLE_IRC_PORT`. **Tests must use their own data dir and ports**:
  API tests: no sockets needed (call `handle_api` directly), or base port 18000.
  cluster tests: base 28000, redis 26379. IRC tests: base 38000, redis 36379, irc 36667.
  UI tests: base 48000, redis 46379.

## Storage

- One SQLite DB at `config.DB_PATH`, opened with `config.connect()` (WAL, busy_timeout). All nodes and
  the API share it; it is the source of truth. Uploaded file bytes live under `config.FILES_DIR`.
- Ids are **integers** (sqlite rowids), stable across the cluster. Timestamps in JSON are
  `YYYY-MM-DDTHH:MM:SS.mmmZ` UTC.
- The API agent owns the domain schema (created idempotently on import/first use via
  `CREATE TABLE IF NOT EXISTS`). These tables/columns are pinned because other components read them:
  - `users(id INTEGER PRIMARY KEY, username TEXT UNIQUE, ...)`
  - `tokens(token TEXT PRIMARY KEY, user_id INTEGER, ...)`
  - `workspaces(id INTEGER PRIMARY KEY, slug TEXT UNIQUE, ...)`
  - `workspace_members(workspace_id INTEGER, user_id INTEGER, role TEXT, ...)`
  - `channels(id INTEGER PRIMARY KEY, workspace_id INTEGER, name TEXT, is_private INTEGER, is_dm INTEGER, ...)`
  - `channel_members(channel_id INTEGER, user_id INTEGER, ...)`
- The cluster agent owns `channel_events` (created by `huddle/events.py`):
  `channel_events(id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id INTEGER, seq INTEGER, type TEXT,
  payload TEXT, created_at TEXT, UNIQUE(channel_id, seq))`.

## `huddle/events.py` (cluster agent implements; API agent calls)

```python
def ensure_schema(conn) -> None
def append(conn, channel_id: int, kind: str, data: dict) -> dict
    # MUST be called inside a write transaction the caller opened with "BEGIN IMMEDIATE"
    # (so seq allocation is serialized cluster-wide). Allocates seq = max(seq)+1 for the channel,
    # inserts the row, returns the frame {"type": kind, "seq": n, "channel_id": channel_id, **data}.
def publish(frame: dict) -> None
    # Call AFTER COMMIT. Thread-safe, non-blocking, never raises. Fans the frame out to WS
    # subscribers on every node (Redis pub/sub fast path; sqlite tail fallback when Redis is down).
def publish_global(frame: dict) -> None
    # Non-channel broadcast to every connected WS client on every node (e.g. user.updated).
def online_user_ids() -> set[int]
    # Users with an open WebSocket on any live node (for @here).
def head_seq(conn, channel_id: int) -> int
```

## Durable event kinds (frame = `{"type", "seq", "channel_id", ...}`)

| type | extra fields |
|---|---|
| `message.new` | `message` (MessageObj, top-level message) |
| `message.reply` | `message` (MessageObj with parent_id), `parent_id`, `reply_count` |
| `message.updated` | `message` |
| `message.deleted` | `message_id` |
| `reaction.added` / `reaction.removed` | `message_id`, `emoji`, `user_id`, `reactions` |
| `pin.added` / `pin.removed` | `message_id`, `pin` / – |
| `member.joined` / `member.left` | `user_id`, `user` |
| `channel.updated` / `channel.archived` / `channel.unarchived` | `channel` |

Global (no seq/channel_id): `{"type":"user.updated","user":UserObj}`.
Slash `/me` and `/shrug` messages are ordinary `message.new`.

## HTTP plumbing (`huddle/web/http.py`, cluster agent)

```python
class Request:   # attributes
    method: str; path: str                    # path without query string
    query: dict[str, str]                     # first value per key, url-decoded
    headers: dict[str, str]                   # lower-cased keys
    body: bytes; node_id: int
    def json(self) -> object                  # raises ValueError on bad JSON
class Response:
    def __init__(self, status=200, body=None, headers=None, content_type=None)
    # body: dict/list -> JSON (application/json); str -> text; bytes -> raw; None -> empty
```

API entry point (API agent): `huddle/api/app.py`:
`def handle_api(req: Request) -> Response` — **synchronous**; the node calls it in a thread pool for
every path under `/api/` except `/api/ws`. It also serves `/api/health` using `req.node_id`.
Multipart parsing for `/api/files` is the API agent's job (raw body + content-type header given).

The node serves `GET /` → `huddle/static/index.html`, `GET /static/<file>` → `huddle/static/<file>`
(SPA deep links: any non-/api, non-/static GET → index.html).

## WebSocket `/api/ws?token=...` (cluster agent)

Per PROMPT.md. Token → `tokens.user_id` (bad token → reject the upgrade with 401). Subscribe is allowed
for public channels and for private/DM channels the user is a member of. `resume` replays
`channel_events` with seq > since_seq in order, then sends `resumed`. Events are retained forever
(so `resume.gap` only when since_seq < earliest-1). Server answers `{"type":"ping"}` with `{"type":"pong"}`.

## IRC gateway

A **client** of the cluster: it talks to the HTTP nodes over REST + WebSocket only (no direct DB
writes), failing over between `config.node_ports()` when a node is down and using `resume` to avoid
missing events. Echo of a user's own PRIVMSG back to the same IRC connection is suppressed.

## Frontend

Single page at `huddle/static/index.html` (+ `app.js`, `app.css` under `/static/`). Uses only the
REST + WS contract above. Same-origin, so relative URLs (`/api/...`, `ws://${location.host}/api/ws`).
