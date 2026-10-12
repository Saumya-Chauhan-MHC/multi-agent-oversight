#!/usr/bin/env python3
"""Terminal control for the v3 tool.

  python3 oversight/v3/ctl3.py model        what the extractor built, and what you have added
  python3 oversight/v3/ctl3.py status       lists, queue, window, precision
  python3 oversight/v3/ctl3.py pending      the block that is due, written out in full
  python3 oversight/v3/ctl3.py answer <label> accept|no ["why"]
  python3 oversight/v3/ctl3.py judgements   every decision judged, shown or not
"""
import json, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
from oversight.v3 import taskmodel as tmod, policy
from oversight import align

PROJ = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()


def model(_):
    tm = tmod.load(PROJ)
    print("requirements")
    for r in tm["requirements"]:
        print("  %-4s %-54s check %-28s %s" % (r["id"], r["text"][:54], r.get("check"), r.get("status")))
    print("preferences")
    for p in tmod.preferences(tm):
        print("  %-8s %-13s %-50s [%s] %s" % (p["id"], tmod.CATEGORIES[p["category"]],
                                              p["rule"][:50], ",".join(p.get("metrics") or []),
                                              p.get("source")))


def status(_):
    tm = tmod.load(PROJ)
    ev = align.load_events(PROJ)
    dep = tmod.dependency_map(ev)
    print("preferences  %d   requirements %d" % (len(tmod.preferences(tm)), len(tm["requirements"])))
    print("graded files %s" % (", ".join(sorted(tmod.graded_files(tm))) or "-"))
    print("registry     %s" % (json.dumps(tmod.registry(ev)) if tmod.registry(ev) else "-"))
    print("depends on   %s" % (json.dumps({k: sorted(v) for k, v in dep["depends_on"].items() if v})
                               if any(dep["depends_on"].values()) else "-"))
    blocks = [b for b in policy._blocks(PROJ) if b["status"] == "waiting" and b["members"]]
    print("queue        %d block(s): %s" % (len(blocks), ", ".join("%s x%d" % (b["label"], len(b["members"]))
                                                                   for b in blocks) or "-"))
    st = policy._read(PROJ, "state.json", {})
    left = max(0, policy.WINDOW_S - int((policy.now() - st.get("last_answer_ts", 0)) / 1000))
    print("window       %s" % ("open" if policy.window_open(PROJ) else "quiet for %ds more" % left))
    js = [e for e in align.load_events(PROJ) if e.get("ov_event") == "v3_judgement"]
    bands = {}
    for j in js:
        bands[j.get("band")] = bands.get(j.get("band"), 0) + 1
    print("judgements   %d %s" % (len(js), bands or ""))


def pending(_):
    b = policy.due(PROJ)
    if not b:
        blocks = [x for x in policy._blocks(PROJ) if x["status"] == "waiting" and x["members"]]
        print("nothing due" + (" (%d waiting for the window)" % len(blocks) if blocks else ""))
        return
    print("BLOCK [%s]  %d recommendation(s)%s" %
          (b["label"], len(b["members"]), "  (jumped the window)" if b.get("preempted") else ""))
    for m in b["members"]:
        print("  - %s -> %s" % (m["agent"], m["action"][:92]))
        print("    %s %.2f  metric %s" % (m.get("verdict"), m.get("confidence") or 0, m.get("metric")))
        for e in (m.get("evidence") or [])[:2]:
            print('      you said (%s): "%s"' % (e.get("pref_id"), str(e.get("said"))[:96]))
            print("      this does:      %s" % str(e.get("proposed"))[:96])
        if m.get("consequence"):
            print("      cost: %s" % m["consequence"][:110])
        if m.get("correction"):
            print("      instead: %s [%s]" % (m["correction"][:90], m.get("cost") or "?"))
    print("\n  answer:  python3 oversight/v3/ctl3.py answer %s accept|no \"why\"" % b["label"])


def answer(argv):
    if len(argv) < 2:
        print("usage: answer <label> accept|no [note]")
        return
    label, decision, note = argv[0], argv[1], (argv[2] if len(argv) > 2 else "")
    members = policy.answer(PROJ, label, decision, note)
    if members is None:
        print("no waiting block called %s" % label)
        return
    print("answered %s: %s (%d recommendation(s))" % (label, decision, len(members)))
    if decision == "no" and note:
        pref = tmod.add_preference(PROJ, note, category=label.split("-")[0].split("+")[0],
                                   source="human", rid=members[0]["rid"] if members else None)
        print("new preference %s: %s" % (pref["id"], pref["rule"]))
        for m in members:
            try:
                align.send_to_agent(PROJ, m["agent"], "[oversight] The user declined this: %s" % note)
            except Exception:
                pass
        print("told: %s" % ", ".join(sorted({m["agent"] for m in members})))
    elif decision == "accept":
        for m in members:
            if m.get("if_accepted"):
                pref = tmod.add_preference(PROJ, m["if_accepted"],
                                           category=label.split("-")[0].split("+")[0], source="human")
                print("new preference %s: %s" % (pref["id"], pref["rule"]))
                break


def judgements(argv):
    n = int(argv[0]) if argv else 12
    js = [e for e in align.load_events(PROJ) if e.get("ov_event") == "v3_judgement"]
    for j in js[-n:]:
        print("  %-7s %-8s %.2f  %-13s %-28s %s" %
              (j.get("band"), j.get("verdict"), j.get("confidence") or 0,
               j.get("metric") or "-", ",".join(j.get("prefs") or []) or "-",
               str(j.get("action"))[:46].replace("\n", " ")))


CMDS = dict(model=model, status=status, pending=pending, answer=answer, judgements=judgements)
if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd not in CMDS:
        print(__doc__)
        sys.exit(1)
    CMDS[cmd](sys.argv[2:])
