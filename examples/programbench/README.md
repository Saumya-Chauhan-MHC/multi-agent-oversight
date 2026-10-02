# ProgramBench

The harness used before the alignment layer: it fetches one ProgramBench task, prepares a task folder
with the overlay in it, and grades the result with the benchmark's own hidden tests.

The overlay does not depend on any of this. It watches Claude Code, not a benchmark, so it runs on a
ProgramBench task, a SWE Marathon task, or your own repository.

```bash
./setup.sh alecthomas__chroma.8d04def     # prepares ./task with the overlay in place
cd task && python3 oversight/ctl.py init  # the five questions
./run_interactive.sh                      # starts Claude Code on PROMPT.md
./grade.sh                                # runs the benchmark's hidden tests
python3 eval_by_module.py run/<id>/<id>.eval.json   # score by test module
```

`setup.sh` needs the `programbench` CLI and Docker. `RUNBOOK_chroma.md` is the long form for one task,
and `programbench_setup.md` has the setup notes.
