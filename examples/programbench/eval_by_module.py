#!/usr/bin/env python3
"""Summarise a ProgramBench eval.json by test module, so the score can be read against the units
the agent built (e.g. chroma: test_harvest = per-language lexers, test_formatters, test_html_options).

    python3 eval_by_module.py run/alecthomas__chroma.8d04def/alecthomas__chroma.8d04def.eval.json
"""
import json, sys, collections
d = json.load(open(sys.argv[1]))
if d.get("error_code"):
    print("error_code:", d["error_code"]); print(d.get("error_details"))
    for s in d.get("log", []):
        if s.get("returncode") not in (0, None): print(f"step {s['step']} rc={s['returncode']}: {(s.get('output') or '')[-800:]}")
    sys.exit(1)
mods = collections.defaultdict(lambda: [0, 0]); fails = collections.defaultdict(list)
for t in d["test_results"]:
    m = t["name"].split(".")[-2] if t["name"].count(".") >= 2 else t["name"]
    mods[m][1] += 1
    if t["status"] == "passed": mods[m][0] += 1
    else: fails[m].append(t["name"].split(".")[-1])
tot = sum(v[1] for v in mods.values()); ok = sum(v[0] for v in mods.values())
print(f"{ok}/{tot} passed ({100*ok/tot:.1f}%)   executable_hash={d.get('executable_hash','')[:12]}")
for m, (a, b) in sorted(mods.items(), key=lambda kv: -kv[1][1]):
    print(f"  {m:32s} {a:4d}/{b:<4d} {100*a/b:5.1f}%   " + (f"e.g. failing: {', '.join(fails[m][:3])}" if fails[m] else ""))
