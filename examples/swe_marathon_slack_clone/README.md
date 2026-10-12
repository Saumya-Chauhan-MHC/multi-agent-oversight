# The task the tool was evaluated on

SWE-Marathon `slack-clone` (Abundant AI). Build a Slack-style chat system: three HTTP nodes on
`127.0.0.1:8000-8002`, an RFC 2812 IRC gateway on `:6667`, a local Redis pub/sub daemon, a browser
SPA, all launched by one `start.sh` that stays in the foreground. Python 3.12 stdlib only.

| file | what it is |
|---|---|
| `PROMPT.md` | the task brief as given to the agent. The benchmark's own text, plus a three-line environment note at the top: `/app` means this directory, there is no preinstalled Redis, and independent parts **may** be built by separate subagents. That last line is permission, not instruction |
| `CONTRACTS.md` | the developer's decomposition instructions: a five-row file-ownership table, the three launch commands, per-component test ports, the pinned SQLite columns, and the `events.py` / `http.py` signatures. This is what the extractor turns into task preferences |
| `fetch_official_tests.sh` | sparse-checkouts the official tests from the public upstream repo into `official/`. Not vendored here: they are someone else's work under their own licence |

## Why this task

| | |
|---|---|
| genuinely four components | REST API, cluster/WebSocket, IRC gateway, browser SPA — so a real division-of-work decision exists to oversee |
| pinned shared seams | one SQLite file, one event log with a dense per-channel `seq`, one `Request`/`Response`, one `handle_api`. This is what makes a silent interface change expensive |
| graded per component | `tests/{api,cluster,irc,ui}`, so test success is observable rather than a proxy |
| long | 45 minutes and 2M tokens of budget, enough for the time and token metrics to mean something |
| pinned ports and processes | resource conflict becomes detectable instead of hypothetical |
| it actually produces fan-out | every run of this brief spawned subagents (4, 4, 5, 5, 4). Three smaller tasks built specifically to invite delegation produced **zero** between them |

## Running it

```bash
# 1. the task
mkdir myrun && cp PROMPT.md CONTRACTS.md myrun/
cp -R ../../overlay/.claude ../../overlay/oversight myrun/

# 2. extract the task model (once, before the agent starts)
cd myrun && BUDGET="45 minutes, 2M tokens" DRAWS=5 python3 -m oversight.v3.extract .

# 3. run it
claude -p "$(cat PROMPT.md)" --permission-mode acceptEdits

# 4. grade it against the official tests
./../fetch_official_tests.sh
python3 ../../eval/grader/run_gates.py . --tests ../official/tests \
    --python <venv python> --out ./grade
```

`OV_SIMUSER=1` on step 3 answers the tool's questions with a stand-in developer instead of a real
one, which is how an unattended arm is run. It is not a substitute for a person.
