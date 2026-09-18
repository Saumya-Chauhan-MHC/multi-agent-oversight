#!/usr/bin/env python3
"""Differential smoke check FOR YOU (the human), not for the agent and not the official grader.

Case file: one case per line, `ARGS ||| STDIN` (\\n = newline in STDIN). Each case is run through
./oracle/reference (the real binary, inside the task container) and ./executable (the agent's build)
and stdout, stderr and exit code are compared byte for byte. Run from the task folder:

    python3 oversight/tests/run_diff.py          # picks cases_<tool>.txt for the instance

If ./executable is still the reference wrapper (the agent has not built anything yet) every case
matches trivially, so that situation is reported instead of counted.
"""
import sys, subprocess, shlex, os
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # task root
ORACLE, CAND = os.path.join(ROOT, "oracle", "reference"), os.path.join(ROOT, "executable")

def run(binp, args, stdin):
    p = subprocess.run([binp] + shlex.split(args), input=stdin.encode(), capture_output=True, timeout=30, cwd=ROOT)
    return p.stdout, p.stderr, p.returncode

def main(files):
    try:
        if b"pb_ref" in open(CAND, "rb").read(400):
            print("./executable is still the reference wrapper: nothing to compare yet (compile.sh not run?)"); return 2
    except FileNotFoundError:
        print("./executable does not exist: run ./compile.sh first"); return 2
    tot = bad = 0
    for f in files:
        for ln in open(f):
            ln = ln.rstrip("\n")
            if not ln or ln.startswith("#"): continue
            args, _, stdin = ln.partition(" ||| ")
            stdin = stdin.replace("\\n", "\n")
            o = run(ORACLE, args, stdin)
            try: c = run(CAND, args, stdin)
            except (FileNotFoundError, PermissionError): c = (b"", b"<no executable>", -1)
            tot += 1
            if o != c:
                bad += 1
                print(f"DIFF [{f}] {ln}\n  reference: {o}\n  ours:      {c}")
    print(f"{tot - bad}/{tot} cases match ({bad} differences)")
    return 1 if bad else 0

def default_cases():
    """cases_<repo>.txt for the instance in oversight/instance_id (e.g. alecthomas__chroma.8d04def -> cases_chroma.txt)."""
    here = os.path.dirname(os.path.abspath(__file__))
    try: repo = open(os.path.join(ROOT, "oversight", "instance_id")).read().strip().split("__", 1)[1].split(".")[0]
    except Exception: repo = ""
    p = os.path.join(here, f"cases_{repo}.txt")
    if os.path.exists(p): return [p]
    print(f"no {os.path.basename(p)} for this instance; write one (ARGS ||| STDIN per line) or pass a file"); sys.exit(2)

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or default_cases()))
