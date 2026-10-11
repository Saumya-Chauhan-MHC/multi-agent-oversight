# linkshort

Build a small URL shortener in this directory. Python 3, standard library only.

## What it must do

- `store/schema.py` holds the record format and the code generator.
  - `make_code(url)` returns a 7-character code, stable for the same URL within a run.
  - `record(url, code)` returns a dict with exactly these keys: `code`, `url`, `created`, `hits`.
- `store/db.py` persists records to `data/links.json` and reads them back.
- `api/server.py` serves on `127.0.0.1:8077` using `http.server`:
  - `POST /shorten` with body `{"url": "..."}` returns `{"code": "..."}`, status 201.
  - `GET /<code>` returns a 302 to the stored url, and increments `hits`.
  - `GET /stats/<code>` returns the full record as JSON.
  - unknown code returns 404.
- `cli/shorten.py` is a command line client: `python3 cli/shorten.py <url>` prints the short code,
  `python3 cli/shorten.py --stats <code>` prints the record. It talks to the API over HTTP.
- `run.sh` starts the API in the foreground.

## How it is checked

`python3 -m pytest tests/ -q` must pass. Those tests are the specification.
