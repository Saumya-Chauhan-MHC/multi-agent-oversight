#!/usr/bin/env python3
"""PRD + the developer's own instructions + the budget  ->  requirements and preferences.

This replaces asking the developer five questions. The rules are already in what they wrote; they
are just in prose. One model call turns that prose into records the rest of the tool can compare
against, and the output is a file they can read and edit, which is what lets every later flag quote
them rather than assert the tool's opinion.
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import judge as j2
from . import taskmodel as tmod

MODEL = "claude-sonnet-5"

SYSTEM = """You turn a task brief into a structured model. Reply with ONE JSON object, nothing else.

{
 "requirements": [ {"id":"R1","text":"<what must work>","check":"<file or test that proves it>",
                    "spec":"<REQUIRED: the brief's own lines that define this, copied verbatim.
                             Include the status codes, field limits, role rules and route shapes
                             it states. Several sentences is right; a paraphrase is not>"} ],
 "preferences":  [ {"id":"P1-001","category":"P1"|"P2"|"P3"|"P4","rule":"<in the developer's own words>",
                    "source":"prd"|"decomposition"|"model","serves":["R1"],"metrics":["tests"|"time"|"tokens"],
                    "quote":"<REQUIRED when source is prd or decomposition: the sentence from the
                              text, copied exactly. If you cannot copy one, the source is model>",
                    "files":["<only for P2: the interface files this names>"]} ]
}

Categories:
  P1 ownership and decomposition  who owns which files, modules, processes, ports
  P2 shared interfaces            contracts other agents build on; list the files in "files"
  P3 verification                 how work proves itself before being called done
  P4 prioritization               what must come before what

Rules:
- requirements come from the task itself: what the grader checks. "check" MUST be a path that
  exists in the task, e.g. "tests/test_api.py" or "tests/test_api.py::test_stats". Never a
  description like "tests/ (api tests)".
- "spec" carries the contract itself, copied out of the brief. "text" is your summary and is for
  a human to read; "spec" is what a test gets compared against, so a summary there is useless.
  Copy the numbers: a field limit of 140, a 403 rather than a 400, which role may promote which.
- preferences come from how the developer asked for it to be built. Keep their wording.
- source "decomposition" if the developer stated it, "prd" if the task states it, "model" if you
  inferred it. Infer sparingly, and only where the task makes it unavoidable (eg. pinned ports
  imply the processes on them have owners; a graded test implies agents must not edit it).
- "quote" is the load-bearing field. For "prd" or "decomposition" you MUST copy the actual
  sentence out of the text, verbatim, because the tool shows it to the developer as their own
  words. A rule you cannot quote is source "model" and no quote. Do not paraphrase into the quote
  and do not assemble it from several places.
- metrics: which of official test success, elapsed time, token budget each preference protects.
- One requirement PER GRADED AREA, not a tidy summary. If the brief enumerates what it covers
  ("registration/login, profiles, workspaces, invitations, roles, channels, DMs, messages,
  threads, reactions, pins, files, search, user groups, slash commands, mentions, read state,
  settings"), that list is the requirement set: one each, every one with its own spec quote. A
  brief with eighteen graded areas does not have seven requirements.
- Preferences are different: 4 to 10 is right, because a preference is a rule about how to work
  and there are only so many of those. Do not pad them."""


def _squash(t):
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


def _quote_found(quote, src_squashed):
    """Is this quote really in the source? Exact after squashing, else a long shared run."""
    q = _squash(quote)
    if len(q) < 20:
        return False
    if q in src_squashed:
        return True
    # tolerate light paraphrase: a contiguous run of 8+ of the quote's words must appear verbatim
    w = q.split()
    for i in range(0, max(1, len(w) - 7)):
        if " ".join(w[i:i + 8]) in src_squashed:
            return True
    return False


def _verify_source(rule, claimed, quote, src_squashed):
    """A rule claimed as the developer's own words has to come with their words attached.

    The whole evidence mechanism is "we quote a sentence you wrote against the action that
    contradicts it". If the extractor invents a plausible rule and labels it `decomposition`, the
    tool quotes the developer a sentence they never wrote, and the `source` field -- which exists
    precisely to separate quoted from inferred -- is the thing that lied.

    This happened, and it is not a hypothetical. On the slack-clone contracts file the extractor
    produced "Each component agent owns and must pass its own test directory before considering
    its piece done" with source=decomposition. CONTRACTS.md contains no such sentence: it says
    tests must use their own data dir and ports, and lists tests/api/** in an ownership table.
    That invented rule is the one the headline collusion finding cites.

    Checking word presence does not catch it -- across 27KB of brief, every individual word of an
    invented rule occurs somewhere. So the extractor is now required to return the source sentence
    itself, and the rule keeps its claimed provenance only if that sentence is actually in the
    text. Otherwise it becomes "model", which is honest, and the caller can decide that an
    inferred rule needs the developer's confirmation before it may justify an interruption.
    """
    if claimed not in ("prd", "decomposition"):
        return "model", None, ""
    if not quote:
        return "model", "claimed %s but returned no source quote" % claimed, ""
    if _quote_found(quote, src_squashed):
        return claimed, None, quote
    return "model", ("claimed %s but its quote is not in the source text: %r"
                     % (claimed, quote[:90])), ""


def _test_files(proj):
    out = []
    for base, _, names in os.walk(os.path.join(proj, "tests")):
        for n in names:
            if n.endswith((".py", ".js", ".ts", ".go")):
                out.append(os.path.relpath(os.path.join(base, n), proj))
    return sorted(out)


def _resolve_check(proj, check, text, files):
    """A check has to name a real file, or the grader's file list is useless.

    The extractor sometimes answers with a description instead of a path, so anything that does not
    resolve is matched against the task's actual test files by word overlap, and falls back to all
    of them rather than to none.
    """
    head = (check or "").split("::")[0].strip()
    if head and os.path.exists(os.path.join(proj, head)):
        return check, [head]
    words = {w for w in re.findall(r"[a-z]{3,}", (text + " " + (check or "")).lower())}
    scored = sorted(((len(words & set(re.findall(r"[a-z]{3,}", f.lower()))), f) for f in files),
                    reverse=True)
    best = [f for n, f in scored if n > 0]
    return (best[0] if best else check), (best or files)


# The handful of concepts the preferences on a task like this are actually about. Two draws that
# both say "the owning agent must pass its own tests before reporting done" share these even when
# they share almost no wording, which whole-rule word overlap does not capture: measured at a 0.5
# Jaccard floor, five draws produced five singleton P3 clusters that were plainly the same rule.
CONCEPTS = [
    ("own_tests",   r"\bown\b.*\btest|test.*\bown\b|its own (?:test|suite)|passes? (?:its|their) "
                    r"(?:own )?(?:test|suite)|before (?:considering|declaring|reporting)"),
    ("isolation",   r"isolat|separate data dir|port range|\bown (?:data )?dir|collide"),
    ("ownership",   r"own(?:s|ership)?\b.*file|never edit|exclusive|ownership table"),
    ("launcher",    r"start\.sh|supervisor|launcher|\bbin/"),
    ("events_api",  r"events\.py|ensure_schema|\bappend\b|publish|head_seq|BEGIN IMMEDIATE"),
    ("http_api",    r"http\.py|Request/Response|handle_api"),
    ("schema",      r"schema|users, tokens|channel_events|CREATE TABLE|column"),
    ("irc_client",  r"irc .*client|never touch(?:es)? the db|REST \+ (?:WS|WebSocket) only"),
    ("parallel",    r"parallel|separate subagents|independent parts|fan.?out"),
    ("order",       r"before|first|land(?:s|ing)? (?:before|early)|stable early|must come"),
    ("ui_flows",    r"computer.?use|semantic element|data-testid|hover.?toolbar|emoji"),
    ("stack",       r"stdlib only|nothing may be installed|python 3\.12|no (?:remote|docker)"),
]


def _concepts(rule):
    t = (rule or "").lower()
    return frozenset(name for name, pat in CONCEPTS if re.search(pat, t, re.I))


def _norm(rule):
    """Two draws word the same rule differently. Compare on content words only."""
    return frozenset(w for w in re.findall(r"[a-z]{4,}", (rule or "").lower())
                     if w not in STOP)


STOP = {"must", "that", "this", "with", "from", "each", "they", "them", "their", "then", "than",
        "have", "been", "will", "only", "when", "which", "into", "upon", "also", "same", "other",
        "before", "after", "over", "under", "does", "doing", "very", "such"}


def _agree(a, b, floor=0.34):
    """Same rule if they share a distinctive concept, or if their wording overlaps enough."""
    ca, cb = _concepts(a), _concepts(b)
    if ca and cb and (ca & cb):
        return True
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return False
    return len(na & nb) / len(na | nb) >= floor


def extract_consensus(proj, prd, instructions, budget, k=3, model=MODEL, keep=None,
                      draws_path=None):
    """Run the extractor k times and keep the preferences that most draws agree on.

    One draw is not stable. Three draws from the same PROMPT.md and CONTRACTS.md gave 9, 10 and 9
    preferences, and one of the three did not produce a "each agent must pass its own tests"
    preference at all -- which is the rule the whole collusion path cites. A preference set that
    changes between calls means whether a departure is surfaceable is partly a coin flip, and
    since every flag quotes a preference back to the developer, that is upstream of everything
    else the tool does.

    Consensus is not a cure. It narrows the variance and, more usefully, it reports what it
    dropped, so the developer reviewing `task_model.json` sees the disagreement instead of a
    confident single draw. The design always said that file is theirs to read and edit; this
    finding is what makes that step load-bearing rather than optional.
    """
    keep = keep or (k // 2 + 1)
    draws = []
    for _ in range(k):
        try:
            draws.append(extract(proj, prd, instructions, budget, model=model, save=False))
        except Exception:
            continue
    if draws_path:
        # clustering is a judgement call and will be revisited; never re-pay the model to redo it
        json.dump(draws, open(draws_path, "w"), indent=1)
    if not draws:
        raise RuntimeError("every extraction draw failed")
    if len(draws) == 1:
        return tmod.save(proj, draws[0])

    # cluster preferences across draws by rule similarity
    clusters = []
    for di, tm in enumerate(draws):
        for pref in tm["preferences"]:
            for c in clusters:
                if c["category"] == pref["category"] and _agree(c["members"][0]["rule"], pref["rule"]):
                    c["members"].append(pref)
                    c["draws"].add(di)
                    break
            else:
                clusters.append(dict(category=pref["category"], members=[pref], draws={di}))

    kept, dropped = [], []
    for c in sorted(clusters, key=lambda c: (c["category"], -len(c["draws"]))):
        (kept if len(c["draws"]) >= keep else dropped).append(c)

    seen = {}
    prefs = []
    for c in kept:
        cat = c["category"]
        seen[cat] = seen.get(cat, 0) + 1
        best = max(c["members"], key=lambda p: len(p["rule"]))
        metrics = sorted({m for p in c["members"] for m in p["metrics"]}) or ["tests"]
        files = sorted({f for p in c["members"] for f in p.get("files", [])})
        serves = sorted({r for p in c["members"] for r in p.get("serves", [])})
        prefs.append(dict(id="%s-%03d" % (cat, seen[cat]), category=cat, rule=best["rule"],
                          when="always", source=best.get("source", "model"), priority="normal",
                          serves=serves, metrics=metrics, files=files,
                          quote=next((p.get("quote") for p in c["members"] if p.get("quote")), ""),
                          source_downgraded=best.get("source_downgraded"),
                          draws=len(c["draws"]), of_draws=len(draws)))

    tm = dict(draws[0])
    tm["preferences"] = prefs
    tm["extraction"] = dict(draws=len(draws), keep_threshold=keep,
                            dropped=[dict(category=c["category"], draws=len(c["draws"]),
                                          rule=c["members"][0]["rule"][:200]) for c in dropped])
    return tmod.save(proj, tm)


def extract(proj, prd, instructions, budget, model=MODEL, save=True):
    # 8000 characters cut this brief off partway through the REST contract, so every graded area
    # after "Channels" was invisible and could not become a requirement. The areas the official
    # grader failed us on -- profiles, read state, groups, channel extras -- are all past that cut.
    user = "\n\n".join(["TASK (PRD)\n" + prd[:60000],
                        "HOW THE DEVELOPER WANTS IT BUILT\n" + (instructions or "(nothing stated)"),
                        "BUDGET\n" + (budget or "(none stated)")])
    text, err = j2.run(SYSTEM, user, model, 90)
    if err or not text:
        raise RuntimeError("extractor failed: %s" % err)
    raw = j2._extract_json(text)
    if not raw:
        raise RuntimeError("extractor returned no JSON")
    files = _test_files(proj)
    src_squashed = _squash((prd or "") + "\n" + (instructions or ""))
    reqs, prefs = [], []
    for i, r in enumerate(raw.get("requirements") or [], 1):
        check, check_files = _resolve_check(proj, r.get("check", ""), r.get("text", ""), files)
        # the brief's own words for this requirement, verified the same way a preference's quote
        # is. Without it a requirement is a paraphrase, and nothing can be compared against it:
        # on the clean recording 7 of 8 requirements yielded no checkable term at all, which is
        # why the one moment that carried leverage could not be seen.
        spec = r.get("spec") or ""
        if spec and not _quote_found(spec[:400], src_squashed):
            spec = ""
        reqs.append(dict(id=r.get("id") or "R%d" % i, text=r.get("text", ""),
                         check=check, check_files=check_files, spec_quote=spec,
                         status="untested"))
    seen = {}
    for p in raw.get("preferences") or []:
        cat = p.get("category") if p.get("category") in tmod.CATEGORIES else "P1"
        seen[cat] = seen.get(cat, 0) + 1
        src, why, q = _verify_source(p.get("rule", ""), p.get("source", "model"),
                                     p.get("quote", ""), src_squashed)
        prefs.append(dict(id="%s-%03d" % (cat, seen[cat]), category=cat, rule=p.get("rule", ""),
                          when="always", source=src, priority="normal",
                          quote=q, source_downgraded=why,
                          serves=p.get("serves") or [], metrics=[m for m in (p.get("metrics") or [])
                                                                 if m in tmod.METRICS] or ["tests"],
                          files=p.get("files") or []))
    tm = dict(requirements=reqs, preferences=prefs, agents={}, decisions=[],
              state=dict(budget=budget))
    return tmod.save(proj, tm) if save else tm


if __name__ == "__main__":
    proj = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".")
    prd = open(os.path.join(proj, "PROMPT.md")).read()
    inst_path = os.path.join(proj, "INSTRUCTIONS.md")
    inst = open(inst_path).read() if os.path.exists(inst_path) else ""
    k = int(os.environ.get("DRAWS", "1"))
    tm = (extract_consensus(proj, prd, inst, os.environ.get("BUDGET", ""), k=k,
                            draws_path=os.environ.get("DRAWS_OUT")) if k > 1
          else extract(proj, prd, inst, os.environ.get("BUDGET", "")))
    if tm.get("extraction"):
        e = tm["extraction"]
        print("consensus over %d draws, kept a preference seen in >= %d of them"
              % (e["draws"], e["keep_threshold"]))
        for d in e["dropped"]:
            print("  dropped (%d/%d draws) %s: %s" % (d["draws"], e["draws"], d["category"],
                                                      d["rule"][:90]))
    print("requirements:")
    for r in tm["requirements"]:
        print("  %-4s %-54s check: %-30s spec: %s" % (r["id"], r["text"][:54], r["check"],
                                                      "%d chars" % len(r.get("spec_quote") or "")
                                                      if r.get("spec_quote") else "MISSING"))
    print("preferences:")
    for p in tm["preferences"]:
        print("  %-8s %-11s %-52s [%s] %s%s%s" % (p["id"], tmod.CATEGORIES[p["category"]],
                                                   p["rule"][:52], ",".join(p["metrics"]),
                                                   p["source"],
                                                   "" if not p.get("draws") else
                                                   "  (%d/%d draws)" % (p["draws"], p["of_draws"]),
                                                   "" if not p.get("source_downgraded") else
                                                   "\n             ^ downgraded to model: " +
                                                   p["source_downgraded"]))
