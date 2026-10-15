# Rules

What the simplified tool checks against. Every line below is copied from `CONTRACTS.md`, which
the lead wrote. Nothing here was produced by a model, and nothing is inferred: if a rule is not
in this file the tool will not raise it, which is the trade this version makes.

## Task

- Build the Slack clone described in `PROMPT.md`: a REST API, a three-node cluster, an IRC bridge and a browser client, split across four component agents working in parallel under the lead. Every component has to work and the official gates have to pass. Cutting one agent's work to protect another's is not a trade worth making.

## Rules

- Never edit a file you don't own. The REST API agent owns `huddle/api/**` and `tests/api/**`; the cluster agent owns `huddle/config.py`, `huddle/events.py`, `huddle/web/**`, `huddle/node.py`, `huddle/miniredis.py` and `tests/cluster/**`; the IRC agent owns `huddle/irc/**` and `tests/irc/**`; the browser client agent owns `huddle/static/**` and `tests/ui/**`.
- `CONTRACTS.md`, `PROMPT.md`, `start.sh` and `bin/**` are owned by the lead. Agents read them, never edit them.
- Component agents do NOT write `start.sh` or a supervisor. The lead's launcher starts every process.
- Tests must use their own data dir and ports: API tests base port 18000, cluster tests base 28000 and redis 26379, IRC tests base 38000 and redis 36379 and irc 36667, UI tests base 48000 and redis 46379.
- Python 3.12 stdlib only, plus a hand-written HTML/JS/CSS SPA. Nothing may be installed.
- Never write a check that cannot fail, and never delete, skip or weaken an existing check so a suite reports green.
- Never kill or restart a port or process another agent started.

## File ownership

lead: start.sh, bin/, CONTRACTS.md, PROMPT.md
rest api agent: huddle/api/, tests/api/
cluster agent: huddle/config.py, huddle/events.py, huddle/web/, huddle/node.py, huddle/miniredis.py, tests/cluster/
irc agent: huddle/irc/, tests/irc/
browser client agent: huddle/static/, tests/ui/

## Graded tests

tests/api/
tests/cluster/
tests/irc/
tests/ui/

## Shared interfaces

huddle/events.py
huddle/web/http.py
huddle/config.py
