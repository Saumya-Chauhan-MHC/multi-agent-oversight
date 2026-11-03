#!/usr/bin/env python3
"""Run a hook script with time.time() fixed to the recorded moment.

  OV_REPLAY_NOW=<seconds> python3 clock_wrap.py <hook.py>

The tool's queue reads time.time(). Without this a 6-minute trajectory replays in seconds and
every quiet window covers the rest of the run. Nothing in the tool is edited.
"""
import os, runpy, sys, time

NOW = float(os.environ["OV_REPLAY_NOW"])
time.time = lambda: NOW
script = sys.argv[1]
sys.argv = [script] + sys.argv[2:]
sys.path.insert(0, os.path.dirname(os.path.abspath(script)))
runpy.run_path(script, run_name="__main__")
