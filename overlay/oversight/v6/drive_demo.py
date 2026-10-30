#!/usr/bin/env python3
"""Run the interactive walkthrough and type the answers into it, for recording.

The demo really does block on input(); this drives that input through a pty so the answers
appear as they would if a person were typing them. It is a stand-in for the hands at the
keyboard and nothing else: the notices, the judge calls, the feedback hook and the rule rewrite
are the same code path a person would drive.
"""
import os, pty, re, select, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
OVERLAY = os.path.dirname(os.path.dirname(HERE))

# What to answer, in order. Each notice asks twice: allow, then a note.
ANSWERS = [
    ("n", "no, that test file is not yours to rewrite"),
    ("n", "tell sub_auth to announce the signature change first"),
    ("n", ""),
    ("n", "a read-only helper is fine, only writes go through the shared layer"),
]

ALLOW = re.compile(r"\[y\]es / \[n\]o >")
NOTE = re.compile(r"anything to say about it\?.*>")


def type_in(fd, text, cps=38):
    for ch in text:
        os.write(fd, ch.encode())
        time.sleep(1.0 / cps)
    time.sleep(0.35)
    os.write(fd, b"\n")


def main():
    args = sys.argv[1:] or ["--pace", "1.0", "--quiet", "40", "--dag"]
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(OVERLAY)
        os.execvp(sys.executable,
                  [sys.executable, os.path.join(HERE, "demo_live.py"), "--interactive"] + args)
    buf, i = "", 0
    while True:
        try:
            r, _, _ = select.select([fd], [], [], 1.0)
        except (OSError, ValueError):
            break
        if not r:
            continue
        try:
            chunk = os.read(fd, 4096)
        except OSError:
            break
        if not chunk:
            break
        sys.stdout.write(chunk.decode(errors="replace"))
        sys.stdout.flush()
        buf += chunk.decode(errors="replace")
        if ALLOW.search(buf[-220:]):
            time.sleep(1.1)
            type_in(fd, ANSWERS[min(i, len(ANSWERS) - 1)][0])
            buf = ""
        elif NOTE.search(buf[-220:]):
            time.sleep(1.1)
            note = ANSWERS[min(i, len(ANSWERS) - 1)][1]
            if note:
                type_in(fd, note)
            else:
                os.write(fd, b"\n")
            i += 1
            buf = ""
    os.waitpid(pid, 0)


if __name__ == "__main__":
    main()
