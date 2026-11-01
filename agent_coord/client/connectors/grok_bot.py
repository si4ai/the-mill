"""Grok Bot leftover poke: spawn map first (see spawn.py), else URL, else stamp.

Set AGENT_COORD_VENDOR=grok-bot on the connect process.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from agent_coord.client.connectors.spawn import skip_ping, spawn_hint

VENDOR = "grok-bot"
_WAKE_TIMEOUT = 0.3
_DEAD_FOR = 30.0
_dead_until = 0.0


def _wake_url() -> str:
    try:
        from agent_coord.config import settings

        u = str(settings().get("bot_wake_url") or "").strip()
        if u:
            return u
    except Exception:
        pass
    return (os.environ.get("AGENT_COORD_BOT_WAKE_URL") or "").strip()


def _stamp_wake(hint: dict[str, Any]) -> Path | None:
    """Durable proof drain poked; not the book."""
    try:
        from agent_coord.config import mill_home
        from agent_coord.helpers.ident import desk as slug_desk

        desk = slug_desk(str(hint.get("desk") or "unknown"))
        from agent_coord.client.offices import desk_local_file

        hosted = desk_local_file(desk, "wake.jsonl")
        if hosted is None:
            dest = mill_home() / "session"
            dest.mkdir(parents=True, exist_ok=True)
            path = dest / f"{desk}.wake.jsonl"
        else:
            path = hosted
        line = json.dumps(hint, default=str, separators=(",", ":"))
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        return path
    except Exception:
        return None


def poke(hint: dict[str, Any]) -> bool:
    """After mill connect HINT: spawn map/CMD, else URL POST, else stamp file.

    True when a chat-wake path ran (spawn, URL, or equivalent). False when only
    a local stamp file was written (card 985: plain connect must then exit).
    """
    if skip_ping(hint):
        return False
    if spawn_hint(hint):
        return True
    url = _wake_url()
    if url:
        global _dead_until
        from agent_coord.server.wake import fire_wake_hook

        now = time.monotonic()
        if now < _dead_until:
            raise RuntimeError(f"grok-bot wake URL skipped: {url[:120]}")
        if not fire_wake_hook(url, hint, timeout=_WAKE_TIMEOUT):
            _dead_until = now + _DEAD_FOR
            raise RuntimeError(f"grok-bot wake URL failed: {url[:120]}")
        _dead_until = 0.0
        return True
    _stamp_wake(hint)
    return False
