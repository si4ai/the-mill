"""Thin HINT-handler helpers - parse / detail / mill-fetch leftovers / exit.

Not a second mill CLI. Commands stay on `mill` (or `python -m agent_coord`).
Cite: share/the-mill/docs/protocol/{hints,route,connect}.md
"""
from .lib import (
    HintEvent,
    parse_stdin,
    parse_hint,
    leftovers,
    run_mill,
    log,
    exit_ok,
    exit_err,
)

__all__ = [
    "HintEvent",
    "parse_stdin",
    "parse_hint",
    "leftovers",
    "run_mill",
    "log",
    "exit_ok",
    "exit_err",
]
