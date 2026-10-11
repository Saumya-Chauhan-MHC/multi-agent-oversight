#!/usr/bin/env python3
"""Run the real SWE-Marathon slack-clone correctness gates against one of our implementations.

The official verifier (`tests/test.sh`) is a container entrypoint: it assumes /app, /tests, a
prebaked venv, chromium, and it blends a Computer-Use rubric into the reward. This runs the part
that is actually about the code: the pytest gates, none of which involve the CUA verifier.

What this does NOT do, and says so in the report rather than pretending:
  - the CUA rubric (tests/cua_*.{py,sh,json}) is excluded by request and by design
  - test_e2e.py and journey_*.py need Playwright and a chromium build; skipped unless --playwright
  - `reward` in the official verifier is binary across five gates. We record per-gate pass counts
    as well, because "4 of 5 gates, 118 of 121 API tests" is the number that tells you whether an
    oversight decision mattered, and binary reward is the number that does not.

Boot: the agent's own `start.sh` is used when it exists, because that is what the verifier grades.
When it is missing we boot the documented processes directly and set supervisor=false in the
report; test_crash.py and test_chaos.py both require a supervisor that respawns what they kill, so
with supervisor=false those two gates are expected to fail and that failure is attributable to a
missing launcher rather than to broken cluster code.
"""
import argparse, json, os, re, signal, socket, subprocess, sys, time, urllib.request

GATES = {
    "api": ["test_api.py", "test_profiles.py", "test_read_state.py", "test_channels_extra.py",
            "test_files.py", "test_slash.py", "test_groups.py", "test_invitations.py",
            "test_roles.py", "test_cluster.py", "test_ordering.py", "test_load.py"],
    "irc": ["test_irc.py"],
    "crash": ["test_crash.py"],
    "chaos": ["test_chaos.py"],
    "frontend": ["test_frontend.py"],
}
PLAYWRIGHT_GATES = {"e2e": ["test_e2e.py"], "journey": ["journey_onboarding.py"]}
NODE_PORTS = (8000, 8001, 8002)


def up(port, path="/api/health", timeout=1.5):
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d%s" % (port, path), timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def tcp(port):
    s = socket.socket()
    s.settimeout(1.0)
    try:
        s.connect(("127.0.0.1", port)); return True
    except Exception:
        return False
    finally:
        s.close()


def kill_ports(ports):
    """Nothing of ours should be holding the contract ports when a run starts."""
    for p in ports:
        subprocess.run("lsof -ti tcp:%d | xargs -r kill -9" % p, shell=True,
                       capture_output=True)


class Impl:
    """The implementation under test, booted the way the verifier would boot it."""

    def __init__(self, app, log):
        self.app, self.log = app, log
        self.procs = []
        self.supervisor = False

    def boot(self):
        sh = os.path.join(self.app, "start.sh")
        fh = open(self.log, "wb")
        if os.path.exists(sh):
            os.chmod(sh, 0o755)
            self.supervisor = True
            self.procs.append(subprocess.Popen(["bash", sh], cwd=self.app, stdout=fh,
                                               stderr=subprocess.STDOUT,
                                               start_new_session=True))
            return "start.sh"
        # No launcher. Boot the processes CONTRACTS.md documents, with no supervision.
        env = dict(os.environ, PYTHONPATH=self.app, HUDDLE_DATA=os.path.join(self.app, "data"))
        cmds = [["python3", "-m", "huddle.miniredis"]]
        cmds += [["python3", "-m", "huddle.node", "--node-id", str(i)] for i in range(3)]
        cmds += [["python3", "-m", "huddle.irc"]]
        for c in cmds:
            self.procs.append(subprocess.Popen(c, cwd=self.app, env=env, stdout=fh,
                                               stderr=subprocess.STDOUT, start_new_session=True))
            time.sleep(0.6)
        return "harness (no start.sh present)"

    def wait_healthy(self, secs=90):
        for i in range(secs):
            if all(up(p) for p in NODE_PORTS):
                return i + 1
            time.sleep(1)
        return None

    def stop(self):
        for p in self.procs:
            try:
                os.killpg(os.getpgid(p.pid), signal.SIGKILL)
            except Exception:
                pass
        kill_ports(list(NODE_PORTS) + [6379, 6667])


CTRF_SUMMARY = re.compile(r"(\d+) passed|(\d+) failed|(\d+) error")


def run_gate(pytest_bin, tests_dir, files, out_dir, name, extra=()):
    # pytest-ctrf is not installable here, so counts come from junit xml, which is built in
    report = os.path.join(out_dir, "junit_%s.xml" % name)
    cmd = [pytest_bin] + [os.path.join(tests_dir, f) for f in files] + \
          ["-rA", "-q", "--tb=line", "--junitxml", report] + list(extra)
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=tests_dir)
    took = round(time.time() - t0, 1)
    passed = failed = total = None
    if os.path.exists(report):
        try:
            import xml.etree.ElementTree as ET
            ts = ET.parse(report).getroot()
            if ts.tag == "testsuites":
                ts = ts.find("testsuite")
            total = int(ts.get("tests") or 0)
            bad = int(ts.get("failures") or 0) + int(ts.get("errors") or 0)
            skipped = int(ts.get("skipped") or 0)
            failed, passed = bad, total - bad - skipped
        except Exception as e:
            passed = failed = total = None
    tail = (r.stdout or "")[-4000:]
    open(os.path.join(out_dir, "gate_%s.log" % name), "w").write((r.stdout or "") + (r.stderr or ""))
    return dict(gate=name, exit=r.returncode, ok=r.returncode == 0, passed=passed,
                failed=failed, total=total, seconds=took, tail=tail.splitlines()[-12:])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("app", help="the implementation directory to grade")
    ap.add_argument("--tests", required=True, help="the official tasks/slack-clone/tests directory")
    ap.add_argument("--python", default=sys.executable, help="venv python with pytest+requests+websockets")
    ap.add_argument("--out", required=True)
    ap.add_argument("--playwright", action="store_true", help="also run test_e2e.py and journey_*.py")
    ap.add_argument("--label", default="")
    a = ap.parse_args()

    app = os.path.abspath(a.app)
    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    pytest_bin = os.path.join(os.path.dirname(a.python), "pytest")
    rep = dict(label=a.label or os.path.basename(app), app=app, at=time.strftime("%Y-%m-%dT%H:%M:%S"),
               cua_excluded=True, playwright=bool(a.playwright), gates=[])

    rep["start_sh_present"] = os.path.exists(os.path.join(app, "start.sh"))
    kill_ports(list(NODE_PORTS) + [6379, 6667])
    impl = Impl(app, os.path.join(out, "server.log"))
    rep["booted_via"] = impl.boot()
    rep["supervisor"] = impl.supervisor
    took = impl.wait_healthy()
    rep["health_seconds"] = took
    rep["health"] = took is not None
    rep["irc_port_open"] = tcp(6667)
    rep["redis_port_open"] = tcp(6379)

    if not rep["health"]:
        rep["note"] = "three nodes never answered /api/health; no gate was run"
        impl.stop()
        json.dump(rep, open(os.path.join(out, "report.json"), "w"), indent=1)
        print(json.dumps(rep, indent=1)); return

    ac = subprocess.run([a.python, os.path.join(a.tests, "anti_cheat.py")],
                        capture_output=True, text=True, cwd=app)
    rep["anti_cheat"] = ac.returncode == 0
    rep["anti_cheat_out"] = (ac.stdout or ac.stderr or "")[-600:]

    gates = dict(GATES)
    if a.playwright:
        gates.update(PLAYWRIGHT_GATES)
    for name, files in gates.items():
        extra = ("--timeout=120", "--timeout-method=thread") if name in PLAYWRIGHT_GATES else ()
        g = run_gate(pytest_bin, a.tests, files, out, name, extra)
        rep["gates"].append(g)
        print("gate %-9s exit=%s  %s/%s passed  %ss" % (name, g["exit"], g["passed"], g["total"], g["seconds"]))
        # crash and chaos kill things; give the cluster a chance to be whole again
        if name in ("crash", "chaos"):
            impl.wait_healthy(30)

    core = [g for g in rep["gates"] if g["gate"] in GATES]
    rep["gates_passed"] = sum(1 for g in core if g["ok"])
    rep["gates_total"] = len(core)
    rep["official_reward"] = 1 if (rep["start_sh_present"] and rep["anti_cheat"]
                                   and rep["gates_passed"] == rep["gates_total"]) else 0
    rep["tests_passed"] = sum(g["passed"] or 0 for g in core)
    rep["tests_total"] = sum(g["total"] or 0 for g in core)
    impl.stop()
    json.dump(rep, open(os.path.join(out, "report.json"), "w"), indent=1)
    print("\n%s: %d/%d gates, %d/%d tests, official reward %d"
          % (rep["label"], rep["gates_passed"], rep["gates_total"],
             rep["tests_passed"], rep["tests_total"], rep["official_reward"]))


if __name__ == "__main__":
    main()
