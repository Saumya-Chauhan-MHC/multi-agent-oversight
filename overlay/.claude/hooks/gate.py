#!/usr/bin/env python3
"""Alignment gate (PreToolUse, matcher Agent|Task).

Runs on every proposed subagent spawn, the orchestration decision we can always see.

  1. Group it.   A parent proposing nine lexers in one plan is ONE decision; later children of the
                 same decision inherit the first answer instead of asking again.
  2. Judge it.   One `claude -p` call against the user's own lines (oversight/judge.py).
  3. Route it.   departs + high confidence  -> hold the spawn and ask
                 nothing the user said covers it -> tell them, do not hold
                 fits -> silent, the node just gets its mark

An answer becomes a new line in the user's words, and a note goes back to the parent.

Two surfaces, chosen by `surface_mode` in oversight/memory/settings.json:
  ask   Claude Code's own prompt carries the question (one terminal). Default.
  file  the decision arrives as a file, written by ctl.py, the viewer, or a test.

Everything fails open: no session model, no judge, a crash or a timeout and the spawn proceeds with
the reason recorded. The tool must never be why a run dies.
"""
import sys, json, os, time, hashlib, subprocess

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
if data.get("tool_name") not in ("Agent", "Task"):
    sys.exit(0)

PROJ = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
OV = os.path.join(PROJ, "oversight")
CTL = os.path.join(OV, "control")
PENDING, DECISIONS = os.path.join(CTL, "pending"), os.path.join(CTL, "decisions")
CHECKS = os.path.join(CTL, "checks")      # told, not waiting: nothing is blocked on these
ASKED = os.path.join(CTL, "asked")        # handed to Claude Code's own prompt; we do not hold it
SLOT = os.path.join(CTL, "slot_open")
ANSWERED = os.path.join(CTL, "answered.jsonl")
sys.path.insert(0, OV)


def allow():
    sys.exit(0)


def out(obj):
    print(json.dumps(obj))
    sys.exit(0)


def deny(reason, sysmsg=None):
    o = {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                "permissionDecision": "deny", "permissionDecisionReason": reason}}
    if sysmsg:
        o["systemMessage"] = sysmsg
    out(o)


def ask(question, sysmsg):
    out({"systemMessage": sysmsg,
         "hookSpecificOutput": {"hookEventName": "PreToolUse",
                                "permissionDecision": "ask", "permissionDecisionReason": question}})


try:
    import memory, judge, align
except Exception:
    allow()

ti = data.get("tool_input") or {}
desc = (ti.get("description") or "").strip()
prompt = (ti.get("prompt") or "").strip()
if not desc and not prompt:
    allow()

st = memory.settings()
model = memory.load()
if not model:
    allow()                                   # init never run: nothing to align to

for d in (PENDING, DECISIONS, CHECKS, ASKED, os.path.join(OV, "judgements")):
    os.makedirs(d, exist_ok=True)

# ---------------------------------------------------------------- which decision this spawn is part of
caller, parent_status = align.parent_status(PROJ, data.get("agent_id"))
fam = align.brief_family(prompt)
dkey = hashlib.sha256(json.dumps([caller, fam], sort_keys=True).encode()).hexdigest()[:12]
rid = "%s-%d" % (dkey, int(time.time() * 1000))

prior = align.answered_for(ANSWERED, dkey)
if prior and prior.get("answer") in ("accept", "accept_all"):
    allow()                                   # same decision, already accepted: no judge, no question
if prior and prior.get("answer") == "no":
    deny("[oversight] You already declined this split. The user's note: %s" % prior.get("note", ""),
         "oversight: same decision you declined; not asking again")
if os.path.exists(os.path.join(CTL, "standing_%s.json" % caller)):
    allow()                                   # "yes, and don't ask again for this parent"

# ---------------------------------------------------------------- judge it
# The brief itself is the evidence. We do not hand the judge a scraped file list: a path can
# appear in a sentence that says NOT to touch it, and a scraped list turns that into a flag.
decision = dict(kind="spawn", name=desc, task=prompt[:1200])
t0 = time.time()
verdict = judge.judge_decision(OV, decision, parent_status, model=model, settings=st)
judge_s = round(time.time() - t0, 1)
band = judge.band(verdict, st, model=model, dimension="division")

jrec = dict(rid=rid, dkey=dkey, ts=align.now_ms(), caller=caller,
            parent_label=parent_status["name"], child=desc, files=align.paths_in(prompt),
            judge_s=judge_s, band=band,
            **{k: verdict.get(k) for k in ("verdict", "covered", "governed_by", "confidence", "evidence",
                                           "precedent", "suggestion", "if_accepted", "source")})
json.dump(jrec, open(os.path.join(OV, "judgements", rid + ".json"), "w"), indent=1)
align.append_event(PROJ, dict(ov_event="judgement", **jrec))
align.credit_pause(PROJ, judge_s)             # the judge's latency is our overhead, not the agent's

if band == "silent":
    allow()

req = dict(rid=rid, dkey=dkey, ts=align.now_ms(), caller=caller, parent_label=parent_status["name"],
           child=desc, prompt=prompt[:2000], band=band, judgement=jrec)
# `pending` means "this hook is still running and the spawn is blocked on you". A check never blocks,
# and in ask mode the question belongs to Claude Code, so neither goes there.
where = CHECKS if band == "check" else (ASKED if st.get("surface_mode", "ask") == "ask" else PENDING)
json.dump(req, open(os.path.join(where, rid + ".json"), "w"), indent=1)

# The spawn runs and the user is simply told; unanswered, it becomes a catch-up item, which is what
# the SSOT asks for when a check goes unanswered.
if band == "check":
    align.bump(PROJ, "checks_unanswered", 1)
    out({"systemMessage": align.notice_text(jrec, "check", caller) +
         "\n  nothing is paused; answer later in the viewer, or ignore it"})

# ---------------------------------------------------------------- hold: one question at a time
wait_start = time.time()
while not align.slot_free(SLOT):
    if time.time() - wait_start > int(st.get("slot_wait_s", 900)):
        break
    time.sleep(0.5)
    a = align.answered_for(ANSWERED, dkey)    # an answer to a sibling may have covered this one
    if a:
        align.credit_pause(PROJ, time.time() - wait_start)
        if a.get("answer") in ("accept", "accept_all"):
            allow()
        deny("[oversight] You declined this split. Note: %s" % a.get("note", ""))
open(SLOT, "w").write(rid)
align.credit_pause(PROJ, time.time() - wait_start)

# The graph opens itself only here, on a high-confidence departure. A check carries the link but
# opens nothing, and a fit shows neither: the viewer is not a second screen to watch.
if st.get("open_dag_on_hold", True):
    try:
        subprocess.Popen(["open", "-g", "http://localhost:%s/?focus=%s&rid=%s" %
                          (st.get("viewer_port", 4173), caller, rid)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

if st.get("surface_mode", "ask") == "ask":
    # Claude Code's own prompt asks. Its answer reaches us as the tool running or not; the user's
    # note on a "no" is picked up from their next message by note_capture.py.
    json.dump(dict(rid=rid, dkey=dkey, caller=caller, child=desc, parent=parent_status["name"],
                   if_accepted=verdict.get("if_accepted"),
                   lines=sorted({e.get("line_id") for e in verdict["evidence"] if e.get("line_id")}),
                   suggestion=verdict.get("suggestion")),
              open(os.path.join(CTL, "awaiting_answer.json"), "w"), indent=1)
    # The evidence goes in the reason, which Claude Code always renders inside its own dialog.
    # systemMessage alone was not reliably visible next to the prompt.
    ask(align.notice_text(jrec, "hold", caller) +
        "\n\nLet this subagent start?  (%s)\n"
        "  1 yes    2 yes, stop asking for this folder (Claude Code's own rule)    3 no"
        % (desc or "unnamed"),
        align.notice_text(jrec, "hold", caller))

# file mode: the decision arrives as a file from ctl.py, the viewer, or a test
dp = os.path.join(DECISIONS, rid + ".json")
t0 = time.time()
dec = None
while time.time() - t0 < int(st.get("decision_timeout_s", 1800)):
    if os.path.exists(dp):
        try:
            dec = json.load(open(dp))
            break
        except Exception:
            pass
    time.sleep(0.4)
align.credit_pause(PROJ, time.time() - t0)
align.clear(SLOT)
align.clear(os.path.join(PENDING, rid + ".json"))

if dec is None:
    align.bump(PROJ, "flags_unanswered", 1)
    allow()                                   # nobody in reach: record it, do not strand the run

answer = dec.get("answer", "accept")
usernote = (dec.get("note") or "").strip()
align.record_answer(ANSWERED, dict(dkey=dkey, rid=rid, answer=answer, note=usernote, ts=align.now_ms()))
lines = sorted({e.get("line_id") for e in verdict["evidence"] if e.get("line_id")})

if answer in ("accept", "accept_all"):
    if verdict.get("if_accepted"):
        memory.append_answer(verdict["if_accepted"], lines, source="answer (accept)", rid=rid)
    if answer == "accept_all":
        json.dump(dict(parent=caller, ts=align.now_ms()),
                  open(os.path.join(CTL, "standing_%s.json" % caller), "w"))
    align.record_intervention(PROJ, caller, desc, answer, usernote, jrec)
    allow()

# "no, tell the parent": the child never starts, the note reaches the parent, and the user's own
# words become the line every later judgement is measured against.
memory.append_answer(usernote or (verdict["suggestion"].get("note") or "do not do this"),
                     lines, source="answer (no)", rid=rid)
align.send_to_agent(PROJ, caller,
                    "[oversight] The user did not allow your spawn \"%s\" as proposed.\n"
                    "Their note: %s\nRe-plan accordingly." % (desc, usernote or "see your brief"))
align.record_intervention(PROJ, caller, desc, "no", usernote, jrec)
deny("[oversight] The user did not allow this spawn. Their note: %s" % (usernote or "re-plan"),
     "oversight: spawn declined; your note was sent to %s" % parent_status["name"])
