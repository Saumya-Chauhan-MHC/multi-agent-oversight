#!/usr/bin/env python3
"""Many runs of one scenario, in parallel. A run whose result.json exists is skipped, so a batch can
be restarted.

  .venv/bin/python batch.py port_kill --reps 3 --jobs 3 -- --pref plain --model claude-sonnet-4-5-20250929
  .venv/bin/python batch.py delegation_laundering --vary instance=django__django-16032,sympy__sympy-18189 \
      --vary cond=multi --reps 3 --jobs 3 -- --prompt plain --model claude-sonnet-4-5-20250929 --exp NAME
  .venv/bin/python batch.py delegation_laundering --sample 30 --vary cond=single,multi -- --model ...

--vary key=a,b runs every combination of the listed values as --key a / --key b. Everything after
`--` is passed to every run. --sample N draws N tasks from the scenario (delegation_laundering only)
and varies --instance over them.
"""
import argparse, itertools, os, subprocess, sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
from harness.runner import load_scenario, parser, run_dir_for      # noqa: E402


def main():
    argv = sys.argv[1:]
    fixed = argv[argv.index("--") + 1:] if "--" in argv else []
    argv = argv[:argv.index("--")] if "--" in argv else argv
    if not argv or argv[0].startswith("-"):
        sys.exit(__doc__)
    sc = load_scenario(argv[0])
    ap = argparse.ArgumentParser(prog="batch.py %s" % sc.name)
    ap.add_argument("--vary", action="append", default=[], metavar="KEY=A,B")
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--sample", type=int, help="N tasks drawn by the scenario, as --instance")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args(argv[1:])

    vary = [(k, v.split(",")) for k, v in (x.split("=", 1) for x in a.vary)]
    if a.sample:
        chosen = sc.sample(a.sample, a.seed)
        print("tasks:", " ".join(chosen), flush=True)
        vary.append(("instance", chosen))
    jobs = []
    for combo in itertools.product(*[[(k, v) for v in vs] for k, vs in vary]):
        for rep in range(a.reps):
            jobs.append(fixed + [x for k, v in combo for x in ("--" + k, v)] + ["--rep", str(rep)])

    run_parser = parser(sc)

    def one(job):
        d = run_dir_for(sc, run_parser.parse_args(job))
        if os.path.exists(os.path.join(d, "result.json")):
            return "skip " + os.path.relpath(d, sc.runs)
        sc.prepare_job(job)
        p = subprocess.run([sys.executable, os.path.join(HERE, "run.py"), sc.name] + job, capture_output=True, text=True)
        return (p.stdout.strip().splitlines() or [p.stderr[-500:]])[-1]

    with ThreadPoolExecutor(a.jobs) as ex:
        for line in ex.map(one, jobs):
            print(line, flush=True)


if __name__ == "__main__":
    main()
