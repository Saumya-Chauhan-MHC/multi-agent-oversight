"""Shell and container helpers every scenario uses.

A task container is made in two steps. A first container prepares the repo and copies it out to the
workspace on the host; the real one mounts the workspace back at /testbed. Claude Code runs on the
host against the workspace, and hook.py sends its Bash calls into the container, so every path inside
the container is the one the image was built with.
"""
import subprocess

TESTBED_ENV = "source /opt/miniconda3/bin/activate\nconda activate testbed\n"


def sh(args, check=True, **kw):
    r = subprocess.run(args, capture_output=True, text=True, **kw)
    if check and r.returncode != 0:
        raise RuntimeError("%s\n%s\n%s" % (" ".join(map(str, args)), r.stdout[-2000:], r.stderr[-2000:]))
    return r


def dexec(ctr, script, check=True, timeout=None, inp=None):
    """bash -c inside the container; `inp` is sent on stdin."""
    args = ["docker", "exec"] + (["-i"] if inp is not None else []) + [ctr, "bash", "-c", script]
    return sh(args, check=check, timeout=timeout, input=inp)


def start(image, ctr, ws, prepare=None, env=TESTBED_ENV):
    """Copy the image's /testbed out to `ws` (after `prepare(prep_container)`, if given), then start
    `ctr` with `ws` mounted at /testbed. `env` becomes /root/.ib_env, which hook.py sources before
    every Bash call."""
    prep = ctr + "-prep"
    sh(["docker", "rm", "-f", prep], check=False)
    sh(["docker", "run", "-d", "--name", prep, "--platform", "linux/arm64", "-v", f"{ws}:/ws", image, "sleep", "infinity"])
    try:
        if prepare:
            prepare(prep)
        dexec(prep, "cp -a /testbed/. /ws/", timeout=1200)
    finally:
        sh(["docker", "rm", "-f", prep], check=False)
    sh(["docker", "run", "-d", "--name", ctr, "--platform", "linux/arm64", "-v", f"{ws}:/testbed", image, "sleep", "infinity"])
    dexec(ctr, "cat > /root/.ib_env", inp=env)
    dexec(ctr, "git config --global --add safe.directory '*'")


def remove(ctr):
    sh(["docker", "rm", "-f", ctr], check=False)
