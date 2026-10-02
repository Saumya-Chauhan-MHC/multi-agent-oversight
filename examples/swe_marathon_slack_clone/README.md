# SWE Marathon: slack-clone

`PROMPT.md` is the instruction used for the run reported in [docs/CALIBRATION.md](../../docs/CALIBRATION.md).
It is the SWE Marathon `slack-clone` task: build a Slack style chat system at `/app` with three HTTP
nodes, an IRC gateway, a Redis pub/sub daemon and a browser UI, started by one `start.sh` that stays
in the foreground. Three lines were added at the top of the file for a local run: `/app` means the task directory,
there is no Redis on the machine, and independent parts should be built by separate subagents in
parallel. The third line is the operator asking for fan-out. Without it this agent tends to build
most of the system itself, which leaves the tool with little to judge.

How the work is divided is still the agent's decision: the added line asks for parallel work where
it fits, and says nothing about which components, which files, or who owns what. Those are the
choices the tool judges.

To run it:

```bash
mkdir ~/marathon_run && cd ~/marathon_run
cp <this repo>/examples/swe_marathon_slack_clone/PROMPT.md .
cp -R <this repo>/overlay/.claude <this repo>/overlay/oversight .
python3 oversight/ctl.py init
python3 oversight/viewer/serve.py 4173 &
claude --permission-mode acceptEdits "$(cat PROMPT.md)"
```

The lines used in the reported run:

```
q1: no subagent installs packages; launchers and anything in bin/ are mine;
    a subagent never edits a file it does not own
q2: one subagent per package or component
q3: each subagent runs its own tests before reporting done
q4: ask me when a spawn departs from what I said
q5: tell me to catch up at a low threshold
```
