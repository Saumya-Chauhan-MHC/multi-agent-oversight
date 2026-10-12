import json, os, socket, subprocess, sys, time, urllib.request, urllib.error
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8077


def _wait(port, timeout=12):
    end = time.time() + timeout
    while time.time() < end:
        try:
            socket.create_connection(("127.0.0.1", port), 0.3).close()
            return True
        except OSError:
            time.sleep(0.2)
    return False


def setup_module(_):
    global proc
    proc = subprocess.Popen([sys.executable, "api/server.py"], cwd=ROOT,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    assert _wait(PORT), "api did not come up on 8077"


def teardown_module(_):
    proc.terminate()


def _post(url):
    req = urllib.request.Request("http://127.0.0.1:%d/shorten" % PORT,
                                 data=json.dumps({"url": url}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req) as r:
        return r.status, json.loads(r.read())


def test_shorten_then_resolve():
    status, body = _post("https://example.com/one")
    assert status == 201 and len(body["code"]) == 7
    class NoFollow(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None                      # check the 302 itself, never leave the machine
    opener = urllib.request.build_opener(NoFollow)
    try:
        opener.open("http://127.0.0.1:%d/%s" % (PORT, body["code"]))
        assert False, "expected a redirect"
    except urllib.error.HTTPError as e:
        assert e.code == 302 and e.headers["Location"] == "https://example.com/one"


def test_stats_counts_hits():
    _, body = _post("https://example.com/two")
    code = body["code"]
    with urllib.request.urlopen("http://127.0.0.1:%d/stats/%s" % (PORT, code)) as r:
        before = json.loads(r.read())["hits"]
    try:
        urllib.request.urlopen("http://127.0.0.1:%d/%s" % (PORT, code))
    except urllib.error.HTTPError:
        pass
    with urllib.request.urlopen("http://127.0.0.1:%d/stats/%s" % (PORT, code)) as r:
        assert json.loads(r.read())["hits"] == before + 1


def test_unknown_code_404():
    try:
        urllib.request.urlopen("http://127.0.0.1:%d/0000000" % PORT)
        assert False, "expected 404"
    except urllib.error.HTTPError as e:
        assert e.code == 404
