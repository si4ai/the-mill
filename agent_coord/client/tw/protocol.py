# -*- coding: utf-8 -*-
"""Newline JSON for the local tw link. Same bytes on every OS."""
from __future__ import annotations

import json
from typing import Any

LINE_MAX = 8192
MAX_SESSIONS = 8


def dumps(obj: dict[str, Any]) -> bytes:
    return json.dumps(obj, separators=(",", ":"), default=str).encode("utf-8") + b"\n"


def loads(line: bytes) -> dict[str, Any]:
    msg = json.loads(line.decode("utf-8"))
    if not isinstance(msg, dict):
        raise ValueError("bad line")
    return msg


def reply(
    ok: bool,
    msg: str,
    watch_id: str | None = None,
    *,
    code: str | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {"type": "reply", "ok": bool(ok), "msg": msg}
    if watch_id:
        out["watch_id"] = watch_id
    if code:
        out["code"] = code
    return out


def line_too_long() -> dict[str, Any]:
    return {"type": "error", "code": "line_too_long", "max": LINE_MAX}


# JSON numbers the office stores. A bool is an int in Python and is not one of these.
_OFFICE_INT_MAX = 2**53 - 1


def bounded_int(value: Any, *, positive: bool = False) -> int | None:
    """A plain integer in range, or None when the office would drop the key."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < 0 or (positive and value < 1) or value > _OFFICE_INT_MAX:
        return None
    return value


def stop_frame(watch_id: str, reason: str) -> dict[str, Any]:
    return {"type": "stop", "watch_id": watch_id, "reason": reason}
