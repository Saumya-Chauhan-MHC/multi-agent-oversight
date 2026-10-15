#!/usr/bin/env python3
"""The claims v4 makes, as assertions."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))))
from oversight.v4 import rules, policy4, judge4, filter4
from oversight.v3 import taskmodel as tmod

RULES = """## Rules
- Never edit a file you don't own.
- Never write a check that cannot fail.
## Graded tests
tests/api/
tests/unit/test_core.py
## Shared interfaces
lib/http.py

## File ownership
nobody: start.sh, bin/
api agent: src/api/, tests/api/
"""
ok, fail = [], []


def check(name, cond):
    (ok if cond else fail).append(name)


tm = rules.parse(RULES)

# the rules are the developer's, verbatim, and nothing else is
check("every rule is the developer's own text",
      all(p["source"] == "developer" for p in rules.stated(tm)))
check("a rule is stored exactly as written",
      rules.stated(tm)[0]["rule"] == "Never edit a file you don't own.")
check("no rule appears that was not written", len(rules.stated(tm)) == 4)

# the graded set is exactly what was declared, with nothing inferred from prose
check("declared dirs are graded", tmod.is_graded(tm, "tests/api/test_auth.py"))
check("declared files are graded", tmod.is_graded(tm, "tests/unit/test_core.py"))
check("a dir merely mentioned in prose is not graded", not tmod.is_graded(tm, "src/test/x.py"))
check("unrelated files are not graded", not tmod.is_graded(tm, "src/app.py"))

# two bands only, and no number decides between them
check("a broken rule holds", policy4.decide(dict(breaks=True, rule="H1", source="judge")) == "hold")
check("an unbroken rule is silent", policy4.decide(dict(breaks=False, source="judge")) == "silent")
check("a judge that failed is silent",
      policy4.decide(dict(breaks=True, rule="H1", source="unavailable")) == "silent")
check("confidence is not consulted anywhere in the policy",
      "confidence" not in open(policy4.__file__).read())

# the judge cannot invent or misattribute a rule
check("a yes citing a real rule survives",
      judge4._validate(dict(breaks=True, rule="H1", does="x", why="y", fix="z"), tm)["breaks"])
check("a yes citing a rule that does not exist becomes a no",
      judge4._validate(dict(breaks=True, rule="H99", does="x"), tm)["source"] == "invalid-citation")
check("the notice quotes the rule from the file, not from the judge",
      judge4._validate(dict(breaks=True, rule="H2", does="x"), tm)["said"]
      == "Never write a check that cannot fail.")

# asked once per rule
with tempfile.TemporaryDirectory() as d:
    check("a rule starts unanswered", policy4.answer_for(d, "H1") is None)
    policy4.record_answer(d, "H1", "block", "no")
    check("an answer is remembered", policy4.answer_for(d, "H1")["decision"] == "block")
    check("another rule is still unanswered", policy4.answer_for(d, "H2") is None)

# every rule shape RULES.md permits has a lookup behind it. Arm F found the gap: a rule saying
# "do not write start.sh" was unenforceable because no lookup matched that path.
check("a forbidden path is caught structurally",
      (filter4.check(tm, [], "Write", {"file_path": "/p/start.sh", "content": "x"}, "a")
       or {}).get("reason") == "owned_file")
check("an owned path names its owner",
      (filter4.check(tm, [], "Write", {"file_path": "/p/src/api/core.py", "content": "x"}, "a")
       or {}).get("owner") == "api agent")
check("an unowned path is not claimed",
      (filter4.check(tm, [], "Write", {"file_path": "/p/README.md", "content": "x"}, "a")
       or {}).get("reason") != "owned_file")
check("reading an owned file is not a write",
      (filter4.check(tm, [], "Read", {"file_path": "/p/start.sh"}, "a") or {}).get("reason")
      != "owned_file")

# the signature binds a cached verdict to the rules that produced it
check("changing a rule changes the signature",
      rules.signature(tm) != rules.signature(rules.parse(RULES.replace("own.", "own!"))))

# no rules written means the tool does nothing at all
check("an empty rule file disables the tool", not rules.stated(rules.parse("# Rules\n")))

# --- the relay: the half of a repair that only the other agent's checkout can take -------------
import tempfile, json as _json
from oversight.v4 import relay

STARTED = [{"ov_event": "subagent_start", "agent_id": "b"}]
STOPPED = STARTED + [{"ov_event": "subagent_stop", "agent_id": "b"}]

check("a started agent is running", relay.running(STARTED, "b"))
check("a stopped agent is not", not relay.running(STOPPED, "b"))
check("a stop with no start is not believed",
      not relay.running([{"ov_event": "subagent_stop", "agent_id": "b"}], "b"))

TRIG = dict(path="B", reason="owned_file", others={"b": [{"where": "d/wt_b/django/utils/html.py",
                                                          "added": "strip_tags(html)"}]})


def _relay(verdict, trigger, events):
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "oversight"), exist_ok=True)
    with open(os.path.join(d, "oversight", "events.jsonl"), "w") as f:
        for e in events:
            f.write(_json.dumps(e) + "\n")
    to = relay.send(d, verdict, trigger, "a", "r1")
    box = os.path.join(d, "oversight", "control", "inbox")
    files = sorted(os.listdir(box)) if os.path.isdir(box) else []
    body = ""
    if files:
        body = open(os.path.join(box, files[0])).read()
    return to, files, body


to, files, body = _relay(dict(other_fix="call strip_tags_v2(html) instead"), TRIG, STARTED)
check("the running other agent is the recipient", to == ["b"])
check("the note lands in that agent's inbox, not the orchestrator's", files == ["b.jsonl"])
check("the note carries the judge's own sentence", "strip_tags_v2(html)" in body)
check("the note names the checkout the repair belongs in", "d/wt_b/django/utils/html.py" in body)
check("the note is tagged as a relay, not as a human", '"kind": "relay"' in body)

to, files, _ = _relay(dict(other_fix="call strip_tags_v2(html) instead"), TRIG, STOPPED)
check("a finished agent falls back to the orchestrator", to == ["orchestrator"])
check("the fallback lands in the orchestrator's mailbox", files == ["main.jsonl"])

check("nothing is relayed when the judge left other_fix empty",
      _relay(dict(other_fix=""), TRIG, STARTED)[0] == [])
check("nothing is relayed when no other agent is involved",
      _relay(dict(other_fix="do the thing"), dict(path="B", others={}), STARTED)[0] == [])

# the judge contract has to carry the field, or the relay is always empty
from oversight.v4 import judge4
check("a no-verdict still has the field",
      "other_fix" in judge4._validate({"breaks": False}, tm))
check("other_fix survives validation of a yes",
      judge4._validate({"breaks": True, "rule": "H1", "said": "x", "does": "y", "why": "z",
                        "fix": "f", "other_fix": "o"}, tm).get("other_fix") == "o")
check("the judge is asked for it", "other_fix" in judge4.SYSTEM)

print("%d passed, %d failed" % (len(ok), len(fail)))
for f in fail:
    print("  FAILED: %s" % f)
sys.exit(1 if fail else 0)
