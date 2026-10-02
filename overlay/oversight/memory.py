#!/usr/bin/env python3
"""The user's lines: oversight/memory/session_model.json.

One file per task. It starts as the five init answers (q1..q5, in the user's own words) and grows by
one line per answer the user gives during the run (d1, d2, ...). Nothing is ever rewritten: a line
that contradicts an earlier one marks the old one superseded, so the history of the user's thinking
survives for the write-up.

Shape of one entry (SSOT appendix B1):

  {"id": "q2", "text": "one subagent per package or component", "source": "init",
   "status": "confirmed", "relates_to": [], "ts": 1790000000000}

Several spawns can be judged at once, so every write takes a lock and re-reads the file first.
"""
import json, os, time, errno

HERE = os.path.dirname(os.path.abspath(__file__))
MEM = os.path.join(HERE, "memory")
MODEL = os.path.join(MEM, "session_model.json")
SETTINGS = os.path.join(MEM, "settings.json")
LOCK = os.path.join(MEM, ".lock")

DEFAULT_SETTINGS = {
    "involvement": "ask",        # q4: "ask" on departure, or "never" (catch-up only)
    "catchup_threshold": 5,      # q5: low 3, medium 5, high 8
    "quick_check_wait": 60,      # q4 follow-up, seconds (unused while checks do not block)
    "hold_band": 0.85,           # departs at or above this holds the spawn
    "check_band": [0.5, 0.65],   # this range, or "no line covers it", asks a quick check
    # Sonnet over Haiku: on live briefs Haiku wrongly held 2 of 4 compliant spawns and never
    # produced the 0.5-0.65 band the design relies on. Sonnet got 4/4 and 12/12 on the eval,
    # for about 6s per judgement instead of 3.4s, and that time is credited back to the cap.
    "judge_model": "claude-sonnet-5",
    "judge_timeout_s": 45,
    "precision_floor": 0.70,    # below this, holds become checks: a false-alarm-prone flagger is worse than none
    "open_dag_on_hold": True,   # the graph opens itself only on a high-confidence departure
    "viewer_port": 4173,
}


def now_ms():
    return int(time.time() * 1000)


class _Lock:
    """Cheap cross-process lock; the hooks are short-lived so a stale lock is simply broken."""

    def __init__(self, path=LOCK, timeout=10.0):
        self.path, self.timeout, self.fd = path, timeout, None

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        t0 = time.time()
        while True:
            try:
                self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                return self
            except OSError as e:
                if e.errno != errno.EEXIST:
                    raise
                try:
                    if time.time() - os.path.getmtime(self.path) > 30:
                        os.unlink(self.path)          # stale
                        continue
                except OSError:
                    continue
                if time.time() - t0 > self.timeout:
                    return self                        # proceed unlocked rather than hang a hook
                time.sleep(0.05)

    def __exit__(self, *exc):
        if self.fd is not None:
            os.close(self.fd)
            try:
                os.unlink(self.path)
            except OSError:
                pass


def load():
    """The user's lines, oldest first. Missing file means init was never run."""
    try:
        return json.load(open(MODEL))
    except Exception:
        return []


def settings():
    s = dict(DEFAULT_SETTINGS)
    try:
        s.update(json.load(open(SETTINGS)))
    except Exception:
        pass
    return s


def save_settings(d):
    os.makedirs(MEM, exist_ok=True)
    s = settings()
    s.update(d)
    json.dump(s, open(SETTINGS, "w"), indent=1)
    return s


def write_init(lines):
    """Replace the model with the init lines. Only ctl.py init calls this."""
    os.makedirs(MEM, exist_ok=True)
    with _Lock():
        out = []
        for ln in lines:
            out.append(dict(id=ln["id"], text=ln["text"].strip(), source="init",
                            status="confirmed", relates_to=[], ts=now_ms()))
        json.dump(out, open(MODEL, "w"), indent=1)
    return out


def next_d_id(model):
    n = sum(1 for m in model if m["id"].startswith("d")) + 1
    return f"d{n}"


def append_answer(text, relates_to, source="answer", status="confirmed", supersedes=None, rid=None):
    """One line per user answer. Returns the new entry.

    `supersedes` marks earlier lines as replaced; the old text stays in the file so the run can be
    replayed and so the write-up can show how the user's model changed.
    """
    text = (text or "").strip()
    if not text:
        return None
    os.makedirs(MEM, exist_ok=True)
    with _Lock():
        model = load()
        for m in model:
            if supersedes and m["id"] in supersedes:
                m["status"] = f"superseded by {next_d_id(model)}"
        e = dict(id=next_d_id(model), text=text, source=source, status=status,
                 relates_to=list(relates_to or []), ts=now_ms())
        if rid:
            e["from_rid"] = rid
        model.append(e)
        json.dump(model, open(MODEL, "w"), indent=1)
    return e


def as_prompt_lines(model=None):
    """The lines as the judge sees them: id, text, and whether the user confirmed or guessed."""
    model = load() if model is None else model
    out = []
    for m in model:
        if str(m.get("status", "")).startswith("superseded"):
            continue
        out.append(f'{m["id"]}: "{m["text"]}" ({m.get("source", "init")}, {m.get("status", "confirmed")})')
    return out


def i0(model=None):
    """What goes into the orchestrator's first prompt (SSOT appendix B2, I0).

    Only the work-shaping lines. q4 and q5 are about the user's own involvement and stay with the
    tool, so the agent is never told how closely it is being watched.
    """
    model = load() if model is None else model
    keep = [m for m in model
            if not m["id"].startswith(("q4", "q5", "q6"))
            and not str(m.get("status", "")).startswith("superseded")]
    if not keep:
        return ""
    rules = "; ".join(m["text"].rstrip(".") for m in keep)
    return ("[oversight] The user's preferences for this task: " + rules +
            ". Spawns that depart from these are held for the user's decision.")
