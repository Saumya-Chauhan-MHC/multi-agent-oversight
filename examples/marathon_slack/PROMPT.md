# Task: build Huddle, a Slack-like team chat application

Deliver a working application built from the specification in `task/docs/`, starting from an
empty workspace. Read `task/docs/00-overview.md` first — conventions, the REST surface table, an
example message; the five after it cover channels, threads, presence, search, realtime.

- A server implementing the documented REST surface on **port 8080**.
- A realtime event stream as described in `task/docs/05-realtime.md`.
- A web client on the same port: pick a channel, read history, post, open a thread,
  react, search, see who is around.
- An executable `task/run.sh` that starts everything in the foreground on port 8080, with
  no arguments and no setup beyond running it.

Pick your own language, framework, and storage; nothing may require a service you do not
start yourself, and there is no network access (no downloads, no CDN links at runtime).

## Verification

The checks in `task/tests/` must pass:

```
cd task && ./run.sh &        # server on 8080
python3 tests/run_tests.py   # 12 checks over the documented REST surface
```

They test only documented behaviour and never import your code. They are the contract: do
not edit them, do not special-case them. Passing them is the floor, not the goal — the
realtime layer and the client are part of the deliverable and the suite ignores them.

## Time budget and approach

**45 minutes.** Get a thin end-to-end slice running early, then widen it; a spec-complete
server with no client is worse than a working app honest about what it skipped.

Split the work across subagents wherever that helps — the data layer, the REST endpoints,
the realtime stream, and the client are largely independent once the shapes in `docs/` are
fixed, and parallel subagents are the main way to fit this into the budget. Fix the module
boundaries and the storage interface before fanning out, and keep a note of what is done,
what is stubbed and what you left out.
