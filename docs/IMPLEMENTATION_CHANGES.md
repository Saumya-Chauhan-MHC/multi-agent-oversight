# What changed in the implementation

Everything here was forced by a measurement, and each item has a regression check. The test suite
went from 38 checks to 104.

This covers the implementation only. The evaluation that produced it is a separate write-up.

---

## 1 · The extractor

**It was reading 39% of the brief.** `extract()` was called with `prd[:8000]` against a 20,683
character task. Nine of fifteen graded areas were cut off before it ever saw them. Combined with a
prompt instruction to produce "3 to 8 requirements", the result was **7 requirements for 18 graded
areas** and eight graded suites with no requirement record at all.

- `prd[:60000]`, and the instruction is now *one requirement per graded area, not a tidy summary*
- same brief now yields **17 requirements** instead of 7

**Requirements kept a paraphrase and threw the specification away.** A one-line summary —
*"Workspaces/channels CRUD, roles, membership semantics function per contract"* — cannot be
compared against anything. 7 of 8 requirements yielded no checkable term.

- every requirement now carries `spec_quote`: the brief's own sentences, copied verbatim and
  **verified by matching them back against the source text**
- 166 to 2,217 characters each, with the status codes, field limits and role rules intact

**A rule claimed as the developer's words was never checked against their words.** The extractor
produced *"each component agent owns and must pass its own test directory before considering its
piece done"* with `source: decomposition`. That sentence is **not in the contracts file** — the
ownership table grants an agent its test directory and nothing says it must pass it. Five draws with
quote verification produce it zero times. The tool was quoting the developer a sentence they never
wrote, and `source` — the field that exists to separate quoted from inferred — was the thing that
lied.

- a preference claiming `prd` or `decomposition` must now return the **source sentence**, which is
  matched against the text. If it is not there, the rule is downgraded to `source: model` and says
  why
- word-presence checking does not catch this: across 27KB of brief, every individual word of an
  invented rule occurs somewhere. The quote has to be returned and found

**Extraction is not stable across calls.** Three draws from the same two files gave 9, 10 and 9
preferences, and one produced no verification preference at all.

- `extract_consensus(k)`: k draws, keep what a majority agree on, cluster on distinctive concepts
  rather than whole-rule word overlap, and **report what was dropped** so the developer reviewing
  `task_model.json` sees the disagreement instead of a confident single draw

---

## 2 · What a flag may be held against

**Verification departures are now grounded in a requirement, not an invented preference.** Since no
contracts file on this task yields a verification preference about proving your component, the judge
may cite a `req_id`: the brief says what must work and names the file that proves it, so a declared
check that cannot do its job breaks the requirement directly, and the evidence shown is the brief's
own sentence.

- `taskmodel.declaring_requirements(tm, path)` — the requirements whose declared check this file is,
  matched by file **or containing directory**
- the judge's payload carries those requirements with their spec quotes, ordered by how little of
  each one's contract the action mentions
- `_validate` accepts `req_id` alongside `pref_id` and rejects a requirement whose check this file
  is not
- `policy.enqueue` groups on `grounds` — preferences and requirements together — so two agents
  breaking one requirement is still one recommendation

---

## 3 · The filter

**A `Write`'s body never reached the judge.** It is in `content`, not `new_string`, so the judge was
handed a bare filename.

**A long file lost the part that mattered.** Truncating at 4,000 characters dropped an `if False`
sitting at character 5,646 of a 15KB test. And asked whether a 33KB suite covered what the brief
requires, the judge answered on the first 3KB — in its own words, *"the snippet is just the start of
a real test file."*

- `_salient()` keeps the head, then **every test, fixture and suite the file declares**, then every
  line that looks like a disabled or skipped check, then the tail, with the elision declared
- a file's test names are its table of contents: without them the coverage question is unanswerable

**The graded file set was whatever test files existed when the extractor ran** — on a greenfield task
that is none of them, so it fell back to the literal paths the extractor guessed, and the agent wrote
different ones.

- `graded_dirs()` and `is_graded()`: the directories the checks live in, plus any test directory a
  preference names. The verifier runs directories, so a directory is the unit

**A dependency was recorded only from a `Read`.** An agent that writes `from huddle.web.http import
Request` never reads the file, so the edge that matters most was missing.

- import edges are derived from written code
- `same_file()` compares by suffix, because hooks report absolute paths and preferences name
  repo-relative ones

**The general trigger was swallowing the specific ones.** Once whole directories were graded,
`graded_file` fired before `disabled_check` and `weakened_check` on every test file.

- the specific triggers run first: naming what is wrong with the content beats saying the file is on
  a list

**The cache was not keyed on the actor**, so the lead defining an interface and a component agent
rewriting the same path later shared a verdict. The key now includes the agent.

---

## 4 · The judge prompt

- **ownership answers the ownership question and nothing else.** One line — *"an action its own brief
  authorises is a fit"* — let ownership settle verification and interface questions too, and passing
  an agent its own brief took every metric to zero. The categories are now evaluated separately, and
  the brief is **withheld** when a structural lookup has established a fact ownership cannot answer
- **a check that cannot fail is a departure even in a file the agent owns.** Owning the test file is
  not a defence for writing a test that does not test
- **reading is not editing.** A deterministic guard flips a departure to a fit when every cited rule
  is edit-only and the action is read-only

---

## 5 · Bands and delivery

**The check band had no output.** That branch of the hook was a bare `sys.exit(0)`. The tool was
putting medium-confidence items in the check band, correctly, and printing none of them.

- a check now prints: the same evidence chain, nothing paused, ignoring it a valid answer
- `window_open()` keys on `last_shown_ts` **as well as** `last_answer_ts`. A hold is always
  answered, so being shown and being answered used to be the same event; a check is never answered,
  and keying the quiet window on answers alone would leave it permanently open and let checks flood

**Word overlap could interrupt.** It is a recall net — it exists to get a decision in front of the
judge when no deterministic lookup matched. Across two recordings it produced 0 of 8 correct flags.

- an item whose only support is word overlap is **capped at silence**: still judged, still recorded,
  no vote on interrupting
- this matters more than a precision number suggests. With one channel rationed to one item every
  ten minutes, a false positive is not noise — **it is a true positive displaced**

**`policy.due()` spent the hourly preempt budget on a read.** A status check could silently disarm
the one interruption allowed per hour.

- `due()` is read-only; only the surface that actually interrupts calls `consume_preempt()`

**`SubagentStop` system messages are never rendered**, so the catch-up notice reached nobody. It is
queued and flushed on the next `PostToolUse`.

---

## 6 · The queue

The ranking key was `(metric, −confidence, arrival)`. Almost every preference on a software task
protects test success, so items tied on the first term and **confidence decided**. Confidence does
not rank these decisions: measured three times at AUC 0.09, 0.52 and 0.67, where 0.5 is no
information. On one recording the two items that mattered carried the **lowest** confidences of
eight and sorted last; three false positives spent the channel and both true positives were still
queued when the run ended.

The key is now:

```
(metric at risk,  is a deterministic fact behind it,  how specific that fact is,  arrival)
```

- **confidence is not in it at all.** A signal that does not rank is not neutral as a tiebreaker; it
  systematically disadvantages the decisions that matter
- `structural` before everything but the metric: a lookup result cannot be miscalibrated, it is
  already computed, and it is the only signal that tracked importance on either recording
- `specificity`: a named defect in the content beats "this file is on the grader's list"
- `arrival` last, which also keeps a notice closer to the action it is about

---

## 7 · A stand-in developer, for unattended runs

`OV_SIMUSER=1`. Exists because a treatment run with nobody to ask raised six holds and eleven checks
that all went nowhere, and reproduced the control exactly — it measured the cost of oversight when
ignored, not its effect.

- shown: the action, the rule in the developer's own words **or the brief's own sentence**, the
  provenance *including an explicit note when the rule was inferred rather than quoted*, the
  conflicting part, the predicted cost, the suggested correction
- **not** shown: the confidence or the band. A stand-in that can see how sure the tool is grades the
  tool's self-report rather than the evidence
- answers `block` / `note` / `ignore`, and `ignore` is deliberately easy to pick
- it is not a human study and must not be reported as one

---

## 8 · The offline harness and the grader

These are measurement, not the tool, and they were wrong in ways that produced plausible numbers.

- **the replay never modelled the land stage.** The live hook drops an item from the queue once its
  action has happened; the replay did not, so the top-ranked block was one whose action had already
  landed — which can never be the current decision — and nothing was ever shown again
- **`grounds` was dropped in the verdict-reuse path**, so every block was labelled `?`, they
  collapsed into one, and showing any member credited all of them: a recall of 1.00 that meant
  nothing. Reused verdicts now re-derive their grounds from the stored evidence
- **block delivery is now credited in scoring.** The design shows a *block*, so a member of a shown
  block has reached the user; crediting only the exact decision index produced a false miss
- **the grader takes a machine-wide lock**, after two grading chains tore down each other's cluster
  and made it look as though the tool had wrecked a run
- **a gate killed by a signal is recorded as void, not failed.** An unrunnable gate and a failed gate
  are different facts, and `crash`/`chaos` cannot run without `/proc`
- **the agent's own suite is run alongside the official one.** The gap between them is the number
  that matters: 24/24 against 123/129 on one arm
