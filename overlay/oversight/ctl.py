#!/usr/bin/env python3
"""Terminal control for the oversight tool. Run from the task folder:

  python3 oversight/ctl.py status                  run state, gate mode, pending splits
  python3 oversight/ctl.py gate on|off             pause every proposed subagent spawn for review
  python3 oversight/ctl.py recommend on|off        show the pros / cons section on split cards
  python3 oversight/ctl.py watch                   wait for proposed splits and decide them here
  python3 oversight/ctl.py pending                 list splits waiting for a decision
  python3 oversight/ctl.py split <id|all> accept|accept_all|modify|reject|reset [--note T] [--to CP]
  python3 oversight/ctl.py nodes                   node ids, intents, status
  python3 oversight/ctl.py checkpoints             checkpoints you can reset to
  python3 oversight/ctl.py reset <cp> [--note T]   1. reset to a checkpoint (forks a branch)
  python3 oversight/ctl.py edit <node> [--brief T | --brief-file F] [--launch]
                                                   2. edit a node's brief and rerun it (forks)
  python3 oversight/ctl.py tell <node> "<text>"    3. instruction to a running node (no fork)
  python3 oversight/ctl.py undo <backup-id>        reverse a reset or edit
  python3 oversight/ctl.py history                 every recorded intervention

Every mutating command shows a PREVIEW of what it will undo or touch, then waits for /confirm
or /cancel (both recorded). --yes skips the prompt. The viewer's buttons call the same code.
"""
import sys, os, json, time, argparse, tempfile, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import control as C  # noqa: E402

G, Y, R, D, B, X = "\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[1m", "\033[0m"
if not sys.stdout.isatty():
    G = Y = R = D = B = X = ""


def bar(title):
    print(f"{Y}| oversight - PREVIEW  {title}{X}")


def row(k, v):
    print(f"{Y}|{X} {k:<22} {v}")


def confirm(args, kind, target, impact):
    if args.yes:
        return True
    print(f"{Y}|{X} {D}/confirm   /cancel{X}")
    try:
        a = input("> ").strip().lower()
    except EOFError:
        a = ""
    if a in ("/confirm", "confirm", "y", "yes"):
        return True
    C.record_cancel(kind, target, impact, "cancelled at preview")
    print(f"{D}cancelled; recorded as decision = cancel{X}")
    return False


def lst(xs, n=4):
    xs = list(xs)
    return ", ".join(xs[:n]) + (f" +{len(xs) - n} more" if len(xs) > n else "") if xs else "none"


# ---------------------------------------------------------------------------------------------
def cmd_status(a):
    st = C.run_state()
    mode = open(os.path.join(C.OV, "gate_mode")).read().strip() if os.path.exists(os.path.join(C.OV, "gate_mode")) else "off"
    print(f"session {st['session']}  run {'ACTIVE' if st['active'] else 'not running'}"
          f"{'  (PAUSED at a split)' if st['paused'] else ''}  last event {st['last_event_age_s']}s ago")
    print(f"split gate: {B}{mode}{X}   recommendations: {B}{C.flag('recommend_mode')}{X}")
    for p in C.pending():
        print(f"  {R}pending{X} {p['rid']}  {p['impact']['parent_label']} -> {p['description']}")


def cmd_recommend(a):
    C.set_flag("recommend_mode", a.state)
    print(f"recommendations {a.state}: split cards " + ("show" if a.state == "on" else "hide") + " the pros / cons section")


def cmd_gate(a):
    open(os.path.join(C.OV, "gate_mode"), "w").write(a.state)
    print(f"split gate {a.state}: " + ("every proposed subagent spawn will pause for review"
                                      if a.state == "on" else "spawns proceed without review"))


def show_split(p):
    im = p["impact"]
    bar(f"split  {im['parent_label']} -> {p['description']}")
    row("request", p["rid"])
    if im.get("stated_plan"):
        row("parent's stated plan", im["stated_plan"].replace("\n", " ")[:160])
    so_far = im.get("split_so_far") or []
    row("split so far", lst(f"{x['label'].split(' (')[0]} [{x['status']}]" for x in so_far) +
        f"   {D}(children arrive one per message){X}" if so_far else "this is the first child")
    row("files in scope", lst(im["files_in_scope"]))
    row("parent output", f"{im['parent_output_count']} files")
    row("downstream affected", lst(x["label"] for x in im["downstream"]) +
        (f"   {R}threshold crossed{X}" if len(im["downstream"]) >= 2 else ""))
    row("other sessions", lst(x["label"] for x in im["cross_session"]))
    if C.flag("recommend_mode") == "on":
        row("pros", "(not assessed yet)")
        row("cons", "(not assessed yet)")
    row("checkpoint before", im.get("checkpoint_before") or "none")
    print(f"{Y}|{X} {D}/accept   /accept-all (this parent, until it finishes)   /modify <what to change>   /reject [why]   /reset [checkpoint]{X}")
    print(f"{Y}|{X} {D}the agent stays paused until you answer{X}")


def decide_interactive(p):
    show_split(p)
    try:
        a = input("> ").strip()
    except EOFError:
        return
    verb, _, rest = a.lstrip("/").partition(" ")
    verb = {"a": "accept", "m": "modify", "r": "reject", "accept-all": "accept_all", "aa": "accept_all"}.get(verb, verb)
    if verb not in ("accept", "accept_all", "modify", "reject", "reset"):
        print("not a decision; still pending"); return
    rec = C.decide(p["rid"], verb, note=rest if verb != "reset" else "", reset_to=(rest or None) if verb == "reset" else None)
    print(f"{G}recorded{X}: split {p['rid']} decision = {rec['decision']}")


def cmd_watch(a):
    print(f"{D}watching for proposed splits (Ctrl-C to stop). Gate must be on: ctl.py gate on{X}")
    seen = set()
    try:
        while True:
            for p in C.pending():
                if p["rid"] not in seen and os.path.exists(os.path.join(C.PENDING, p["rid"] + ".json")):
                    seen.add(p["rid"])
                    print("\a")
                    decide_interactive(p)
            time.sleep(1)
    except KeyboardInterrupt:
        print()


def cmd_pending(a):
    ps = C.pending()
    if not ps:
        print("no splits waiting"); return
    for p in ps:
        show_split(p); print()


def cmd_split(a):
    ps = C.pending() if a.rid == "all" else [p for p in C.pending() if p["rid"].startswith(a.rid)]
    if not ps:
        print("no matching pending split"); return
    for p in ps:
        rec = C.decide(p["rid"], a.decision, note=a.note or "", reset_to=a.to)
        print(f"{G}recorded{X}: {p['rid']}  {p['description']}  decision = {rec['decision']}")


def cmd_nodes(a):
    nodes, _ = C.build()
    for k, n in nodes.items():
        print(f"  {k[:18]:<20} {n['status']:<9} {('orchestrator' if n['main'] else n['intent'])[:40]:<42} "
              f"wrote {len(n['writes'])}")


def cmd_checkpoints(a):
    for c in C.checkpoints()[-a.n:]:
        t = time.strftime("%H:%M:%S", time.localtime((c["ts"] or 0) / 1000))
        print(f"  {c['id']:<6} {t}  {c['kind']:<9} {(c['file'] or c.get('label') or ''):<46} {c['agent'][:12]}")


def cmd_reset(a):
    pv = C.preview_reset(a.target)
    bar(f"reset -> {a.target}")
    row("to", pv["to"])
    for d in pv["discards"]:
        row("discards", f"{d['node']}: {lst(d['files'], 3)}")
    row("nodes back to pending", lst(pv["nodes_back_to_pending"]))
    row("files restored", f"{pv['files_restored']}   deleted: {pv['files_deleted']}")
    if pv["unrestorable"]:
        row(f"{R}cannot restore{X}", lst(pv["unrestorable"]))
    row("downstream affected", lst(pv["downstream"]) + (f"   {R}threshold crossed{X}" if pv["threshold"] else ""))
    if pv["run"]["active"] and not pv["run"]["paused"]:
        row(f"{R}warning{X}", "a run is active; stop it or reset while it is paused at a split")
    impact = {k: pv[k] for k in ("to", "files_restored", "files_deleted", "downstream", "threshold")}
    if confirm(a, "reset", a.target, impact):
        rec = C.apply_reset(a.target, a.note or "", force=a.force)
        print(f"Forked {rec['branch']} at {a.target}. {rec['applied']}. Backup: {rec['backup']}")
        print(f"{D}oversight: recorded human reset, {rec['checkpoint_before']} -> {rec['checkpoint_after']}, decision = confirm{X}")


def cmd_edit(a):
    nodes, _ = C.build()
    k = C.find_node(nodes, a.node)
    if not k:
        print(f"no such node: {a.node}  (see: ctl.py nodes)"); return
    brief = a.brief or (open(a.brief_file).read() if a.brief_file else None)
    if brief is None:
        with tempfile.NamedTemporaryFile("w+", suffix=".md", delete=False) as t:
            t.write(nodes[k]["prompt"]); tp = t.name
        subprocess.call([os.environ.get("EDITOR", "vi"), tp])
        brief = open(tp).read()
    pv = C.preview_edit(k, brief)
    bar(f"rerun {pv['node_label']} with edited brief")
    row("discards", f"{pv['discards_n']} files: {lst(pv['discards'], 3)}")
    row("downstream affected", lst(pv["downstream"]) + (f"   {R}threshold crossed{X}" if pv["threshold"] else ""))
    row("untouched", lst(pv["untouched_siblings"]))
    row("delivered via", "the running orchestrator (it re-spawns the node)" if pv["route"] == "orchestrator"
        else "a standalone rerun (script written; --launch to start it)")
    for w in pv["warnings"]:
        row(f"{R}warning{X}", w)
    impact = {x: pv[x] for x in ("discards_n", "downstream", "threshold", "route")}
    if confirm(a, "edit_rerun", k, impact):
        rec = C.apply_edit(k, brief, a.note or "", launch=a.launch, force=a.force)
        print(f"{pv['node_label']}: output reverted ({rec['applied']}), rerun via {rec['route']}."
              + (f" Script: {rec.get('rerun_script')}" if rec.get("rerun_script") else ""))


def cmd_tell(a):
    pv = C.preview_tell(a.node, a.text)
    bar(f"instruction -> {pv['node_label']} ({pv['status']})")
    row("files in scope", lst(pv["files_in_scope"]))
    row("downstream affected", lst(pv["downstream"]))
    for w in pv["warnings"]:
        row(f"{R}warning{X}", w)
    if not pv["deliverable"]:
        return
    if confirm(a, "instruction", pv["node"], {"files_in_scope": pv["files_in_scope"]}):
        C.apply_tell(pv["node"], a.text, a.note or "")
        print(f"Queued for {pv['node_label']}; it will see it on its next tool call.")


def cmd_undo(a):
    n = C.undo(a.backup)
    print(f"restored {n} files from backup {a.backup}")


def cmd_history(a):
    for r in C.interventions():
        t = time.strftime("%H:%M:%S", time.localtime(r["ov_ts"] / 1000))
        print(f"  {t}  {r['kind']:<11} {r['decision']:<27} proposed by {r['initiated_by']:<5} decided by {r.get('decided_by','human'):<5} "
              f"{str(r.get('child') or r.get('node_label') or r['target'])[:36]:<38} "
              f"{r['checkpoint_before']} -> {r['checkpoint_after']}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("status").set_defaults(f=cmd_status)
    p = sp.add_parser("gate"); p.add_argument("state", choices=["on", "off"]); p.set_defaults(f=cmd_gate)
    p = sp.add_parser("recommend"); p.add_argument("state", choices=["on", "off"]); p.set_defaults(f=cmd_recommend)
    sp.add_parser("watch").set_defaults(f=cmd_watch)
    sp.add_parser("pending").set_defaults(f=cmd_pending)
    p = sp.add_parser("split"); p.add_argument("rid"); p.add_argument("decision", choices=["accept", "accept_all", "modify", "reject", "reset"])
    p.add_argument("--note"); p.add_argument("--to"); p.set_defaults(f=cmd_split)
    sp.add_parser("nodes").set_defaults(f=cmd_nodes)
    p = sp.add_parser("checkpoints"); p.add_argument("-n", type=int, default=25); p.set_defaults(f=cmd_checkpoints)
    for name, fn in (("reset", cmd_reset),):
        p = sp.add_parser(name); p.add_argument("target"); p.add_argument("--note"); p.add_argument("--yes", action="store_true")
        p.add_argument("--force", action="store_true"); p.set_defaults(f=fn)
    p = sp.add_parser("edit"); p.add_argument("node"); p.add_argument("--brief"); p.add_argument("--brief-file")
    p.add_argument("--launch", action="store_true"); p.add_argument("--note"); p.add_argument("--yes", action="store_true")
    p.add_argument("--force", action="store_true"); p.set_defaults(f=cmd_edit)
    p = sp.add_parser("tell"); p.add_argument("node"); p.add_argument("text"); p.add_argument("--note")
    p.add_argument("--yes", action="store_true"); p.set_defaults(f=cmd_tell)
    p = sp.add_parser("undo"); p.add_argument("backup"); p.set_defaults(f=cmd_undo)
    sp.add_parser("history").set_defaults(f=cmd_history)
    a = ap.parse_args()
    try:
        a.f(a)
    except (ValueError, RuntimeError) as e:
        print(f"{R}{e}{X}"); sys.exit(1)


if __name__ == "__main__":
    main()
