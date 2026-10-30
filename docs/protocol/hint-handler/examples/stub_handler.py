#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Minimal HINT-handler stub. Import tools.hint_handler. Task commands stay tiny.

stdin: one HINT JSON. parse_stdin() takes no argument.
Exit 0. Append one line to hint-evidence.jsonl beside this file.
Replace that write with your task mill commands.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# SoR draft root: .../hint-handler/ - until packaged:
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.hint_handler import parse_stdin, exit_err, exit_ok

_EVIDENCE = Path(__file__).resolve().parent / "hint-evidence.jsonl"


def _note(route_key: str, id_: object, hint: str, detail: object) -> None:
    kind = "recipe" if isinstance(detail, str) else "default"
    row = {"route_key": route_key, "id": id_, "hint": hint, "detail_kind": kind}
    with _EVIDENCE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, default=str) + "\n")


def main() -> int:
    try:
        ev = parse_stdin()
    except ValueError as e:
        _note("", None, "", f"bad stdin: {e}")
        return exit_err(2)
    if ev.ignore:
        return exit_ok()
    # detail is the recipe string, or the cheap default. Fetch leftovers only
    # when your task still needs the book.
    _note(ev.route_key, ev.id, ev.hint, ev.detail)
    return exit_ok()


if __name__ == "__main__":
    raise SystemExit(main())
