"""Grok Build poke: mill connect already has /ws. Ring Grok with grok -p -r.

Who it wakes: the Grok *session* bound to this mill desk (one UUID), not a
subagent. One TUI with many mill desks needs mill connect --session per desk
(or they all poke the same chat).

PING skipped.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from agent_coord.client.connectors.spawn import skip_ping, spawn_hint

VENDOR = "grok-build"


def session_path(desk: str) -> Path:
    from agent_coord.client.offices import desk_local_file
    from agent_coord.config import mill_home
    from agent_coord.helpers.ident import desk as slug_desk

    hosted = desk_local_file(desk, "grok-session")
    if hosted is not None:
        return hosted
    dest = mill_home() / "session"
    dest.mkdir(parents=True, exist_ok=True)
    return dest / f"{slug_desk(desk)}.grok-session"


def bind_session(desk: str, session_id: str) -> Path:
    sid = (session_id or "").strip()
    path = session_path(desk)
    if sid:
        path.write_text(sid + "\n", encoding="utf-8")
    return path


def grok_session_id(hint: dict[str, Any]) -> str:
    env = (os.environ.get("AGENT_COORD_GROK_SESSION") or "").strip()
    if env:
        return env
    desk = str(hint.get("desk") or os.environ.get("AGENT_COORD_OWNER") or "")
    try:
        p = session_path(desk)
        if p.is_file():
            return p.read_text(encoding="utf-8").strip().splitlines()[0].strip()
    except OSError:
        pass
    return ""


def _prompt(hint: dict[str, Any]) -> str:
    h = str(hint.get("hint") or "MAIL")
    typ = str(hint.get("type") or "")
    nid = hint.get("id") or ""
    return (
        f"mill HINT {h} type={typ} id={nid}. "
        "mill inbox unread or mill todo one card then STOP. "
        "Do not dump /api/floor."
    )


def poke(hint: dict[str, Any]) -> bool:
    """True when a chat-wake path ran; False when only a stamp remains (card 985)."""
    if skip_ping(hint):
        return False
    if spawn_hint(hint):
        return True
    url = (os.environ.get("AGENT_COORD_BOT_WAKE_URL") or "").strip()
    if url:
        from agent_coord.client.connectors import grok_bot

        return bool(grok_bot.poke(hint))
    sid = grok_session_id(hint)
    grok = shutil.which("grok")
    if grok and sid:
        subprocess.Popen(
            [grok, "-p", _prompt(hint), "-r", sid],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return True
    from agent_coord.client.connectors import grok_bot

    return bool(grok_bot.poke(hint))
