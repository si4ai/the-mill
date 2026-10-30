# -*- coding: utf-8 -*-
"""Desk inbound: skill.md Hub frame -> route_key -> action.

Frame: {"type", "id", "hint"}. Hub PING is type=heartbeat (not an activity type).
Match the key. Do not interpret the frame with the model.
"""
from __future__ import annotations

from typing import Any

# skill.md inbound (canonical). ignore = do not queue / no mill command.
ROUTES: dict[str, dict[str, Any]] = {
    "heartbeat:PING": {"ignore": True},
    "doing:DOING": {"ignore": True},
    "mail:MAIL": {"verb": "inbox", "unread": True},
    "todo:TODO": {"verb": "todo"},
    "hold:HOLD": {"verb": "hold"},
    "score:SCORE": {"glance": True},

    "name:NAME": {"fyi": True},
}


def route_key(event: dict[str, Any] | None) -> str:
    msg = event or {}
    typ = str(msg.get("type") or "")
    hint = str(msg.get("hint") or "")
    if typ:
        return f"{typ}:{hint}"
    if hint:
        return f"{hint.lower()}:{hint}"
    return ""


def classify(event: dict[str, Any] | None) -> dict[str, Any]:
    msg = dict(event or {})
    key = route_key(msg)
    row = dict(ROUTES.get(key) or {})
    if str(msg.get("hint") or "") == "PING":
        row["ignore"] = True
        key = key or "heartbeat:PING"
    out = {"key": key, "ignore": bool(row.get("ignore"))}
    out.update(row)
    out["key"] = key
    if "id" in msg:
        out["id"] = msg.get("id")
    return out


def ignore(event: dict[str, Any] | None) -> bool:
    return bool(classify(event).get("ignore"))
