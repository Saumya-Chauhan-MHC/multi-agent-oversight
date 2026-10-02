#!/usr/bin/env python3
"""Terminal control for the oversight tool. Run from the task folder:

  python3 oversight/ctl.py init                 the five questions, once, before the first prompt
  python3 oversight/ctl.py lines                the user's lines, as the judge sees them
  python3 oversight/ctl.py status               run state, counters, anything waiting
  python3 oversight/ctl.py pending              decisions waiting for an answer
  python3 oversight/ctl.py answer <rid|all> accept|accept_all|no [--note "..."]
  python3 oversight/ctl.py watch                wait for decisions and answer them here
  python3 oversight/ctl.py catchup              print the catch-up line now, and what is behind it
  python3 oversight/ctl.py caught-up            reset the counters ("I have looked")
  python3 oversight/ctl.py judgements [N]       what the judge said, most recent last

The viewer's buttons write the same files this writes, so a run can be driven from either.
"""
import sys, os, json, time, argparse, glob

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
PROJ = os.path.dirname(HERE)
import memory, align                                            # noqa: E402

CTL = align.ctl(PROJ)
PENDING, DECISIONS = os.path.join(CTL, "pending"), os.path.join(CTL, "decisions")
CHECKS = os.path.join(CTL, "checks")

QUESTIONS = [
    dict(id="q1", kind="text", prompt="1  rules a subagent must never break",
         hint="free text, hard constraints; two rules in one answer become two lines",
         default=""),
    dict(id="q2", kind="choice", prompt="2  how should the work be divided?",
         options={"a": "one subagent per package or component",
                  "b": "one subagent per file or module",
                  "c": "let the orchestrator decide"}, default="a"),
    dict(id="q3", kind="choice", prompt="3  how should the work be verified?",
         options={"a": "each subagent runs its own tests before reporting done",
                  "b": "tests only at the end, by the orchestrator"}, default="a"),
    dict(id="q4", kind="choice", prompt="4  when should I stop the agent and ask you?",
         options={"a": "when a spawn departs from the points in questions 1 to 3",
                  "b": "never; tell me at catch-up"}, default="a"),
    dict(id="q5", kind="choice", prompt="5  when should I tell you to catch up?",
         options={"a": "low: after small changes (3)",
                  "b": "medium (5)",
                  "c": "high: only after big changes (8)"}, default="b"),
]


def hub_files(proj, top=3):
    """A concrete default for q1: the files most of the work will touch.

    Guessing beats an empty box. Hub-file isolation is also the one structural rule with measured
    value in parallel coding work, so it is a sensible thing to protect by default.
    """
    cands = []
    for pat in ("__init__.py", "compile.sh", "run.sh", "setup.py", "Makefile", "package.json",
                "requirements.txt", "schema.sql", "app.py", "server.py", "main.py"):
        for p in glob.glob(os.path.join(proj, "**", pat), recursive=True):
            if "/oversight/" in p or "/.claude/" in p or "/node_modules/" in p:
                continue
            cands.append(os.path.relpath(p, proj))
    seen, out = set(), []
    for c in sorted(cands, key=len):
        b = os.path.basename(c)
        if b in seen:
            continue
        seen.add(b)
        out.append(b)
    return out[:top]


def init(argv):
    ap = argparse.ArgumentParser(prog="ctl.py init")
    ap.add_argument("--defaults", action="store_true", help="take every default, ask nothing")
    ap.add_argument("--answers", help='JSON, e.g. {"q1":"never edit run.sh","q2":"a"}')
    a = ap.parse_args(argv)

    preset = json.loads(a.answers) if a.answers else {}
    hubs = hub_files(PROJ)
    if hubs:
        QUESTIONS[0]["default"] = "never edit %s from a subagent" % " or ".join(hubs)

    print("oversight . before work     5 questions . Enter keeps the default")
    if hubs:
        print("                            q1's default comes from this repo's hub files")
    print()
    answers = {}
    for q in QUESTIONS:
        if q["id"] in preset:
            answers[q["id"]] = str(preset[q["id"]]).strip()
            print("%s\n    %s  (given)" % (q["prompt"], answers[q["id"]]))
            continue
        if a.defaults:
            answers[q["id"]] = q["default"]
            print("%s\n    %s  (default)" % (q["prompt"], q["default"]))
            continue
        print(q["prompt"])
        if q["kind"] == "choice":
            for k, v in q["options"].items():
                print("    (%s) %s" % (k, v))
        elif q.get("hint"):
            print("    %s" % q["hint"])
        got = input("    [%s] > " % q["default"]).strip()
        answers[q["id"]] = got or q["default"]
        print()

    lines = []
    for q in QUESTIONS:
        ans = answers[q["id"]]
        if q["kind"] == "choice":
            text = q["options"].get(ans, ans)
            if q["id"] in ("q4", "q5"):
                continue                                   # about the user's involvement, not the work
            lines.append(dict(id=q["id"], text=text))
        else:
            parts = [p.strip() for p in ans.replace(";", "\n").split("\n") if p.strip()]
            for i, p in enumerate(parts):
                lines.append(dict(id="q1%s" % chr(ord("a") + i), text=p))
    memory.write_init(lines)
    memory.save_settings(dict(
        involvement="ask" if answers["q4"].startswith("a") else "never",
        catchup_threshold={"a": 3, "b": 5, "c": 8}.get(answers["q5"], 5),
    ))
    print("saved      oversight/memory/session_model.json   lines %s, in your words" %
          ", ".join(l["id"] for l in lines))
    print("injected   into the orchestrator's first prompt:")
    print("           %s" % memory.i0()[:160])
    print("the task itself comes from your prompt; nothing else is asked")


def lines_cmd(_argv):
    for l in memory.as_prompt_lines():
        print("  " + l)
    if not memory.load():
        print("  (no lines yet; run: python3 oversight/ctl.py init)")


def pending(_argv):
    ps = sorted(glob.glob(os.path.join(PENDING, "*.json")))
    cs = sorted(glob.glob(os.path.join(CHECKS, "*.json")))
    if not ps and not cs:
        print("nothing waiting")
        return
    for p in cs:
        r = json.load(open(p))
        print("  %s  [check, nothing is blocked]  %s -> %s" % (r["rid"], r["parent_label"], r["child"]))
    for p in ps:
        r = json.load(open(p))
        print("  %s  [%s]  %s -> %s" % (r["rid"], r["band"], r["parent_label"], r["child"]))
        print(align.notice_text(r["judgement"], r["band"], r["caller"]))
        print()


def answer(argv):
    ap = argparse.ArgumentParser(prog="ctl.py answer")
    ap.add_argument("rid")
    ap.add_argument("decision", choices=["accept", "accept_all", "no"])
    ap.add_argument("--note", default="")
    a = ap.parse_args(argv)
    os.makedirs(DECISIONS, exist_ok=True)
    rids = ([os.path.basename(p)[:-5] for p in glob.glob(os.path.join(PENDING, "*.json"))]
            if a.rid == "all" else [a.rid])
    if not rids:
        print("nothing waiting")
        return
    for rid in rids:
        json.dump(dict(answer=a.decision, note=a.note, ts=align.now_ms()),
                  open(os.path.join(DECISIONS, rid + ".json"), "w"))
        print("answered %s: %s%s" % (rid, a.decision, (" - " + a.note) if a.note else ""))
    align.reset_look(PROJ, "answered a notice")


def watch(_argv):
    print("waiting for decisions; ctrl-c to stop")
    seen = set()
    while True:
        for p in sorted(glob.glob(os.path.join(PENDING, "*.json"))):
            rid = os.path.basename(p)[:-5]
            if rid in seen:
                continue
            seen.add(rid)
            r = json.load(open(p))
            print()
            print(align.notice_text(r["judgement"], r["band"], r["caller"]))
            if r["band"] != "hold":
                continue
            print("  1. yes   2. yes, and don't ask again for this parent   3. no, tell the parent")
            try:
                c = input("  > ").strip()
            except (EOFError, KeyboardInterrupt):
                return
            dec = {"1": "accept", "2": "accept_all", "3": "no"}.get(c, "accept")
            note = input("  note to the parent > ").strip() if dec == "no" else ""
            json.dump(dict(answer=dec, note=note, ts=align.now_ms()),
                      open(os.path.join(DECISIONS, rid + ".json"), "w"))
            align.reset_look(PROJ, "answered a notice")
            print("  recorded")
        time.sleep(0.5)


def counters_line(c, st):
    unseen = c.get("unseen_files", 0) // 10
    total = (c.get("flags_unanswered", 0) + c.get("checks_unanswered", 0)
             + 2 * c.get("repeat_flags", 0) + unseen)
    return total, ("outdatedness %d = %d departures x1 + %d unanswered checks x1 + %d repeats x2 + %d "
                   "(%d unseen edits); your threshold is %d" %
                   (total, c.get("flags_unanswered", 0), c.get("checks_unanswered", 0),
                    c.get("repeat_flags", 0), unseen, c.get("unseen_files", 0),
                    st.get("catchup_threshold", 5)))


def accept_all(argv):
    """Stop asking for one parent. Claude Code's own prompt cannot offer this, so it lives here."""
    parent = argv[0] if argv else "orchestrator"
    os.makedirs(CTL, exist_ok=True)
    json.dump(dict(parent=parent, ts=align.now_ms()),
              open(os.path.join(CTL, "standing_%s.json" % parent), "w"))
    print("standing approval for %s: further spawns from it will not be held" % parent)


def status(_argv):
    st, c = memory.settings(), align.counters(PROJ)
    model = memory.load()
    if not model:
        print("lines        NONE - run `python3 oversight/ctl.py init` first, or nothing is judged")
    print("lines        %d (%s)" % (len(model), ", ".join(m["id"] for m in model[:8])))
    print("involvement  %s   catch-up threshold %s   surface %s" %
          (st.get("involvement"), st.get("catchup_threshold"), st.get("surface_mode", "ask")))
    tot, why = counters_line(c, st)
    print("counters     %s" % why)
    ps = glob.glob(os.path.join(PENDING, "*.json"))
    print("waiting      %d" % len(ps))
    prec, n = align.precision(os.path.join(CTL, "answered.jsonl"))
    if prec is not None:
        print("precision    %.2f over the last %d answered holds%s" %
              (prec, n, "  (below the floor: holds are being downgraded to checks)"
               if n >= 5 and prec < st.get("precision_floor", 0.70) else ""))
    js = sorted(glob.glob(os.path.join(align.ov(PROJ), "judgements", "*.json")))
    bands = {}
    for p in js:
        try:
            bands[json.load(open(p))["band"]] = bands.get(json.load(open(p))["band"], 0) + 1
        except Exception:
            pass
    print("judgements   %d  %s" % (len(js), bands))


def catchup(_argv):
    st, c = memory.settings(), align.counters(PROJ)
    tot, why = counters_line(c, st)
    mins = max(0, int((align.now_ms() - c.get("last_look_ts", align.now_ms())) / 60000))
    print("oversight catch up?   since your last look (%d min)" % mins)
    print("  %d departures from what you said, not surfaced" % c.get("flags_unanswered", 0))
    print("  %d checks you did not answer" % c.get("checks_unanswered", 0))
    print("  open the graph   http://localhost:4173/?since=last-look")
    print("  %s . nothing is paused" % why)


def caught_up(_argv):
    align.reset_look(PROJ, "caught up")
    print("counters reset; last look is now")


def judgements(argv):
    n = int(argv[0]) if argv else 10
    for p in sorted(glob.glob(os.path.join(align.ov(PROJ), "judgements", "*.json")))[-n:]:
        j = json.load(open(p))
        print("  %-6s %-9s %.2f  %-28s -> %-28s %s" %
              (j.get("band"), j.get("verdict"), j.get("confidence", 0),
               str(j.get("parent_label"))[:28], str(j.get("child"))[:28],
               ",".join(sorted({e.get("line_id") for e in (j.get("evidence") or [])}))))


CMDS = dict(init=init, lines=lines_cmd, status=status, pending=pending, answer=answer,
            watch=watch, catchup=catchup, judgements=judgements)
def allow_action(argv):
    """Let a blocked subagent action through: clears what the action gate remembered about it."""
    import shutil
    d = os.path.join(CTL, "action_seen")
    n = len(glob.glob(os.path.join(d, "*.json")))
    shutil.rmtree(d, ignore_errors=True)
    print("cleared %d remembered actions; the agent can retry" % n)


CMDS["accept-all"] = accept_all
CMDS["allow-action"] = allow_action
CMDS["caught-up"] = caught_up

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in CMDS:
        print(__doc__)
        sys.exit(1)
    CMDS[sys.argv[1]](sys.argv[2:])
