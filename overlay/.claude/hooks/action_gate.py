#!/usr/bin/env python3
"""Action gate (PreToolUse on Bash, Write, Edit, MultiEdit), for subagents only.

The spawn gate judges what a brief SAYS. This judges what a child actually DOES, which is where
rules like "no subagent installs packages" or "the schema is mine" are really broken: in a live run
the orchestrator's briefs were clean and a child decided to `npm install` on its own.

Judging every tool call with a model would be absurd (hundreds per session, seconds each), so this
is two-stage:

  1. a free keyword filter: does this command or path touch words the user's own lines are about?
     No overlap, no cost, the call proceeds.
  2. only then, one judge call, cached by (command, lines).

It only ever holds a SUBAGENT's action, never the orchestrator's: the user's lines are about what
they delegate, and holding the agent they are talking to would be absurd.
"""
import sys, json, os, re, time, hashlib

def _fail_open(exc_type, exc, tb):
    """Any unhandled error: let the tool call through and leave a trace for us, never block work."""
    try:
        import traceback, tempfile
        with open(os.path.join(tempfile.gettempdir(), "oversight-hook-errors.log"), "a") as f:
            f.write("%s %s\n%s\n" % (time.strftime("%F %T"), os.path.basename(__file__),
                                      "".join(traceback.format_exception(exc_type, exc, tb))))
    except Exception:
        pass
    sys.exit(0)


sys.excepthook = _fail_open

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
if data.get("tool_name") not in ("Bash", "Write", "Edit", "MultiEdit"):
    sys.exit(0)
IS_ORCHESTRATOR = not data.get("agent_id")

PROJ = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
OV = os.path.join(PROJ, "oversight")
CTL = os.path.join(OV, "control")
sys.path.insert(0, OV)

STOP = {"the", "a", "an", "and", "or", "not", "never", "only", "from", "with", "that", "this",
        "they", "them", "than", "then", "its", "it", "is", "are", "be", "for", "in", "on", "of",
        "to", "no", "any", "all", "one", "per", "own", "mine", "my", "i", "you", "your", "subagent",
        "subagents", "agent", "agents", "must", "should", "do", "does", "doing", "run", "runs",
        "running", "before", "after", "more", "most", "less", "each", "every", "max", "at", "once"}


def allow():
    sys.exit(0)


try:
    import memory, judge, align
except Exception:
    allow()

st = memory.settings()
if not st.get("gate_actions", True):
    allow()
model = memory.load()
if not model:
    allow()

ti = data.get("tool_input") or {}
target = " ".join(str(x) for x in (ti.get("command"), ti.get("file_path"), ti.get("old_string"))
                  if x)[:2000]
if not target.strip():
    allow()

# ---------------------------------------------------------------- stage 1: free keyword filter
words = set()
for m in model:
    if str(m.get("status", "")).startswith("superseded"):
        continue
    for w in re.findall(r"[A-Za-z_][A-Za-z0-9_.\-/]{2,}", m["text"].lower()):
        if w not in STOP:
            words.add(w)
            words.add(w.rstrip("s"))          # schema/schemas, migration/migrations
low = target.lower()
hits = sorted(w for w in words if w in low)
if not hits:
    allow()

# ---------------------------------------------------------------- stage 2: one judge call, cached
key = hashlib.sha256((target + "|" + "|".join(memory.as_prompt_lines(model))).encode()).hexdigest()[:16]
seen = os.path.join(CTL, "action_seen")
os.makedirs(seen, exist_ok=True)
marker = os.path.join(seen, key + ".json")
if os.path.exists(marker):
    try:
        prev = json.load(open(marker))
        if prev.get("band") != "hold":
            allow()                           # identical action already judged fine
    except Exception:
        allow()

who, parent_status = align.parent_status(PROJ, data.get("agent_id"))
# Without the child's own brief the judge cannot tell what it owns, which produced every false
# positive in the first live run ("writes web/tests/ui_test.py" flagged as editing someone else's
# file, when its brief had handed it exactly that directory).
decision = dict(kind="action", name="%s by %s" % (data.get("tool_name"), parent_status["name"]),
                task=("This subagent was given this brief:\n%s\n\nIt is about to run:\n%s\n\n"
                      "Judge only the action. Anything the brief put inside this subagent's scope is "
                      "its own to write." % (parent_status.get("brief") or "(brief not recorded)", target)))
t0 = time.time()
verdict = judge.judge_decision(OV, decision, parent_status, model=model, settings=st)
judge_s = round(time.time() - t0, 1)
align.credit_pause(PROJ, judge_s)

rid = "act-%s-%d" % (key, int(time.time() * 1000))
jrec = dict(rid=rid, dkey="act-" + key, ts=align.now_ms(), caller=who,
            parent_label=parent_status["name"], child=(target[:90] + ("..." if len(target) > 90 else "")),
            kind="action", matched=hits[:6], judge_s=judge_s,
            band=judge.band(verdict, st, model=model),
            **{k: verdict.get(k) for k in ("verdict", "confidence", "evidence", "suggestion", "source")})
# an action only ever holds on a clear rule break; "nothing covers this" is not worth stopping work
if jrec["band"] == "check" or (IS_ORCHESTRATOR and jrec["band"] == "hold"):
    # a rule like "launchers are mine" is about the orchestrator's own hands too, but we never block
    # the agent the user is talking to: it is recorded and shown at catch-up instead
    jrec["band"] = "silent"
os.makedirs(os.path.join(OV, "judgements"), exist_ok=True)
json.dump(jrec, open(os.path.join(OV, "judgements", rid + ".json"), "w"), indent=1)
align.append_event(PROJ, dict(ov_event="judgement", **jrec))
json.dump(jrec, open(marker, "w"), indent=1)

if jrec["band"] != "hold":
    if jrec.get("verdict") == "departs":
        # believed, but not enough to interrupt: it belongs in catch-up rather than vanishing
        align.bump(PROJ, "flags_unanswered", 1)
    allow()

reason = align.notice_text(jrec, "hold", who)
print(json.dumps({"systemMessage": reason,
                  "hookSpecificOutput": {"hookEventName": "PreToolUse",
                                         "permissionDecision": "deny",
                                         "permissionDecisionReason":
                                         reason + "\n\nThis was blocked because it breaks a rule you "
                                         "wrote. Tell the agent what to do instead, or run "
                                         "`python3 oversight/ctl.py allow-action` to let it through."}}))
