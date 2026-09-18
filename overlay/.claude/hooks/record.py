#!/usr/bin/env python3
"""Record-only oversight hook (T0).

Appends every hook event as one JSON line to oversight/events.jsonl and snapshots a file just
before Claude edits it (oversight/snap/, oversight/checkpoints.txt). It never blocks and never
asks. Exit code is always 0, so the agent's behaviour is unchanged by this hook.

Adds these fields to each event:
  ov_event      which hook fired (session_start, prompt, pre_tool, post_tool, subagent_start, ...)
  ov_ts         wall-clock time in ms
  ov_session_no 1 for the first `claude` launch, 2 after the next launch or `claude --resume`
                (the viewer draws one column per number; Claude's own session_id may or may not
                change on resume, so we count launches ourselves)

  ov_bash_writes   (post_tool, Bash) files created/modified by the command, found by diffing a
                   stat manifest of the workspace taken at pre_tool. Agents routinely write files
                   with `cat > f <<EOF`, `python3 - <<EOF`, `go build -o`, `sed -i` etc.; without
                   this the Write/Edit tool names miss all of it and the work DAG comes out empty.
  ov_bash_reads    (pre_tool, Bash) workspace paths that appear literally in the command string.
                   A heuristic (a path in the string is not proof it was read), but it is the only
                   signal available for `cat`/`head`/`grep` reads. Kept separate from Read events.
  ov_subagent_real (subagent_start/stop) False for Claude Code's internal auxiliary agents, which
                   fire SubagentStop with an empty agent_type, no matching SubagentStart and no
                   transcript on disk. Counting those as delegation inflates the subagent count.
"""
import sys, json, os, time, hashlib, shutil, re

event = sys.argv[1] if len(sys.argv) > 1 else "unknown"
try:
    data = json.load(sys.stdin)
except Exception:
    data = {}
root = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
out = os.path.join(root, "oversight")
os.makedirs(os.path.join(out, "snap"), exist_ok=True)

# --- session counter -------------------------------------------------------------------------
counter = os.path.join(out, "session_no.txt")
no = int(open(counter).read().strip() or 0) if os.path.exists(counter) else 0
if event == "session_start" and data.get("source") in ("startup", "resume", "clear"):
    no += 1
    with open(counter, "w") as f:
        f.write(str(no))
    # the time cap starts now for this session (read by cap.py)
    with open(os.path.join(out, f"cap_start_{no}.txt"), "w") as f:
        f.write(str(int(time.time())))
data["ov_event"] = event
data["ov_ts"] = int(time.time() * 1000)
if os.environ.get("OVERSIGHT_RERUN_OF"):
    data["ov_rerun_of"] = os.environ["OVERSIGHT_RERUN_OF"]
data["ov_session_no"] = max(no, 1)

# --- workspace manifest: what Bash actually changed --------------------------------------------
SKIP_DIRS = {".git", "oversight", "node_modules", "__pycache__", ".venv", "venv", "target", ".cache"}
# One manifest per acting agent. With parallel subagents a single shared manifest cross-attributes
# writes: agent A's post_tool diff picks up files agent B wrote inside A's window.
AGENT = (data.get("agent_id") or "main")
MANIFEST = os.path.join(out, f".manifest_{AGENT}.json")


def names_file(cmd, rp, unique_base=None):
    """Does cmd reference rp as a whole token? Plain substring matching is wrong:
    basename 'p.sh' is a substring of 'cmp.sh', so every command mentioning tests/cmp.sh
    was recorded as reading tests/samples/bash/p.sh, inventing dependency edges.

    The bare-basename form normally must not be preceded by '/', or src/core/engine.py
    would match build/core/engine.py. But shells write paths through variables
    (`S=tests/samples/sql && cp /tmp/x $S/dialect.sql`), where the only literal token is
    '/dialect.sql'. So a '/'-preceded basename counts when that basename is unique in the
    workspace - there is then no other file it could mean.
    """
    base = os.path.basename(rp)
    if re.search(r"(?<![\w./\-])" + re.escape(rp) + r"(?![\w\-])", cmd):
        return True
    if len(base) > 3:
        if re.search(r"(?<![\w./\-])" + re.escape(base) + r"(?![\w\-])", cmd):
            return True
        if unique_base and unique_base.get(base) == 1 and \
           re.search(r"/" + re.escape(base) + r"(?![\w\-])", cmd):
            return True   # uniqueness, not the prefix, is what makes this safe
    return False


def manifest():
    """path -> [size, mtime_ns] for every file in the workspace, minus noise directories."""
    m = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and d != ".claude"]
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            try:
                st = os.stat(p)
                m[os.path.relpath(p, root)] = [st.st_size, st.st_mtime_ns]
            except OSError:
                pass
    return m


# Content-addressed snapshot store. Checkpointing only named writes left no before-image for a
# file rewritten by a loop or a script. Here every small text file is hashed at pre_tool and its
# content stored once under its digest; post_tool records the BEFORE digest of each changed file,
# so any change can be diffed without copying the tree each time.
SNAP_MAX = 512 * 1024
STORE = os.path.join(out, "snap", "store")
STATE = os.path.join(out, ".snapstate.json")


def snapshot(mf):
    try:
        state = json.load(open(STATE)) if os.path.exists(STATE) else {}
    except Exception:
        state = {}
    os.makedirs(STORE, exist_ok=True)
    new = {}
    for rp, (size, mtime) in mf.items():
        if size > SNAP_MAX:
            continue
        prev = state.get(rp)
        if prev and prev[1] == size and prev[2] == mtime:
            new[rp] = prev                      # unchanged since last look: reuse digest
            continue
        ap = os.path.join(root, rp)
        try:
            blob = open(ap, "rb").read()
        except OSError:
            continue
        if b"\x00" in blob[:2048]:
            continue                            # binary: not worth storing for diffs
        h = hashlib.sha256(blob).hexdigest()[:16]
        dst = os.path.join(STORE, h)
        if not os.path.exists(dst):
            try:
                with open(dst, "wb") as f:
                    f.write(blob)
            except OSError:
                pass
        new[rp] = [h, size, mtime]
    try:
        with open(STATE, "w") as f:
            json.dump(new, f)
    except Exception:
        pass
    return new


if data.get("tool_name") == "Bash":
    if event == "pre_tool":
        mf = manifest()
        _before = snapshot(mf)
        try:
            # Per-agent before-digests. The shared state file is refreshed by every agent's
            # pre_tool, so by this agent's post_tool it may already hold the AFTER contents.
            with open(MANIFEST, "w") as f:
                json.dump({"mf": mf, "dg": {k: v[0] for k, v in _before.items()}}, f)
        except Exception:
            pass
        # reads: workspace paths that appear literally in the command string
        cmd = (data.get("tool_input") or {}).get("command") or ""
        READERS = r"(?:cat|head|tail|less|more|grep|egrep|rg|sed|awk|wc|diff|cmp|md5|shasum|source|\.)"

        def executed_not_read(rp, c):
            """`./oracle/reference -l go` runs the file; it is not a read. A path invoked as a
            command (start of line, after a pipe/;/&&) counts as execution unless a reader
            command precedes it."""
            e = re.escape(rp); b = re.escape(os.path.basename(rp))
            for pat in (e, b):
                if re.search(r"(?:^|[|;&]|&&)\s*\.?/?\S*" + pat + r"\b", c) and \
                   not re.search(READERS + r"\s+[^|;&]*" + pat, c) and \
                   not re.search(r"<\s*\S*" + pat, c):
                    return True
            return False

        ubase = {}
        for rp in mf:
            b = os.path.basename(rp)
            ubase[b] = ubase.get(b, 0) + 1
        hits = []
        for rp in mf:
            if names_file(cmd, rp, ubase):
                if executed_not_read(rp, cmd):
                    continue
                hits.append(rp)
        data["ov_bash_reads"] = sorted(hits)[:40]
        # input contract: the exact version (content digest) of each file this command reads
        rd = {f: _before[f][0] for f in hits if f in _before}
        if rd:
            data["ov_read_digests"] = rd
        # Checkpoint the files this command names, before it runs. Write/Edit get this for free
        # below; a Bash command that rewrites a file in place (`cat > f`, `sed -i f`) otherwise
        # leaves no before-image, so snap/ and checkpoints.txt had nothing to diff against.
        def write_intent(rp, cmd):
            """Does this command look like it writes rp? Executing or cat-ing a file is not a write."""
            for pat in (r">>?\s*['\"]?(?:\./)?%s", r"\btee\s+(?:-a\s+)?['\"]?(?:\./)?%s",
                        r"\bsed\s+-i[^|;]*%s", r"\b(?:cp|mv|install)\s+[^|;]*%s",
                        r"-o\s+['\"]?(?:\./)?%s", r"\btruncate\b[^|;]*%s"):
                if re.search(pat % re.escape(rp), cmd) or re.search(pat % re.escape(os.path.basename(rp)), cmd):
                    return True
            return False

        cps = []
        for rp in hits[:10]:
            ap = os.path.join(root, rp)
            if not os.path.isfile(ap):
                continue
            if not write_intent(rp, cmd):
                continue
            try:
                cp_file = os.path.join(out, "checkpoints.txt")
                n2 = sum(1 for _ in open(cp_file)) + 1 if os.path.exists(cp_file) else 1
                cid = f"c{n2:03d}"
                shutil.copy(ap, os.path.join(out, "snap", f"{cid}__{os.path.basename(ap)}"))
                h2 = hashlib.sha256(open(ap, "rb").read()).hexdigest()[:12]
                with open(cp_file, "a") as f:
                    f.write(f"{cid} {rp} {h2} agent={AGENT} session={data['ov_session_no']} via=bash\n")
                cps.append(cid)
            except Exception:
                pass
        if cps:
            data["ov_checkpoint_bash"] = cps
    elif event == "post_tool":
        try:
            _m = json.load(open(MANIFEST)) if os.path.exists(MANIFEST) else {}
        except Exception:
            _m = {}
        before = _m.get("mf", _m) if isinstance(_m, dict) else {}
        pre_dg = _m.get("dg", {}) if isinstance(_m, dict) else {}
        after = manifest()
        changed = sorted(p for p, v in after.items() if before.get(p) != v)
        # files removed by the command count as changes too
        changed = sorted(set(changed) | {p for p in before if p not in after})
        bm = {p: pre_dg[p] for p in changed if p in pre_dg}
        if bm:
            data["ov_before"] = bm
        created = [p for p in changed if p not in before]
        unrestorable = [p for p in changed if p in before and p not in pre_dg]
        if created:
            data["ov_created"] = created[:200]
        if unrestorable:
            data["ov_unrestorable"] = unrestorable[:60]   # binary or >512 KB: no before-image
        _after = snapshot(after)                 # refresh the store for the next command
        # A concurrent agent may have written inside this window. Prefer paths this command
        # actually names; only fall back to the raw diff when it names none, and say so.
        cmd = (data.get("tool_input") or {}).get("command") or ""
        ub = {}
        for p2 in after:
            b2 = os.path.basename(p2)
            ub[b2] = ub.get(b2, 0) + 1
        named = [p for p in changed if names_file(cmd, p, ub)]
        if named:
            data["ov_bash_writes"] = named[:60]
            if len(named) != len(changed):
                data["ov_bash_writes_dropped"] = [p for p in changed if p not in named][:60]
        else:
            data["ov_bash_writes"] = changed[:60]
            if changed:
                data["ov_bash_writes_ambiguous"] = True
        # output versions: which digest each written file ended up at
        wr = set(data.get("ov_bash_writes") or []) | set(data.get("ov_bash_writes_dropped") or [])
        av = {f: _after[f][0] for f in wr if f in _after}
        if av:
            data["ov_after"] = av

def _digest_of(p):
    """Content digest of a workspace file, stored once in the content store."""
    try:
        blob = open(p, "rb").read()
    except OSError:
        return None
    if len(blob) > SNAP_MAX or b"\x00" in blob[:2048]:
        return None
    h = hashlib.sha256(blob).hexdigest()[:16]
    os.makedirs(STORE, exist_ok=True)
    if not os.path.exists(os.path.join(STORE, h)):
        with open(os.path.join(STORE, h), "wb") as f:
            f.write(blob)
    return h


_tfp = (data.get("tool_input") or {}).get("file_path")
if _tfp:
    _ap = _tfp if os.path.isabs(_tfp) else os.path.join(root, _tfp)
    _in_ws = _ap.startswith(root + os.sep) and "/oversight/" not in _ap and "/.claude/" not in _ap
    if _in_ws and event == "pre_tool" and data.get("tool_name") == "Read" and os.path.isfile(_ap):
        _d = _digest_of(_ap)
        if _d:
            data["ov_read_digests"] = {os.path.relpath(_ap, root): _d}
    if _in_ws and event == "post_tool" and data.get("tool_name") in ("Edit", "Write", "MultiEdit") and os.path.isfile(_ap):
        _d = _digest_of(_ap)
        if _d:
            data["ov_after"] = {os.path.relpath(_ap, root): _d}

# --- distinguish real subagents from Claude Code's internal auxiliary agents --------------------
if event in ("subagent_start", "subagent_stop"):
    atype = (data.get("agent_type") or "").strip()
    tpath = data.get("agent_transcript_path") or ""
    data["ov_subagent_real"] = bool(atype) and (event == "subagent_start" or os.path.exists(tpath))

# --- checkpoint the file about to change ------------------------------------------------------
if event == "pre_tool" and data.get("tool_name") in ("Edit", "Write", "MultiEdit"):
    fp = (data.get("tool_input") or {}).get("file_path")
    if fp:
        p = fp if os.path.isabs(fp) else os.path.join(root, fp)
        cp_file = os.path.join(out, "checkpoints.txt")
        n = sum(1 for _ in open(cp_file)) + 1 if os.path.exists(cp_file) else 1
        cid = f"c{n:03d}"
        if os.path.exists(p):
            shutil.copy(p, os.path.join(out, "snap", f"{cid}__{os.path.basename(p)}"))
            blob = open(p, "rb").read()
            h = hashlib.sha256(blob).hexdigest()[:12]
            d16 = hashlib.sha256(blob).hexdigest()[:16]
            os.makedirs(STORE, exist_ok=True)
            if not os.path.exists(os.path.join(STORE, d16)):
                with open(os.path.join(STORE, d16), "wb") as bf:
                    bf.write(blob)
            data["ov_before_tool"] = {os.path.relpath(p, root): d16}
        else:
            h = "new"
            data["ov_before_tool"] = {os.path.relpath(p, root): None}   # None = did not exist
        with open(cp_file, "a") as f:
            f.write(f"{cid} {fp} {h} agent={data.get('agent_id', 'main')} session={data['ov_session_no']}\n")
        data["ov_checkpoint"] = cid

with open(os.path.join(out, "events.jsonl"), "a") as f:
    f.write(json.dumps(data) + "\n")
sys.exit(0)
