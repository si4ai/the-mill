#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mill route template - one redirector in this desk's chain.

stdin: one JSON frame {type, id, hint, desk, route, ...}, or a letter {kind: mail, id, ...}.
Do the mill command; do not expect the letter body on the frame. Do not call a model.

Exit marks (mill connect reads them, in chain order):
  exit 0, last stdout line "not-mine"  -> next redirector (vendor poke if none handle it)
  exit 0, anything else                -> handled; the chain stops, no vendor poke
  non-zero                             -> failed; next redirector, and one exit line in the next sync

Example:
  mill route add mail:MAIL -- python path/to/route-template.py
  mill route add "*" -- python path/to/route-template.py

Requires: mill on PATH (or PYTHONPATH=the-mill checkout), AGENT_COORD_OWNER set.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys


def main() -> int:
    raw = sys.stdin.read()
    try:
        hint = json.loads(raw or "{}")
    except json.JSONDecodeError:
        print("route-template: bad JSON on stdin", file=sys.stderr)
        return 2
    kind = str(hint.get("hint") or "").upper()
    if not kind and str(hint.get("kind") or "").lower() == "mail":
        kind = "MAIL"
    if kind in ("PING", "DOING"):
        return 0
    owner = (
        os.environ.get("AGENT_COORD_OWNER")
        or str(hint.get("desk") or "")
        or ""
    ).strip()
    project = os.environ.get("AGENT_COORD_PROJECT") or "the-mill"
    if not owner:
        print("route-template: set AGENT_COORD_OWNER", file=sys.stderr)
        return 1
    env = os.environ.copy()
    env["AGENT_COORD_OWNER"] = owner
    if kind == "MAIL":
        cmd = ["mill", "inbox", "--limit", "3"]
    elif kind == "TODO":
        cmd = ["mill", "todo", project]
    elif kind == "HOLD":
        print("route-template: HOLD - refuse writes / mill hold", flush=True)
        return 0
    else:
        print("not-mine", flush=True)
        return 0
    # Prefer checkout if PYTHONPATH set
    try:
        r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        cmd[0] = sys.executable
        cmd[1:1] = ["-m", "agent_coord"]
        r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30)
    sys.stdout.write(r.stdout or "")
    if r.returncode:
        sys.stderr.write(r.stderr or "")
    return int(r.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
