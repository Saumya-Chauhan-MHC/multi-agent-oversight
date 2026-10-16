#!/usr/bin/env python3
"""A task model built from the task description, with no model in the loop.

This replaces extract.py and nothing else. Everything downstream of it in v3 is untouched: the
filter, the three bands, the queue, the quiet window and the metric gate all read the same
`task_model.json` they always did.

The extractor existed because a brief is prose and v3's filter indexes on preference objects.
But a task description is not undifferentiated prose. It is markdown with headings and bullets,
and every bullet is already a rule the developer wrote, in their own words. Parsing those is
deterministic, so the three defences the extractor needed against its own output (a provenance
check, a verbatim quote check and a five draw consensus vote) all stop being necessary: the
quote is exact by construction and nothing can be invented.

What is genuinely lost: the extractor assigned each preference the metrics it serves, and v3's
metric gate reads that field to decide whether a departure threatens anything. A parser cannot
infer it, so every preference here claims the test metric. That makes the metric gate less
discriminating than v3's was, and any arm run this way should say so rather than imply the gate
is doing the work it used to.
"""
import json, os, re

BULLET = re.compile(r"^\s*[-*]\s+(.+)")
MIN_LEN = 25                       # shorter bullets are list items, not rules

# Headings whose bullets are constraints rather than descriptions. Everything else still becomes
# a preference; this only decides how hard it is treated.
HARD = ("prohibit", "must", "require", "constraint", "rule", "error", "idempot")


def _clean(t):
    return re.sub(r"\*\*|`", "", t).strip()


def build(text, source_file="instruction.md"):
    prefs, section = [], ""
    for line in (text or "").splitlines():
        if line.startswith("#"):
            section = line.lstrip("# ").strip()
            continue
        m = BULLET.match(line)
        if not m or len(m.group(1)) < MIN_LEN:
            continue
        rule = _clean(m.group(1))
        low = section.lower()
        prefs.append(dict(
            id="P%d" % (len(prefs) + 1),
            category="H" if any(h in low for h in HARD) else "P2",
            rule=rule,
            quote=rule,                       # exact by construction, unlike an extracted one
            when="always",
            source="task-description",
            priority="hard" if any(h in low for h in HARD) else "soft",
            section=section,
            serves=[],
            metrics=["tests"],                # see the module docstring: this is an assumption
            files=[]))
    return dict(requirements=[], preferences=prefs, agents={}, decisions=[], state={},
                source=dict(kind="task-description", file=source_file, rules=len(prefs),
                            extracted=False))


NAMES = ("PROMPT.md", "instruction.md", "TASK.md", "CONTRACTS.md", "SPEC.md")


def write(proj):
    """Find the task description, build the model, write it where v3 expects it."""
    for n in NAMES:
        p = os.path.join(proj, n)
        if os.path.exists(p):
            tm = build(open(p, errors="ignore").read(), n)
            os.makedirs(os.path.join(proj, "oversight"), exist_ok=True)
            out = os.path.join(proj, "oversight", "task_model.json")
            json.dump(tm, open(out, "w"), indent=1)
            return out, len(tm["preferences"]), n
    return None, 0, None


if __name__ == "__main__":
    import sys
    out, n, src = write(sys.argv[1] if len(sys.argv) > 1 else ".")
    print("%s preferences from %s -> %s" % (n, src, out))
