#!/usr/bin/env python3
"""Render each stage of the demo to a PNG, so the run can be shown rather than described.

Terminal output, not a mock-up: `demo6` is run for real and its text is split on the stage
banners, then each stage is drawn as the terminal drew it.
"""
import os, re, subprocess, sys
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OVERLAY = os.path.dirname(os.path.dirname(HERE))
FONT = "/System/Library/Fonts/Menlo.ttc"
BG, FG, DIM, HOT, GOOD = "#0d1117", "#d7dde3", "#7d8590", "#ff7b72", "#7ee787"
PAD, SIZE, LEAD = 26, 15, 21


def color(line):
    if line.startswith("=") or "STAGE" in line[:12]:
        return GOOD
    if line.startswith("DETECTED") or "[oversight" in line:
        return HOT
    if line.startswith(("SURFACED", "^", "(")):
        return DIM
    return FG


def draw(lines, path):
    f = ImageFont.truetype(FONT, SIZE)
    wide = max((f.getbbox(l)[2] for l in lines), default=600)
    img = Image.new("RGB", (int(wide) + PAD * 2, LEAD * len(lines) + PAD * 2), BG)
    d = ImageDraw.Draw(img)
    for i, l in enumerate(lines):
        d.text((PAD, PAD + i * LEAD), l, font=f, fill=color(l))
    img.save(path)
    return path


def main(outdir):
    os.makedirs(outdir, exist_ok=True)
    p = subprocess.run([sys.executable, os.path.join(HERE, "demo6.py")],
                       capture_output=True, text=True, cwd=OVERLAY,
                       env=dict(os.environ, PYTHONPATH=os.path.join(OVERLAY, "oversight")))
    text = p.stdout or p.stderr
    open(os.path.join(outdir, "v6_demo_full.txt"), "w").write(text)

    stages, cur, title = [], [], None
    for line in text.splitlines():
        m = re.match(r"\s*STAGE (\d+)\s+(.*)", line)
        if m:
            if title:
                stages.append((title, cur))
            title, cur = m.group(0).strip(), [line]
        elif title:
            cur.append(line)
    if title:
        stages.append((title, cur))

    made = []
    for title, lines in stages:
        n = re.match(r"STAGE (\d+)", title).group(1)
        slug = re.sub(r"[^a-z0-9]+", "_",
                      title.split(None, 2)[2].lower()).strip("_")[:44]
        out = os.path.join(outdir, "v6_stage%s_%s.png" % (n, slug))
        body = [l for l in lines if l.strip()]
        draw(body, out)
        made.append((title, out))
    return made


if __name__ == "__main__":
    for t, f in main(sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/Downloads")):
        print("%-70s %s" % (t[:70], os.path.basename(f)))
