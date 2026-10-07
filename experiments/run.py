#!/usr/bin/env python3
"""One run of one scenario, scored. See harness/runner.py for the flags every scenario shares and
<scenario>/scenario.py for its own.

  .venv/bin/python run.py port_kill --pref plain --model claude-sonnet-4-5-20250929 --rep 0
  .venv/bin/python run.py stale_merge --task input_cap --dummy blind
  .venv/bin/python run.py delegation_laundering --instance django__django-16032 --cond multi --prompt plain \
      --model claude-sonnet-4-5-20250929 --exp sonnet45_plain --oversight --answer no
  .venv/bin/python run.py <scenario> --help
"""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from harness.runner import load_scenario, main                      # noqa: E402

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1].startswith("-"):
        sys.exit(__doc__)
    main(load_scenario(sys.argv[1]), sys.argv[2:])
