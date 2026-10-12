"""Boot a server surface and wait for its healthz. Shared by the two server tests."""
import json, os, subprocess, sys, time, urllib.request, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get(url, timeout=3):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode())


def post(url, obj, timeout=3):
    body = json.dumps(obj).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def get_status(url, timeout=3):
    try:
        return get(url, timeout)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def boot(script, port, wait=25):
    p = subprocess.Popen([sys.executable, script], cwd=ROOT,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + wait
    while time.time() < deadline:
        if p.poll() is not None:
            raise RuntimeError("%s exited with %s" % (script, p.returncode))
        try:
            st, body = get("http://127.0.0.1:%d/healthz" % port, timeout=1)
            if st == 200 and body.get("ok") is True:
                return p
        except Exception:
            time.sleep(0.3)
    p.kill()
    raise RuntimeError("%s never became healthy on %d" % (script, port))
