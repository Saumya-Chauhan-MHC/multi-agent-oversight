# v4, the simplified tool

Two things come out compared to v3: the middle band, and the extractor.

## What changed and why

**One band instead of three.** v3 had hold, check and silent. A check paused nothing and you could
ignore it, so most of the machinery around it existed to stop it becoming a feed: ranking,
grouping, a precision floor and a ten minute quiet window. v4 either stops the tool call and asks
you, or says nothing.

The number that used to pick the band is gone too. v3 banded on the judge's confidence, and across
three measurements that confidence ordered decisions at 0.09, 0.52 and 0.67, where 0.5 means it is
telling you nothing. So the v4 judge is asked a yes or no question and there is no confidence field
to return, because nothing downstream would be allowed to read it.

**You write the rules.** v3 ran an LLM over your brief to extract them. That extractor then needed
a provenance check, a verbatim quote check and a five draw consensus vote to defend against its own
output, because it had twice produced a rule the developer never wrote, and once dropped the only
rule that mattered as a minority opinion.

None of that is needed if you write the rules down. A rule in `RULES.md` is yours by construction.
It cannot be invented, it cannot be out-voted, and the notice quotes it back to you exactly,
because the string in the notice is the string in your file.

The cost is that you have to write `RULES.md`. That is the trade.

**The recall net no longer calls the judge.** In v3, an action that matched no structural lookup
still went to the judge through a word overlap check, and was then capped at silence. That bought
a measurement and nothing else: 216 judge calls across two recordings, all 216 silent, and 0 of 8
right where it was the only trigger. In v4 it is recorded unjudged, so the blind spot is still
visible in the log and costs nothing.

## RULES.md

Three sections, all optional. Headings match on their first word, so `## Rules` and `## Hard rules`
are the same section.

```markdown
## Rules
- Never edit a file you don't own.
- Never write a check that cannot fail.

## Graded tests
tests/api/
tests/unit/test_core.py

## Shared interfaces
lib/http.py
```

The graded set is exactly what you list. v3 scraped directory names out of rule prose, which meant
a rule saying "never skip a test" produced the directory `test/` and then graded every path
containing it. Nothing here is inferred from prose.

## What it does during a run

1. The filter runs on every tool call. Most calls stop here.
2. Six structural lookups decide what gets through: is this file one you protected, is this port
   owned by another agent, has somebody already built on the file about to be rewritten. These are
   shared with v3 and unchanged.
3. What survives goes to one judge call. **LLM as judge**, one call per surviving decision, strict
   JSON, 45 second timeout, and it fails open so a timeout means silence and the work carries on.
   It answers one question: does this break one of the rules you wrote, yes or no. A yes has to
   name a rule by id and quote the part of the action that contradicts it. A yes naming a rule that
   is not in your file is turned into a no.
4. A yes holds the tool call and asks you. A no is recorded and you hear nothing.

Once you answer about a rule, that answer stands for the rest of the run, so an agent retrying the
same violation five times costs one interruption rather than five.

## Running it

```bash
# write RULES.md in the project, then
claude -p "$(cat PROMPT.md)" --permission-mode acceptEdits
```

`OV_SIMUSER=1` answers with a stand-in developer for running an arm unattended. It sees your rule,
the action, and the conflict, and answers block or allow. It is not shown that a judge was
involved, and there is no band or confidence to show it.

Replaying a recording offline:

```bash
python3 -I oversight/v4/replay4.py trajectory.jsonl RULES.md --out results.jsonl
```

## Files

| | |
|---|---|
| `rules.py` | reads `RULES.md`, no model involved |
| `judge4.py` | one call, yes or no, no confidence field |
| `policy4.py` | hold or silent, plus asked once per rule |
| `simuser4.py` | the stand-in developer |
| `replay4.py` | offline replay against a recorded run |
| `tests/test_v4.py` | 19 assertions covering the claims above |

v3 is kept alongside this and is unchanged, because the published benchmark numbers in `eval/`
were measured against it and have to stay reproducible.
