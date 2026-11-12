# -*- coding: utf-8 -*-
"""Desk-local last read of a letter or card body (card 1125).

The office compares the stamp this desk last read (body_updated, or created
when the text was never edited). The file is per acting desk, so a later
command with --desk finds the same stamp. A missing key is never-read, which
refuses before the office is called. A stored created time is a real read.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

UNCHANGED = (
    "body:unchanged: replace did nothing: the new text is the same as the current text"
)


def stamp_text(value: Any) -> str:
    """Datetime text the office can compare. Empty when there is no stamp."""
    if value is None or value == "":
        return ""
    if hasattr(value, "isoformat"):
        try:
            text = value.isoformat(sep=" ")
        except TypeError:
            text = value.isoformat()
    else:
        text = str(value).strip()
    if not text or text.lower() == "none":
        return ""
    text = text.replace("T", " ", 1)
    if text.endswith("Z"):
        text = text[:-1]
    plus = text.find("+", 10)
    if plus > 0:
        text = text[:plus]
    return text.strip()


def read_hint(kind: str, item_id: int, roster: str = "") -> str:
    """The command that reads this item whole."""
    if kind == "mail":
        return f"mill mail-thread {int(item_id)} --full"
    who = str(roster or "").strip() or "ROSTER"
    return f"mill todo {who} {int(item_id)}"


def never_read(kind: str, item_id: int) -> str:
    return f"replace-body: read it first: {read_hint(kind, item_id)}"


def stale_line(kind: str, item_id: int, roster: str = "") -> str:
    return f"body:stale: read it again: {read_hint(kind, item_id, roster)}"


def map_refusal(msg: str | None, kind: str, item_id: int, roster: str = "") -> str | None:
    """body:stale names the reread. Every other refusal, including unchanged, stays as the office wrote it."""
    if msg == "body:stale":
        return stale_line(kind, item_id, roster)
    return msg


def _desk_file(desk: str) -> Path | None:
    who = str(desk or "").strip()
    if not who or len(who) > 64:
        return None
    ok = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-"
    if any(ch not in ok for ch in who):
        return None
    from agent_coord.config import mill_home

    return mill_home() / "body-read" / f"{who}.json"


def _load(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def load_stamp(desk: str, kind: str, item_id: int) -> str:
    path = _desk_file(desk)
    if path is None or not path.is_file() or kind not in ("mail", "todo"):
        return ""
    bucket = _load(path).get(kind)
    if not isinstance(bucket, dict):
        return ""
    try:
        key = str(int(item_id))
    except (TypeError, ValueError):
        return ""
    return stamp_text(bucket.get(key))


def save_stamp(desk: str, kind: str, item_id: Any, stamp: Any) -> None:
    path = _desk_file(desk)
    text = stamp_text(stamp)
    if path is None or kind not in ("mail", "todo") or not text:
        return
    try:
        item = int(item_id)
    except (TypeError, ValueError):
        return
    if item < 1:
        return
    data = _load(path) if path.is_file() else {}
    bucket = data.get(kind)
    if not isinstance(bucket, dict):
        bucket = {}
        data[kind] = bucket
    bucket[str(item)] = text
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")


def stamp_from_row(row: Any) -> str:
    """The stamp a read just showed: the edit stamp, else the created time."""
    if not isinstance(row, dict):
        return ""
    for key in ("body_stamp", "body_updated"):
        text = stamp_text(row.get(key))
        if text:
            return text
    return stamp_text(row.get("created"))


def prepare_replace(body: dict[str, Any]) -> None:
    """Fill expected from the last read, or refuse before the office is called.

    --history does not need a stamp and does not send one.
    """
    from agent_coord.helpers.errors import CoordError

    if str(body.get("verb") or "") != "replace-body" or body.get("history"):
        return
    kind = str(body.get("type") or "")
    try:
        item_id = int(body.get("id") or 0)
    except (TypeError, ValueError):
        item_id = 0
    if kind not in ("mail", "todo") or item_id < 1:
        return
    desk = str(body.get("sender_desk") or body.get("owner") or "").strip()
    stamp = load_stamp(desk, kind, item_id)
    if not stamp:
        raise CoordError(never_read(kind, item_id))
    body["expected"] = stamp


def remember(desk: str, args: Any, row: Any) -> None:
    """Store stamps from a full read or a replace that landed. A short preview does not count."""
    if not isinstance(row, dict) or row.get("ok") is not True:
        return
    cmd = str(getattr(args, "cmd", "") or "")
    result = row.get("result")
    if cmd == "mail-thread":
        chain = result.get("chain") if isinstance(result, dict) else None
        if not isinstance(chain, list):
            return
        for letter in chain:
            if not isinstance(letter, dict) or letter.get("body_trunc"):
                continue
            save_stamp(desk, "mail", letter.get("id"), stamp_from_row(letter))
        return
    if cmd == "todo" and str(getattr(args, "need", "") or "").strip():
        cards = result if isinstance(result, list) else None
        if isinstance(result, dict) and isinstance(result.get("cards"), list):
            cards = result["cards"]
        if not isinstance(cards, list):
            return
        for card in cards:
            if isinstance(card, dict):
                save_stamp(desk, "todo", card.get("id"), stamp_from_row(card))
        return
    if cmd == "replace-body" and not bool(getattr(args, "history", False)):
        if not isinstance(result, dict):
            return
        save_stamp(
            desk,
            str(result.get("type") or ""),
            result.get("id"),
            result.get("body_updated"),
        )
