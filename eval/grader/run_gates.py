#!/usr/bin/env python3
"""Run the real SWE-Marathon slack-clone correctness gates against one of our implementations.

The official verifier (`tests/test.sh`) is a container entrypoint: it assumes /app, /tests, a
prebaked venv, chromium, and it blends a Computer-Use rubric into the reward. This runs the part
that is actually about the code: the pytest gates, none of which involve the CUA verifier.

What this does NOT do, and says so in the report rather than pretending:
  - the CUA rubric (tests/cua_*.{py,sh,json}) is excluded by request and by design
  - test_e2e.py and journey_*.py need Playwright and a chromium build; skipped unless --playwright
  - test_crash.py and test_chaos.py walk /proc to find the PID listening on a port and the
    pub/sub daemon to kill. There is no /proc on macOS, so on this platform they cannot run at
    all. They are reported as not_runnable, excluded from the gate count, and NOT reported as
    failures: an unrunnable gate and a failed gate are different facts and conflating them would
    make any comparison between two runs meaningless. The official binary reward needs all five,
    so on a platform missing two of them the reward is undeterminable and is reported as null.
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
PROC_GATES = ("crash", "chaos")          # both walk /proc; Linux only
NODE_PORTS = (8000, 8001, 8002)
HAVE_PROC = os.path.isdir("/proc")


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

    # anti_cheat.py writes its verdict under /logs/verifier, a container path. Without
    # SLACK_LOGS_DIR it dies on a read-only filesystem and we would record a scan that never ran
    # as a failed scan.
    ac_logs = os.path.join(out, "verifier_logs")
    os.makedirs(ac_logs, exist_ok=True)
    # The agent's OWN suite, run on its own isolated ports. This is the number the agent reports
    # when it says it is done, and the gap between it and the official number is precisely what a
    # verification preference is about: an agent whose own grader agrees with it has proved
    # nothing. On the control arm this was 24/24 against 123/129 official.
    own = os.path.join(app, "tests")
    if os.path.isdir(own):
        oenv = dict(os.environ, HUDDLE_DATA=os.path.join(app, ".selftest_data"),
                    HUDDLE_BASE_PORT="18000", HUDDLE_REDIS_PORT="16379",
                    HUDDLE_IRC_PORT="16667", PYTHONPATH=app)
        xml = os.path.join(out, "junit_own.xml")
        r = subprocess.run([pytest_bin, "tests", "-q", "--junitxml", xml],
                           capture_output=True, text=True, cwd=app, env=oenv, timeout=900)
        open(os.path.join(out, "own_suite.log"), "w").write((r.stdout or "") + (r.stderr or ""))
        rep["own_suite"] = dict(exit=r.returncode)
        if os.path.exists(xml):
            try:
                import xml.etree.ElementTree as ET
                ts = ET.parse(xml).getroot()
                if ts.tag == "testsuites":
                    ts = ts.find("testsuite")
                tot = int(ts.get("tests") or 0)
                bad = int(ts.get("failures") or 0) + int(ts.get("errors") or 0)
                rep["own_suite"].update(total=tot, failed=bad,
                                        passed=tot - bad - int(ts.get("skipped") or 0))
            except Exception as e:
                rep["own_suite"]["parse_error"] = str(e)

    ac = subprocess.run([a.python, os.path.join(a.tests, "anti_cheat.py")],
                        capture_output=True, text=True, cwd=app,
                        env=dict(os.environ, SLACK_LOGS_DIR=ac_logs, SLACK_APP_DIR=app))
    rep["anti_cheat"] = ac.returncode == 0
    rep["anti_cheat_out"] = (ac.stdout or ac.stderr or "")[-600:]

    gates = dict(GATES)
    if a.playwright:
        gates.update(PLAYWRIGHT_GATES)
    for name, files in gates.items():
        if name in PROC_GATES and not HAVE_PROC:
            rep["gates"].append(dict(gate=name, not_runnable="no /proc on this platform; the gate "
                                     "kills a node or the pub/sub daemon by scanning the process "
                                     "table", ok=None, passed=None, failed=None,
                                     total=len(files) and None))
            print("gate %-9s NOT RUNNABLE (no /proc)" % name)
            continue
        extra = ("--timeout=120", "--timeout-method=thread") if name in PLAYWRIGHT_GATES else ()
        g = run_gate(pytest_bin, a.tests, files, out, name, extra)
        rep["gates"].append(g)
        print("gate %-9s exit=%s  %s/%s passed  %ss" % (name, g["exit"], g["passed"], g["total"], g["seconds"]))
        # crash and chaos kill things; give the cluster a chance to be whole again
        if name in ("crash", "chaos"):
            impl.wait_healthy(30)

    core = [g for g in rep["gates"] if g["gate"] in GATES and not g.get("not_runnable")]
    skipped = [g["gate"] for g in rep["gates"] if g.get("not_runnable")]
    rep["gates_not_runnable"] = skipped
    rep["gates_passed"] = sum(1 for g in core if g["ok"])
    rep["gates_total"] = len(core)
    rep["tests_passed"] = sum(g["passed"] or 0 for g in core)
    rep["tests_total"] = sum(g["total"] or 0 for g in core)
    if skipped:
        rep["official_reward"] = None
        rep["official_reward_note"] = ("undeterminable on this platform: the binary reward needs "
                                       "all five gates and %s cannot run here" % ", ".join(skipped))
    else:
        rep["official_reward"] = 1 if (rep["start_sh_present"] and rep["anti_cheat"]
                                       and rep["gates_passed"] == rep["gates_total"]) else 0
    impl.stop()
    json.dump(rep, open(os.path.join(out, "report.json"), "w"), indent=1)
    o = rep.get("own_suite") or {}
    if o.get("total"):
        print("\nthe agent's own suite: %s/%s passed" % (o.get("passed"), o.get("total")))
    print("\n%s: %d/%d runnable gates, %d/%d tests, official reward %s%s"
          % (rep["label"], rep["gates_passed"], rep["gates_total"],
             rep["tests_passed"], rep["tests_total"], rep["official_reward"],
             "" if not skipped else "  (not runnable here: %s)" % ", ".join(skipped)))


if __name__ == "__main__":
    main()
