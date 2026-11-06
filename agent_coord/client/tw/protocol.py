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


def reply(ok: bool, msg: str, watch_id: str | None = None) -> dict[str, Any]:
    if watch_id:
        return {"type": "reply", "watch_id": watch_id, "ok": bool(ok), "msg": msg}
    return {"type": "reply", "ok": bool(ok), "msg": msg}


def line_too_long() -> dict[str, Any]:
    return {"type": "error", "code": "line_too_long", "max": LINE_MAX}


def stop_frame(watch_id: str, reason: str) -> dict[str, Any]:
    return {"type": "stop", "watch_id": watch_id, "reason": reason}
