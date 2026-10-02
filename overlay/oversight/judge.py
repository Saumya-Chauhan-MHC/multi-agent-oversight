#!/usr/bin/env python3
"""The judge: one `claude -p` call per orchestration decision (SSOT appendix B3, prompt P2).

It answers one question: does this decision contradict anything the user said? It returns the
evidence, not a verdict to defer to, and it may only restate the user's own lines; it never invents
an exception the user has not stated.

Everything here fails open. A judge that is slow, unreachable or malformed must never block the
agent and must never look like a real "fits": it returns confidence 0 and `source: unavailable`, and
the caller records that.
"""
import json, os, subprocess, re, hashlib, tempfile

import memory

SYSTEM = """You are the user's stand-in for one decision about how an AI coding agent divides its work.

You see a proposed orchestration decision (usually a new subagent and its brief), the status of the
agent proposing it, and the user's own lines for this task. Go down the user's lines one by one and
decide whether the proposal contradicts any of them.

Return ONLY a JSON object, no prose, no code fence, with these fields:
  verdict: "fits" or "departs"
  governed_by: the id of the line that tells the agent HOW TO DIVIDE WORK INTO SUBAGENTS, or null if
           the user never said anything about how work should be divided. This is about the shape of
           the split only. A line about which files may be touched, or about testing, does NOT
           answer how to divide work, even when the proposal respects it. Examples: "one subagent
           per package or component" -> that line's id. "never edit run.sh from a subagent" -> null.
           "each subagent runs its own tests" -> null.
  confidence: a number between 0 and 1
  evidence: list of {line_id, said, proposed}; empty unless verdict is "departs"
  precedent: the id of the nearest line when no line covers the case, otherwise null
  suggestion: {action: "accept"|"modify"|"reject", note: string, from: [line_ids]}
  if_accepted: one sentence, in the user's words, to add to the user's lines if this decision stands
               as proposed; null when the verdict is "fits" and no precedent was needed

Rules:
- "departs" requires at least one evidence pair, and every line_id must be one of the user's lines.
- If your own explanation would say the proposal respects, satisfies or complies with the line, the
  verdict is "fits". Never return "departs" with reasoning that says the brief is correct.
- "One subagent per package or component" is SATISFIED by a subagent scoped to exactly one package,
  one component, one directory or one file. Splitting it further is optional, never required, so a
  single-component subagent is a fit even if you think a finer split would be nicer.
- A proposal that MATCHES a line is a fit, never a departure. "one subagent per file or module"
  is satisfied by a subagent that owns exactly one file, and by one that owns exactly one module.
  Never flag a proposal for being compatible with a line.
- In each evidence pair, `proposed` must quote the specific words from the brief that conflict with
  the line, not the spawn's name. If you cannot quote conflicting words, there is no departure.
- Evidence must quote what the proposal ITSELF says. Do not infer consequences the proposal does not
  state. "Building a package normally means touching __init__.py" is NOT evidence; the brief naming
  __init__.py is. If a protected file is not named in the proposal, no rule about that file is
  broken.
- Confidence 0.85 or above ONLY when the proposal's own words contradict a line.
- governed_by is NOT "the line this proposal respects". If the user never said how to divide work,
  governed_by is null even when the proposal breaks no rule; then set `precedent` to the nearest
  related line and keep confidence between 0.5 and 0.65.
- When governed_by is set, leave `precedent` null and cite that line in `suggestion.from`, and in
  `evidence` when it is contradicted.
- Judge the decision in front of you, not the whole plan, and not work the agent has already done.
- Read the brief's own words. A file the brief says NOT to touch, or says someone else owns, is not
  a proposal to edit it, and is never evidence of a departure.
- The suggestion may only restate the lines in `from`. Never propose an exception the user has not
  stated.
- Be brief. No reasoning outside the JSON."""


def _fingerprint(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


def _cache_path(ov, fp):
    d = os.path.join(ov, "judgements", "cache")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, fp + ".json")


def _extract_json(text):
    """Models wrap JSON in prose or fences more often than they should."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?|```$", "", text).strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None


def _validate(out, model):
    """Keep the contract: a departure needs real evidence against lines that exist."""
    ids = {m["id"] for m in model}
    verdict = out.get("verdict")
    if verdict not in ("fits", "departs"):
        return None
    try:
        conf = float(out.get("confidence", 0))
    except Exception:
        conf = 0.0
    conf = max(0.0, min(1.0, conf))
    ev = [e for e in (out.get("evidence") or [])
          if isinstance(e, dict) and e.get("line_id") in ids]
    if verdict == "departs" and not ev:
        verdict, conf = "fits", min(conf, 0.3)       # unsupported departure degrades, never holds
    # a departure whose own suggestion is "accept" is self-contradictory: trust the suggestion
    if verdict == "departs" and (out.get("suggestion") or {}).get("action") == "accept":
        verdict, conf, ev = "fits", min(conf, 0.5), []
    sug = out.get("suggestion") or {}
    if sug.get("action") not in ("accept", "modify", "reject"):
        sug = {"action": "accept" if verdict == "fits" else "reject",
               "note": str(sug.get("note", ""))[:300], "from": []}
    sug["from"] = [x for x in (sug.get("from") or []) if x in ids]
    prec = out.get("precedent") if out.get("precedent") in ids else None
    gov = out.get("governed_by")
    gov = gov if gov in ids else None
    covered = bool(gov) or bool(ev)          # a departure is covered by whatever it contradicts
    return dict(verdict=verdict, covered=covered, governed_by=gov, confidence=conf,
                evidence=ev[:4], precedent=prec,
                suggestion=sug, if_accepted=(out.get("if_accepted") or None), source="judge")


def unavailable(why):
    return dict(verdict="fits", covered=True, governed_by=None, confidence=0.0, evidence=[], precedent=None,
                suggestion={"action": "accept", "note": "", "from": []},
                if_accepted=None, source="unavailable", why=why)


def _neutral_cwd():
    """An empty directory to run the judge in.

    The judge is itself a Claude Code process. Run inside the task folder it would pick up the task's
    CLAUDE.md and its hooks, so its own session events landed in the task's events.jsonl and a later
    judgement read a previous judge's JSON as "what the parent plans next". It judges from the text
    we hand it, so it gets a folder with nothing in it.
    """
    d = os.path.join(tempfile.gettempdir(), "oversight-judge-cwd")
    os.makedirs(d, exist_ok=True)
    return d


def run(system, user_text, model_id, timeout_s):
    """One headless Claude Code call. No API key: this reuses the machine's own Claude Code auth."""
    cmd = ["claude", "-p", "--output-format", "json", "--model", model_id,
           "--strict-mcp-config",                      # do not load the project's MCP servers
           "--append-system-prompt", system]
    env = dict(os.environ)
    env["MAX_THINKING_TOKENS"] = "0"                   # 21s -> 3s, and the verdicts do not change
    env.pop("CLAUDE_PROJECT_DIR", None)                # do not let the judge adopt the task's setup
    try:
        p = subprocess.run(cmd, input=user_text, capture_output=True, text=True,
                           timeout=timeout_s, env=env, cwd=_neutral_cwd())
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"
    if p.returncode != 0:
        return None, (p.stderr or "")[-200:]
    try:
        envelope = json.loads(p.stdout)
        text = envelope.get("result") if isinstance(envelope, dict) else p.stdout
    except Exception:
        text = p.stdout
    return text, None


def judge_decision(ov, decision, parent_status, model=None, settings=None):
    """P2. `decision` is {kind, name, task, files, plan_next}; returns the validated verdict."""
    model = memory.load() if model is None else model
    st = memory.settings() if settings is None else settings
    if not model:
        return unavailable("no session model; run ctl.py init")

    payload = dict(decision=decision, parent=parent_status, lines=memory.as_prompt_lines(model))
    fp = _fingerprint(payload)
    cp = _cache_path(ov, fp)
    if os.path.exists(cp):                                   # same decision, same lines: reuse
        try:
            out = json.load(open(cp))
            out["cached"] = True
            return out
        except Exception:
            pass

    user_text = (
        "The user's lines for this task:\n" + "\n".join(payload["lines"]) +
        "\n\nThe agent proposing this decision:\n" + json.dumps(parent_status, indent=1) +
        "\n\nThe proposed decision:\n" + json.dumps(decision, indent=1) +
        "\n\nReturn the JSON object only."
    )
    text, err = run(SYSTEM, user_text, st["judge_model"], st["judge_timeout_s"])
    if text is None:
        return unavailable(err or "no output")
    out = _extract_json(text)
    if out is None:
        return unavailable("unparsable judge output")
    out = _validate(out, model)
    if out is None:
        return unavailable("invalid judge output")
    try:
        json.dump(out, open(cp, "w"), indent=1)
    except Exception:
        pass
    return out


def band(out, settings=None, model=None, dimension="division"):
    """Which of the SSOT's three levels this verdict lands in.

    hold  : departs, high confidence, a written line is contradicted  -> the spawn waits for a human
    check : middle confidence, or nothing in the model covers it      -> asked, but nothing waits
    silent: fits, or a judge we could not reach                       -> recorded as a mark only
    """
    st = memory.settings() if settings is None else settings
    lo, hi = st["check_band"]
    if out.get("source") == "unavailable":
        return "silent"
    if out["verdict"] == "departs" and out["confidence"] >= st["hold_band"]:
        return "hold"
    if out["verdict"] == "departs" and out["confidence"] >= lo:
        return "check"
    if not out.get("covered", True):
        # "nothing you said covers this" is the SSOT's middle case: the judge reports it, we route on
        # it. Keeping this with the judge is deliberate; the alternative (reading coverage off which
        # questions the user answered) would make the middle band a property of the form, not of the
        # decision in front of us.
        return "check"
    return "silent"
