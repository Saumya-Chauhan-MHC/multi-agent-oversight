import os, subprocess, sys
from _util import boot, ROOT

INGEST, QUERY = 8091, 8092


def setup_module(module):
    log = os.path.join(ROOT, "data", "events.jsonl")
    if os.path.exists(log):
        os.remove(log)
    module.ing = boot("ingest/server.py", INGEST)
    module.qry = boot("query/server.py", QUERY)


def teardown_module(module):
    module.ing.kill()
    module.qry.kill()


def run(*args):
    r = subprocess.run([sys.executable, "cli/watch.py"] + list(args),
                       cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_send_prints_an_id():
    out = run("send", "api", "error", "cli boom").strip().splitlines()[-1]
    assert len(out.strip()) == 12


def test_tail_prints_the_event():
    run("send", "worker", "fatal", "cli fatal")
    out = run("tail", "--min-severity", "error")
    assert "cli fatal" in out and "worker" in out
    assert "fatal" in out


def test_tail_limit():
    for i in range(3):
        run("send", "api", "info", "m%d" % i)
    out = run("tail", "--limit", "2")
    assert len([l for l in out.splitlines() if l.strip()]) == 2


def test_check_names_every_rule():
    run("send", "api", "error", "c1")
    out = run("check")
    import json
    names = [r["name"] for r in json.load(open(os.path.join(ROOT, "config", "rules.json")))]
    for n in names:
        assert n in out
