#!/usr/bin/env python3
"""The stand-in developer. v4's, with the task description it is actually working from."""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from v4 import simuser4

MODEL = os.environ.get("OV_SIMUSER_MODEL", "claude-sonnet-5")


def ask(flag, model=MODEL, task="", asked_n=0):
    """v4's stand-in takes the task and the interruption count already; the only thing that
    changes here is that `said` is a quoted sentence rather than a rule the developer wrote,
    so the prompt's "THE RULE YOU WROTE" heading is still true: they wrote the task."""
    return simuser4.ask(flag, model=model, task=task, asked_n=asked_n)
