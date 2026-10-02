# NOTES

- A hand-written test task environment imitating a SWE-Marathon **full-stack application cloning** task: build a Slack clone from a spec, zero-to-one.
- Contents: `PROMPT.md` (the prompt), `task/docs/` (the spec), `task/tests/` (a REST verification suite), `task/` (the empty build workspace).
- It is **not** the real SWE-Marathon benchmark: not their prompt, spec, tests, or grader, and the 45-minute budget in `PROMPT.md` is invented.
- Scores here say nothing about SWE-Marathon performance; it exists only to give an agent a realistic zero-to-one build to work through.
- The 12 checks cover the documented REST surface only — no realtime layer, no UI, no rubric. Passing them is not the same as cloning Slack.
- No git repo, no dependencies, no network: pure text plus two small scripts.
