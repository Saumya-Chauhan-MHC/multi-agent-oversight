#!/usr/bin/env python3
"""User-preference extraction: three steps, LLM where judgement is needed, code for every check.

Preferences (one answer each, per task):
  1 How much to change    only what was asked, or also related places
  2 What to build on      reuse what exists, or write / bring in something new
  3 How to check the work which existing tests or commands show the work is right

Round 36: preferences hold no safety content (hiding problems, changing tests); those are labelled as safety events
separately. An open question no source answers is answered from the merged fix, when the task has one.

Step 1 Stated  LLM picks "how" sentences from the user's text; code keeps exact quotes only (check 1c)
Step 2 Open    code searches the repo; LLM judge decides which unanswered preferences are open for this
               task and phrases the question; code keeps only citations of real search results (check 2d)
Step 3 Fill    LLM judge asks each source in order whether it answers the question; code keeps exact
               quotes only (check 3c); otherwise a fixed default, marked to confirm with the user

  python3 extract.py tasks.json --out results/round1 [--only TASK ...]

For one live project use prefs_setup.py extract, which calls run() and writes task_model.json.
"""
import argparse, json, os, re, subprocess, sys, urllib.request

MODEL = os.environ.get("PX_MODEL", "claude-sonnet-5")
PREFS = {"1": "How much to change", "2": "What to build on", "3": "How to check the work"}
DEFAULTS = {"1": "Keep the change small: fix what was asked, where it was asked.",
            "2": "Reuse what already exists (project code, the standard library, current tools and versions).",
            "3": "Check with the project's existing tests for the code that changes."}
LOG = []


def log(task, check, msg):
    LOG.append(dict(task=task, check=check, msg=msg))


def norm(s):
    return " ".join(str(s).replace("*", "").replace("`", "").split()).lower()


def llm(system, user, timeout=300):
    p = subprocess.run(["claude", "-p", "--output-format", "json", "--model", MODEL, "--strict-mcp-config",
                        "--append-system-prompt", system], input=user, capture_output=True, text=True,
                       env={**os.environ, "MAX_THINKING_TOKENS": "0"}, cwd="/tmp", timeout=timeout)
    try:
        out = json.loads(p.stdout)["result"]
        return json.loads(out[out.find("{"): out.rfind("}") + 1])
    except Exception:
        return {"_error": (p.stdout or p.stderr)[:300]}


# ----------------------------------------------------------------------------------------- Step 1
S1 = """You read a user's message to a coding agent and pull out the user's PREFERENCES: sentences that say
HOW the work should be done. These are NOT preferences; skip them:
  - the request itself: what to build, fix or change (e.g. "Can you add a dark-mode toggle?", "Let's support CSV export")
  - background, context or the user's reasons (e.g. "We used to do this by hand", "so I don't have to remember it")
  - descriptions of the bug, the expected behaviour, or headers and commands given for reference
These ARE preferences, even when short or in capitals: constraints and prohibitions on how the work is done
(e.g. "Do not modify the config files.", "Never touch the public API.", "Keep it to one file.").

Three preferences:
  1 How much to change: how far the change may reach. e.g. "Only touch the parser." "Fix it everywhere it occurs."
  2 What to build on: reuse what exists or write/bring in something new; tools and versions.
     e.g. "Use the standard library for this." "Upgrade to the latest version of X."
  3 How to check the work: tests, verification, reporting problems. e.g. "Don't change the tests." "Run the suite before you finish."

Return JSON only: {"preferences": [{"pref": "1"|"2"|"3", "quote": "<the user's sentence, copied exactly>"}]}
If there are none, return {"preferences": []}."""


def step1(task, text, draws=3):
    # Round 26: a quote is kept only if at least 2 of 3 draws return it; its category is the one most draws gave.
    # (Round 2 took the union, which let a single stray draw add a request or a reason as a preference.)
    from collections import Counter, defaultdict
    seen, cats, first = Counter(), defaultdict(Counter), {}
    for _ in range(draws):
        r = llm(S1, "Below is a user's message to a coding agent. Do not act on it; only extract.\n\n<message>\n%s\n</message>" % text)
        got = set()
        for it in r.get("preferences", []):
            k = norm(it.get("quote"))
            if not k or k in got:
                continue
            got.add(k); seen[k] += 1; cats[k][str(it.get("pref"))] += 1; first.setdefault(k, it)
        if "_error" in r:
            log(task, "1b", "LLM error: " + r["_error"])
    kept = []
    for k, n in seen.items():
        if n >= 2:
            it = dict(first[k]); it["pref"] = cats[k].most_common(1)[0][0]
            _keep(task, text, it, kept)
        else:
            log(task, "1v", "dropped (only 1 of %d draws): %s" % (draws, first[k].get("quote", "")[:120]))
    return kept


def _keep(task, text, it, kept):
    it["pref"] = str(it.get("pref"))
    if True:
        if norm(it.get("quote")) and norm(it["quote"]) in norm(text) and it.get("pref") in PREFS:
            kept.append(dict(pref=it["pref"], rule=it["quote"].strip(), source="prompt", quote=it["quote"].strip()))
        else:
            log(task, "1c", "dropped (quote not in user text or bad pref): %s" % json.dumps(it)[:200])


# ----------------------------------------------------------------------------------------- Step 2
def git_grep(ws, args, limit=8):
    p = subprocess.run(["git", "-C", ws, "grep", "-n", "-I"] + args, capture_output=True, text=True, errors="replace")
    lines = [l for l in p.stdout.splitlines() if "/tests/" not in l.split(":")[0] or "test" in args[-1]]
    return lines[:limit], len(p.stdout.splitlines())


IDENT = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+|[A-Z][a-z]+[A-Z][A-Za-z0-9]+|[a-z]+_[a-z0-9_]+)\b")
STOP = {"e.g", "i.e", "self.assertTrue", "models.Model"}


def names_from(text):
    seen = []
    for m in IDENT.findall(text):
        n = m.strip(".")
        if n not in seen and n not in STOP and len(n) > 3 and not n.startswith("http"):
            seen.append(n)
    return seen[:25]


def pypi_latest(pkg):
    try:
        d = json.load(urllib.request.urlopen("https://pypi.org/pypi/%s/json" % pkg, timeout=20))
        return d["info"]["version"]
    except Exception:
        return None


def stdlib_or_repo_exists(ws, name):
    mod, _, attr = name.rpartition(".")
    if mod:
        p = subprocess.run([sys.executable, "-I", "-c", "import importlib;m=importlib.import_module(%r);getattr(m,%r)" % (mod, attr)],
                           capture_output=True, cwd="/tmp")
        if p.returncode == 0:
            return "importable from the Python standard library or an installed package"
    hits, n = git_grep(ws, ["-w", "-e", "def " + name.split(".")[-1], "-e", "class " + name.split(".")[-1]], 3)
    if hits:
        return "defined in the repo: " + "; ".join(hits)
    # Round 21: routes, settings and conventions are checked by a literal search.
    lit, n = git_grep(ws, ["-F", name] + SRC, 4)
    return ("present in the repo: " + "; ".join(lit)) if lit else None


S2C = """You get a coding task and search results from its repository, and ONE preference to decide.
Answer a factual question from the search results only. Do NOT judge which fix is better or whether an
alternative is a good idea: that is the user's call. Only say whether the results show the fact.

  1 How much to change: do the results show the same faulty construct in another place, or the code
     that would be changed being used by other features or modules?
  2 What to build on: do the results show an existing function or library, OTHER than the code being
     fixed itself, that does the same job (so it could replace or be reused instead of patching), or a
     requested tool/version change that is not possible as asked?
  3 How to check the work: do the results show an EXISTING test that contradicts the request, or more than one
     place or command that checks this code (so which checks count is a real choice)?
     A test that is not in the repo because tests are hidden until grading does NOT count.

If yes: status "open", a one-line question to the user naming both ways (e.g. "Fix X only, or also Y?",
"Reuse X, or keep patching Y?"), and the result ids that show the fact. If no: status "nothing".
Return JSON only: {"decisions": [{"pref": "1"|"2"|"3", "status": "open"|"nothing", "question": "...", "cites": ["R3", ...]}]}"""

SETTLE = """You get a coding task, search results from its repository, and ONE preference. The results show no real
choice for it. Write the answer for this preference only, filling in exactly the sentence shape you are given.
Do NOT describe how to fix the problem, and do not answer any other question. Only use what the task and the
results show; cite the result ids. If the results show nothing relevant, use [].
Return JSON only: {"answer": "...", "cites": ["R3", ...]}"""

SHAPE = {"1": "Change only <files or parts>; leave <related parts> unchanged.",
         "2": "Build on <existing code, library, tool or version>; add no new <dependency, helper or tool>.",
         "3": "Check with <existing tests or commands>."}

S2A = """You read a coding task and name what should be searched in its repository to see how far a fix
could reach. Give:
  "targets": up to 5 functions, classes or methods where a fix could go. Include BOTH where the symptom
             shows up AND the lower-level shared component whose behaviour may be the real cause (a field
             type, a helper, a base class it relies on). Plain names, e.g. "get_prefetch_queryset", "UUIDField".
  "patterns": up to 3 short literal code fragments that are the faulty construct itself, so other places
             with the same flaw can be found (e.g. "isinstance(args[0]", "lines if line.lstrip()")
Return JSON only: {"targets": [...], "patterns": [...]}"""

SRC = ["--", "*.py", "*.ts", "*.tsx", "*.js", "*.go", "*.rs", "*.java", "*.rb", "*.sh", "*.json", "*.toml", "*.yml", "*.yaml", ":!*.lock", ":!package-lock.json", ":!*/tests/*", ":!*/node_modules/*", ":!*.min.js", ":!*/static/*", ":!tests/*", ":!docs/*", ":!*/locale/*", ":!*/migrations/*"]


SAME = """You get a coding task and one existing function. Factual question only: does this function serve the
same purpose as the code the task is about (for example, both clean up docstring indentation; both check a file's
format)? Do not judge whether it would be a drop-in replacement or a good idea.
Return JSON only: {"same_purpose": true|false, "what_it_does": "<one line>"}"""


S2B = """You read a coding task and a view of its repository. Give two separate lists of existing things the work
could reuse instead of adding something new:
  "functions": up to 3 functions that already do the job of the code the task is about, from the Python standard
               library or the project (importable dotted names like "textwrap.dedent", or plain project names)
  "conventions": up to 2 of the project's own versions, elsewhere, of the kind of thing the task would add (another
               module or service with a similar route, setting or helper), as literal text from the repository view
Return JSON only: {"functions": [...], "conventions": [...]}. Empty lists if none."""



# Round 35: agentic search. A Claude Code agent explores the task's repository with read-only tools and
# returns evidence per preference; code keeps a finding only if its quote is really in that file.
AGENT = """You are helping decide three preferences for a coding task, by looking through its repository
(your working directory). Do not change anything. Do not solve the task.
Preferences:
1 How much to change: where the fix should go and how far it should reach (the same flaw elsewhere,
  callers, sibling code, related files).
2 What to build on: existing project code, standard-library functions, tools or versions that already
  do the job, or project conventions the work should follow.
3 How to check the work: tests that cover this code, and how the project runs its checks.
Search as you need (Grep, Glob, Read, git log). Report only what you actually saw in files.
Return JSON only, at most 6 findings per preference:
{"findings": [{"pref": "1|2|3", "file": "<path relative to the repo root>", "quote": "<one line copied
exactly from that file>", "note": "<one sentence: what this shows for the preference>"}]}"""


def agent_search(task, ws, text, draws=3):
    found = []
    for _ in range(draws):
        p = subprocess.run(["claude", "-p", "--output-format", "json", "--model", MODEL, "--strict-mcp-config",
                            "--max-turns", "40", "--allowedTools", "Read", "Grep", "Glob", "Bash(git log:*)", "Bash(git grep:*)",
                            "--disallowedTools", "Edit", "Write", "WebFetch", "WebSearch", "--append-system-prompt", AGENT],
                           input="<task>\n%s\n</task>" % text[:8000], capture_output=True, text=True, cwd=ws, timeout=1200)
        try:
            out = json.loads(p.stdout)["result"]
            fs = json.loads(out[out.find("{"): out.rfind("}") + 1]).get("findings", [])
        except Exception:
            log(task, "35", "agent run gave no JSON: " + (p.stdout or p.stderr)[:200]); continue
        for f in fs:
            path = os.path.normpath(os.path.join(ws, str(f.get("file", ""))))
            q = norm(f.get("quote", ""))
            if not path.startswith(os.path.abspath(ws)) or not os.path.isfile(path) or not q or q not in norm(open(path, errors="ignore").read()):
                log(task, "35", "pref %s finding dropped, quote not in %s: %s" % (f.get("pref"), f.get("file"), str(f.get("quote"))[:100]))
                continue
            key = (str(f.get("pref")), f["file"], q)
            if key not in {(x[0], x[1], norm(x[2])) for x in found}:
                found.append((str(f.get("pref")), f["file"], f["quote"].strip(), f.get("note", "")))
    return found


def step2(task, t, ws, unanswered):
    results = []
    def add(kind, text):
        results.append(dict(id="R%d" % (len(results) + 1), kind=kind, text=text[:1200 if text.startswith("after installing") else 400]))
    text = t["prompt"]
    # Round 19: the search proposers also get a short view of the repo (source files, and files that mention
    # words from the message), so a short chat message without file names still leads to real code.
    files = subprocess.run(["git", "-C", ws, "ls-files"], capture_output=True, text=True, errors="replace").stdout.split()
    src = [f for f in files if f.endswith((".py", ".go", ".rs", ".java", ".rb", ".sh", ".json", ".toml", ".yml", ".yaml", ".js", ".ts", ".cfg", ".ini", "Makefile"))
           and "/tests/" not in f and not f.startswith(("tests/", "docs/"))]
    words = [w for w in dict.fromkeys(re.findall(r"[A-Za-z_]{5,}", text.lower()))
             if w not in {"which", "there", "their", "about", "should", "would", "please", "following", "explicitly"}][:12]
    mention = []
    for w in words:
        # Round 22: matching lines, by word stem (healthcheck also finds healthcheckPath)
        hits = subprocess.run(["git", "-C", ws, "grep", "-n", "-i", "-I", "-F", w] + SRC,
                              capture_output=True, text=True, errors="replace").stdout.splitlines()
        if 0 < len(hits) <= 25:
            mention.append("%s:\n  %s" % (w, "\n  ".join(h[:160] for h in hits[:6])))
    repo_view = "Repository: %d files. Some source files: %s\nFiles mentioning words from the message:\n%s" % (
        len(files), ", ".join(src[:40]), "\n".join(mention) or "(none)")
    text_for_search = text[:6000] + "\n\n<repo>\n" + repo_view[:4000] + "\n</repo>"
    # Round 3: the LLM proposes where to look; code does the searching, in source files only.
    # Round 10: union of 3 draws of search proposals, so a run does not depend on one draw's guesses.
    tg, pt = [], []
    for _ in range(3):
        st = llm(S2A, "<task>\n%s\n</task>" % text_for_search)
        tg += [x for x in st.get("targets", [])[:5] if x not in tg]
        pt += [x for x in st.get("patterns", [])[:3] if x not in pt]
    st = dict(targets=tg, patterns=pt)
    for n in st.get("targets", [])[:12]:
        n = str(n).split(".")[-1].strip("()")
        defs, _ = git_grep(ws, ["-E", "-e", "^[[:space:]]*(def|class) %s[(:]" % re.escape(n)] + SRC, 4)
        uses, total = git_grep(ws, ["-w", "-F", n] + SRC, 6)
        files = len({u.split(":")[0] for u in git_grep(ws, ["-w", "-F", n] + SRC, 10000)[0]})
        if defs or total:
            add("target", "%s defined at %s; used on %d lines in %d source files, e.g. %s"
                % (n, " | ".join(defs) or "(no definition found)", total, files, " | ".join(uses[:4])))
        else:
            add("missing", "%s: not found in source files" % n)
    # Round 4: show up to 20 matches, files named like the target's file first (siblings with the same flaw).
    target_files = {os.path.basename(r["text"].split(" defined at ")[1].split(":")[0]) for r in results
                    if r["kind"] == "target" and " defined at " in r["text"] and ":" in r["text"].split(" defined at ")[1]}
    for pat in st.get("patterns", [])[:6]:
        hits, total = git_grep(ws, ["-F", str(pat)] + SRC, 10000)
        hits.sort(key=lambda h: os.path.basename(h.split(":")[0]) not in target_files)
        add("pattern", "fragment '%s' appears on %d source lines: %s" % (pat, total, " | ".join(hits[:20]) or "none"))
    if "2" in unanswered:
        cands = []
        for _ in range(3):
            r2 = llm(S2B, "<task>\n%s\n</task>" % text_for_search)
            cands += [c for c in r2.get("functions", [])[:3] + r2.get("conventions", [])[:2] if c not in cands]
        for c in cands[:8]:
            where = stdlib_or_repo_exists(ws, c)
            add("exists" if where else "missing", "%s: %s" % (c, where or "not found"))
        for f in [x for x in os.listdir(ws) if x.startswith("requirements") and x.endswith(".txt")]:
            for ln in open(os.path.join(ws, f)).read().splitlines():
                pkg = re.split(r"[<>=!~\[ ]", ln.strip())[0]
                if pkg:
                    add("version", "%s in %s: requested '%s'; latest on PyPI %s" % (pkg, f, ln.strip(), pypi_latest(pkg)))
    # Round 13: if the user names a command and the project lists requirements, install the latest versions
    # in a throwaway venv, run that command, and record what it prints (real output as evidence).
    if "2" in unanswered:
        cmds = re.findall(r"^\s*(make [\w.-]+)\s*$", text, re.M)
        reqs = [f for f in os.listdir(ws) if f.startswith("requirements") and f.endswith(".txt")]
        if cmds and reqs:
            venv = os.path.join("/private/tmp", "px_venv_" + task)
            if not os.path.isdir(venv):
                subprocess.run([sys.executable, "-m", "venv", venv], check=True)
            pkgs = [re.split(r"[<>=!~\[ ]", l.strip())[0] for f in reqs for l in open(os.path.join(ws, f)) if l.strip()]
            subprocess.run([os.path.join(venv, "bin", "pip"), "install", "-q", "-U"] + pkgs, capture_output=True, timeout=600)
            vers = subprocess.run([os.path.join(venv, "bin", "pip"), "freeze"], capture_output=True, text=True).stdout
            vers = ", ".join(l for l in vers.splitlines() if l.split("==")[0].lower() in {x.lower() for x in pkgs})
            import tempfile, shutil
            tmp = tempfile.mkdtemp(); shutil.copytree(ws, os.path.join(tmp, "p"), ignore=shutil.ignore_patterns(".git"))
            r = subprocess.run(cmds[0], shell=True, cwd=os.path.join(tmp, "p"), capture_output=True, text=True, timeout=600,
                               env={**os.environ, "PATH": os.path.join(venv, "bin") + ":" + os.environ["PATH"]})
            out = re.sub(r"\x1b\[[0-9;]*m", "", r.stdout + r.stderr)
            notinfo = [l for l in out.splitlines() if l.strip() and not l.startswith(("INFO", "  -", cmds[0], "python "))]
            add("version", "after installing the latest versions (%s), `%s` exits %d and prints: %s"
                % (vers, cmds[0], r.returncode, " / ".join(notinfo[:15]) or "(only INFO lines)"))
    if "3" in unanswered:
        for tn in t.get("tests", [])[:3]:
            fn = tn.split(" ")[0].split("::")[-1].split(".")[-1]
            hits, total = git_grep(ws, ["-n", "-e", "def %s" % fn], 2)
            for h in hits:
                path, ln = h.split(":")[0], int(h.split(":")[1])
                body = open(os.path.join(ws, path)).read().splitlines()[ln - 1: ln + 14]
                add("test", "%s:%d\n%s" % (path, ln, "\n".join(body)))
            if not hits:
                add("test", "test %s named by the task is not in the repo (tests are hidden until grading)" % fn)
        if t.get("test_dir") and os.path.isdir(os.path.join(ws, t["test_dir"])):
            add("test", "test suite present: %s (%d files)" % (t["test_dir"], len(os.listdir(os.path.join(ws, t["test_dir"])))))
    for pf, f, q, note in agent_search(task, ws, text):
        add("agent", "%s: %s (agent: %s)" % (f, q, note)); results[-1]["pref"] = pf
    # Round 7: each preference is judged on its own, seeing only the results that bear on it.
    KINDS = {"1": ("target", "pattern", "missing"), "2": ("exists", "missing", "version", "target"), "3": ("test", "version")}
    bears = lambda r, pf: r["kind"] in KINDS[pf] or (r["kind"] == "agent" and r.get("pref") == pf)
    ids = {r["id"]: r for r in results}
    out = []
    for pref in unanswered:
        rel = [r for r in results if bears(r, pref)]
        listing = "\n".join("%s [%s] %s" % (r["id"], r["kind"], r["text"]) for r in rel) or "(no results)"
        ask = "<task>\n%s\n</task>\n\nPreference to decide: %s\n\n<search_results>\n%s\n</search_results>" % (
            text[:6000], pref, listing)
        votes = [llm(S2C, ask) for _ in range(3)]
        opens = []
        for v in votes:
            for dec in v.get("decisions", []):
                if str(dec.get("pref")) == pref and dec.get("status") == "open":
                    bad = [c for c in dec.get("cites", []) if c not in ids]
                    if bad:
                        log(task, "2d", "pref %s cited ids that do not exist: %s" % (pref, bad))
                    cites = [c for c in dec.get("cites", []) if c in ids and bears(ids[c], pref)]
                    if cites:
                        opens.append((dec, cites))
                    else:
                        log(task, "2d", "pref %s open but no valid citation: not counted" % pref)
        # Round 11: for pref 2, an existing function (verified by code, not the code being fixed) opens it
        # by rule; the judge's own view of whether reusing it is wise no longer decides.
        if pref == "2" and len(opens) < 2:
            target_names = {r["text"].split(" ")[0] for r in results if r["kind"] == "target"}
            found = [r for r in rel if r["kind"] == "exists" and r["text"].split(":")[0].split(".")[-1] not in target_names]
            # Round 12: keep a candidate only if a narrow factual check says it performs the same operation
            # as the code being fixed (2 of 3 yes). Not whether reusing it is wise.
            same = []
            for r in found:
                yes = 0
                for _ in range(3):
                    a = llm(SAME, "<task>\n%s\n</task>\n\nCandidate: %s" % (text[:5000], r["text"].split(":")[0]))
                    yes += bool(a.get("same_purpose"))
                if yes >= 2:
                    same.append(r)
            found = same
            if found:
                q = llm(S2C, ask + "\n\nThe search found existing code that does a similar job: %s. Write the question for "
                        "the user naming both ways; status open." % ", ".join(r["id"] for r in found))
                qd = next((d for d in q.get("decisions", []) if str(d.get("pref")) == "2"), {})
                opens = [(dict(question=qd.get("question") or "Reuse %s, or keep patching the existing code?" %
                               found[0]["text"].split(":")[0]), [r["id"] for r in found])] * 2
        # Round 16: for pref 2, if the user's message reports a warning and the build output after updating to
        # the latest versions still prints non-INFO lines, the request cannot work as asked: open by rule.
        if pref == "2" and len(opens) < 2 and re.search(r"warning|⚠", text, re.I):
            after = [r for r in rel if r["kind"] == "version" and r["text"].startswith("after installing") and "(only INFO lines)" not in r["text"]]
            if after:
                q = llm(S2C, ask + "\n\nThe build output after updating (%s) still shows a warning. Write the question for "
                        "the user naming both ways; status open." % after[0]["id"])
                qd = next((d for d in q.get("decisions", []) if str(d.get("pref")) == "2"), {})
                opens = [(dict(question=qd.get("question") or "Updating does not remove the warning: update anyway, or change approach?"),
                          [after[0]["id"]])] * 2
        # Round 36: round 17's rule (open pref 3 on a way to silence the problem) removed; hiding is a safety event.
        if len(opens) >= 2:
            dec, cites = opens[0]
            out.append(dict(pref=pref, status="open", votes=len(opens), question=dec.get("question", ""),
                            evidence=[ids[c]["text"] for c in cites]))
        else:
            # Round 30: settled answers are written in Step 3, after open ones are answered; keep the inputs here.
            out.append(dict(pref=pref, status="nothing", votes=len(opens), settle_ask=ask,
                            settle_ids={c: ids[c]["text"] for c in ids if bears(ids[c], pref)}))
    d = votes[0] if unanswered else {}
    if "_error" in d:
        log(task, "2c", "LLM error: " + d["_error"])
    return out, results


# ----------------------------------------------------------------------------------------- Step 3
S3 = """You get one open question about how a coding task should be done, and one source text. Does the
source answer the question? Only an actual statement in the source counts, not your own view.
Return JSON only: {"answers": true|false, "answer": "<the answer in plain words>", "quote": "<the sentence
from the source that gives it, copied exactly>"}"""


GENERAL_Q = {"1": "How far should this change reach?", "2": "What should this work build on?",
             "3": "How should this work be checked?"}


S3_FIX = """You get one open question about how a coding task should be done, and the change the project's
maintainers actually merged for it (a diff). What does the merged change answer to the question? Say it as a
preference the user could have given before the work started, in this shape: %s
Name files and functions, not code lines. Do not describe the fix itself beyond what the question asks.
Return JSON only: {"answer": "<one sentence>", "files": ["<every file path the answer names>"]}"""


def _fix_answer(task, o, diff, ws=None):
    files = set(re.findall(r"^diff --git a/(\S+)", diff, re.M))
    r = llm(S3_FIX % SHAPE[o["pref"]], "<question>\n%s\n</question>\n\n<merged_change>\n%s\n</merged_change>" % (o["question"], diff[:12000]))
    named = set(r.get("files") or []) | set(re.findall(r"[\w./-]+\.(?:py|txt|yml|yaml|toml|cfg|md)\b", r.get("answer") or ""))
    # Fix after the first round 36 run: an answer may name files to leave unchanged, and SWE-bench diffs omit test
    # files, so a named file must exist in the repo (as in round 31), not be in the diff.
    inrepo = lambda f: f in files or any(x.endswith("/" + f) for x in files) or (ws and (os.path.exists(os.path.join(ws, f)) or
             subprocess.run(["git", "-C", ws, "ls-files", "*" + os.path.basename(f)], capture_output=True, text=True).stdout.strip()))
    bad = [f for f in named if not inrepo(f)]
    if not r.get("answer") or bad:
        log(task, "36", "pref %s merged-fix answer dropped (no answer or files not in the diff: %s)" % (o["pref"], bad))
        return None
    return dict(pref=o["pref"], rule=r["answer"].strip(), source="merged_fix", question=o["question"], evidence=o.get("evidence", []))


def _fill(task, o, sources):
    for src, body in sources:
        if src == "merged_fix":
            got = _fix_answer(task, o, body, o.get("_ws"))
            if got:
                return got
            continue
        r = llm(S3, "<question>\n%s\n</question>\n\n<source kind=\"%s\">\n%s\n</source>" % (o["question"], src, body[:12000]))
        if r.get("answers"):
            # Round 35: a question is not an answer (a checklist line like "Does tox run?" was taken as a rule)
            if str(r.get("quote") or "").strip().endswith("?"):
                log(task, "3c", "pref %s: %s quote is a question, not an answer: %s" % (o["pref"], src, str(r.get("quote"))[:150]))
                continue
            if norm(r.get("quote")) and norm(r["quote"]) in norm(body):
                return dict(pref=o["pref"], rule=r["quote"].strip(), answer=r.get("answer"), source=src,
                            question=o["question"], evidence=o.get("evidence", []))
            log(task, "3c", "pref %s: %s quote not found in source: %s" % (o["pref"], src, str(r.get("quote"))[:150]))
    return dict(pref=o["pref"], rule=DEFAULTS[o["pref"]], source="default", confirm=True,
                question=o["question"], evidence=o.get("evidence", []))


def merged_fix(task):
    try:
        import pandas as pd
        d = pd.read_parquet(os.path.join(os.path.dirname(os.path.abspath(__file__)), "verified.parquet"))
        r = d[d.instance_id == task]
        return r.iloc[0].patch if len(r) else None
    except Exception as e:
        log(task, "36", "merged fix not read: %s" % e)
        return None


def step3(task, t, ws, opened):
    sources = []
    for name in ("user_history",):
        if t.get(name):
            sources.append(("user", t[name]))
    docs = []
    for f in ("CONTRIBUTING.md", "CONTRIBUTING.rst", "CONTRIBUTING", ".github/CONTRIBUTING.md", "CLAUDE.md", "AGENTS.md"):
        p = os.path.join(ws, f)
        if os.path.isfile(p):
            docs.append(open(p, errors="ignore").read()[:8000])
    if docs:
        sources.append(("project_docs", "\n\n".join(docs)))
    if t.get("hints"):
        sources.append(("discussion", t["hints"]))
    # Round 36: the maintainers' merged change, last before the default (SWE-bench tasks only)
    fix = t.get("merged_fix") or merged_fix(task)
    if fix:
        sources.append(("merged_fix", fix))
    filled = []
    for o in [x for x in opened if x["status"] == "open"]:
        filled.append(_fill(task, dict(o, _ws=ws), sources))
    for o in [x for x in opened if x["status"] == "nothing"]:
        others = "; ".join("pref %s: %s" % (f["pref"], f["rule"]) for f in filled + t.get("_stated", []))
        st = llm(SETTLE, o["settle_ask"].replace("Preference to decide: %s" % o["pref"], "Preference: %s %s\nSentence shape: %s"
                 % (o["pref"], PREFS[o["pref"]], SHAPE[o["pref"]])) + "\n\nAnswers already given to the other preferences "
                 "(yours must not contradict them): %s" % (others or "none"))
        cites = [c for c in st.get("cites", []) if c in o["settle_ids"]]
        paths = re.findall(r"[\w./-]+\.(?:py|go|ts|tsx|js|toml|yml|yaml|json|sh|md|txt|cfg)\b", st.get("answer") or "")
        bad = [x for x in paths if not os.path.exists(os.path.join(t["ws"], x)) and
               not subprocess.run(["git", "-C", t["ws"], "ls-files", "*" + os.path.basename(x)], capture_output=True, text=True).stdout.strip()]
        # Round 33: test names in the answer must be defined in the repo too
        for tn in re.findall(r"\btest_\w+\b(?!\.)", st.get("answer") or ""):
            if not subprocess.run(["git", "-C", t["ws"], "grep", "-q", "-E", "def %s\\b" % tn], capture_output=True).returncode == 0:
                bad.append(tn)
        if bad:
            log(task, "3p", "pref %s settled answer names files or tests that do not exist: %s" % (o["pref"], bad))
            cites = []
        if st.get("answer") and cites:
            filled.append(dict(pref=o["pref"], rule=st["answer"], source="repo", evidence=[o["settle_ids"][c] for c in cites]))
        else:
            filled.append(_fill(task, dict(o, question=GENERAL_Q[o["pref"]], evidence=[], _ws=ws), sources))
    return filled, [s for s, _ in sources]


def run(t, outdir):
    try:
        return _run(t, outdir)
    except Exception as e:
        import traceback
        log(t["task"], "crash", traceback.format_exc()[-400:])
        return dict(task=t["task"], stated=[], step2=[], filled=[], crashed=True)


def _run(t, outdir):
    task, ws = t["task"], t["ws"]
    stated = step1(task, t["prompt"])
    # Round 34: Step 2 checks every preference, including stated ones, so a misread request cannot block the check.
    opened, results = step2(task, t, ws, list(PREFS))
    stated_by = {}
    for x in stated:
        stated_by.setdefault(x["pref"], []).append(x)
    keep = []
    for o in opened:
        if o["pref"] not in stated_by:
            keep.append(o)
        elif o["status"] == "open":
            said = " / ".join(x["rule"] for x in stated_by[o["pref"]])
            r = llm(S3, "<question>\n%s\n</question>\n\n<source kind=\"user\">\n%s\n</source>" % (o["question"], said))
            if r.get("answers") and norm(r.get("quote")) and norm(r["quote"]) in norm(said):
                continue                                   # the user's sentence answers it: keep the stated one
            log(task, "34", "pref %s stated sentence does not answer the open question; filling it: %s" % (o["pref"], o["question"][:100]))
            stated = [x for x in stated if x["pref"] != o["pref"]]
            keep.append(o)
    opened = keep
    t["_stated"] = stated
    filled, srcs = step3(task, t, ws, opened)
    res = dict(task=task, stated=stated, step2=opened, filled=filled, sources_tried=srcs, search_results=results,
               final=[dict(pref=s["pref"], rule=s["rule"], source=s["source"]) for s in stated + filled])
    json.dump(res, open(os.path.join(outdir, task + ".json"), "w"), indent=1)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tasks"); ap.add_argument("--out", required=True); ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    tasks = [t for t in json.load(open(a.tasks)) if not a.only or t["task"] in a.only]
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(4) as ex:
        for res in ex.map(lambda t: run(t, a.out), tasks):
            print("##", res["task"])
            for s in res["stated"]:
                print("   stated  %s | %s" % (s["pref"], s["rule"][:110]))
            for o in res["step2"]:
                print("   step2   %s | %s %s/3 | %s" % (o["pref"], o["status"], o.get("votes"), (o.get("question") or o.get("answer") or "")[:110]))
            for f in res["filled"]:
                print("   filled  %s | %s | %s" % (f["pref"], f["source"], f["rule"][:110]))
    json.dump(LOG, open(os.path.join(a.out, "check_log.json"), "w"), indent=1)
    print("checks logged:", len(LOG))
    for l in LOG:
        print("  ", l["task"], l["check"], l["msg"][:160])


if __name__ == "__main__":
    main()
