#!/usr/bin/env python3
"""No filter, no rule file: what has to hold instead."""
import os, sys, tempfile, json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))
from oversight.v5 import task, context, judge5, policy5

ok, fail = [], []


def check(name, cond):
    (ok if cond else fail).append(name)


TASK = ("Build the service. The REST API agent owns huddle/api/**.\n"
        "Component agents do NOT write start.sh or a supervisor.\n")

# --- the task description comes from the task, not from a second document --------------------
d = tempfile.mkdtemp()
open(os.path.join(d, "PROMPT.md"), "w").write(TASK)
tk = task.load(d)
check("the task is read from the task's own file", task.stated(tk) and "start.sh" in tk["text"])
check("the file it came from is recorded", tk["files"] == ["PROMPT.md"])
check("no task description disables the tool", not task.stated(task.load(tempfile.mkdtemp())))
check("CONTRACTS.md is read alongside PROMPT.md", True)
d2 = tempfile.mkdtemp()
open(os.path.join(d2, "PROMPT.md"), "w").write("spec")
open(os.path.join(d2, "CONTRACTS.md"), "w").write("seams")
check("both task files are joined", set(task.load(d2)["files"]) == {"PROMPT.md", "CONTRACTS.md"})
check("editing the task invalidates a cached answer",
      task.signature(tk) != task.signature(task.load(d2)))

# --- a yes has to quote the task, which replaces v4's rule-id lookup -------------------------
good = judge5._validate({"breaks": True, "said": "Component agents do NOT write start.sh",
                         "does": "x", "why": "y", "fix": "", "other_fix": ""}, TASK)
check("a faithful quote is accepted", good["breaks"])
bad = judge5._validate({"breaks": True, "said": "Agents must never use threads",
                        "does": "x", "why": "y", "fix": "", "other_fix": ""}, TASK)
check("an invented quote is turned into a no", not bad["breaks"])
check("and it is marked as such", bad["source"] == "invalid-quote")
wrapped = judge5._validate({"breaks": True, "does": "x", "why": "y", "fix": "", "other_fix": "",
                            "said": "Component agents  do NOT\nwrite start.sh"}, TASK)
check("a quote broken across lines still matches", wrapped["breaks"])
clash = judge5._validate({"breaks": True, "said": "", "does": "x", "why": "y", "fix": "",
                          "other_fix": "update your call"}, TASK)
check("a cross-agent clash may stand with no quote", clash["breaks"])
check("a no always carries both fix fields",
      all(k in judge5._validate({"breaks": False}, TASK) for k in ("fix", "other_fix")))

# --- there is no filter: context is gathered, nothing is gated -------------------------------
check("every repository-changing tool is watched",
      set(context.WATCHED) >= {"Write", "Edit", "MultiEdit", "Task"})
check("reading is not one of them", "Read" not in context.WATCHED and "Grep" not in context.WATCHED)

EV = [{"ov_event": "pre_tool", "agent_id": "b", "tool_name": "Write",
       "tool_input": {"file_path": "/w/wt_b/django/utils/html.py",
                      "content": "def text_preview(h):\n    return strip_tags(h)\n"}}]
o = context.others_on(EV, "/w/wt_a/django/utils/html.py", "a")
check("a write in another checkout is linked to this one", list(o) == ["b"])
check("and its own path is kept, for routing the repair",
      o["b"][0]["where"].endswith("wt_b/django/utils/html.py"))
check("an agent is not shown its own writes", context.others_on(EV, "/w/wt_b/django/utils/html.py", "b") == {})
check("separate checkouts are detected",
      context.separate_checkouts("/w/wt_a/django/utils/html.py", "/w/wt_b/django/utils/html.py"))
check("the same path is not two checkouts",
      not context.separate_checkouts("/w/a/x.py", "/w/a/x.py"))

# --- an edit reaches the judge as a labelled before and after --------------------------------
at = context.action_text("Edit", {"file_path": "x.py", "old_string": "def f():",
                                  "new_string": "def g():"})
check("the edit is labelled, not joined with spaces",
      "REPLACED THIS:" in at and "WITH THIS:" in at)
check("a deletion says so", "deleted" in context.action_text(
    "Edit", {"file_path": "x.py", "old_string": "def f():", "new_string": ""}))

# --- answers are keyed on the quoted sentence, since there are no rule ids -------------------
v1 = {"said": "Component agents do NOT write start.sh", "other_fix": ""}
v2 = {"said": "Component  agents do NOT write  start.sh", "other_fix": ""}
v3 = {"said": "The REST API agent owns huddle/api/**.", "other_fix": ""}
check("the same sentence is the same topic", policy5.topic(v1) == policy5.topic(v2))
check("a different sentence is a different topic", policy5.topic(v1) != policy5.topic(v3))
check("a quoteless clash still gets a topic", policy5.topic({"said": "", "other_fix": "do x"}))

p = tempfile.mkdtemp()
check("nothing is remembered before it is asked", policy5.answer_for(p, policy5.topic(v1)) is None)
policy5.record_answer(p, policy5.topic(v1), "block", "no")
check("an answer is remembered for the run",
      policy5.answer_for(p, policy5.topic(v2))["decision"] == "block")
check("and only for that sentence", policy5.answer_for(p, policy5.topic(v3)) is None)
check("a yes holds", policy5.decide({"breaks": True}) == "hold")
check("a no is silent", policy5.decide({"breaks": False}) == "silent")
check("there is no middle band",
      {policy5.decide({"breaks": b}) for b in (True, False)} == {"hold", "silent"})

print("%d passed, %d failed" % (len(ok), len(fail)))
for f in fail:
    print("  FAILED: %s" % f)
sys.exit(1 if fail else 0)
