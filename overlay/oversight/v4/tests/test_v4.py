#!/usr/bin/env python3
"""The claims v4 makes, as assertions."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))))
from oversight.v4 import rules, policy4, judge4
from oversight.v3 import taskmodel as tmod

RULES = """## Rules
- Never edit a file you don't own.
- Never write a check that cannot fail.
## Graded tests
tests/api/
tests/unit/test_core.py
## Shared interfaces
lib/http.py
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

# the signature binds a cached verdict to the rules that produced it
check("changing a rule changes the signature",
      rules.signature(tm) != rules.signature(rules.parse(RULES.replace("own.", "own!"))))

# no rules written means the tool does nothing at all
check("an empty rule file disables the tool", not rules.stated(rules.parse("# Rules\n")))

print("%d passed, %d failed" % (len(ok), len(fail)))
for f in fail:
    print("  FAILED: %s" % f)
sys.exit(1 if fail else 0)
