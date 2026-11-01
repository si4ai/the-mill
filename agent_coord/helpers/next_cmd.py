"""Append the read that lists valid names (card 735)."""
from __future__ import annotations


def with_next(text: str, step: str) -> str:
    """The refusal, then the next command, once.

    A line that already names a mill command is left as it is.
    """
    body = " ".join(str(text or "").split())
    nxt = " ".join(str(step or "").split())
    if not body:
        return ""
    if not nxt or "mill " in body:
        return body
    if body.endswith(".") or body.endswith(";"):
        return body + " " + nxt
    return body + ". " + nxt
