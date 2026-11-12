# -*- coding: utf-8 -*-
"""Desk session stamp: wake -> first day-one command ok (A1) + wrong/retry (A2).

In-process per-desk clock from /ws connect. On first successful
day-one command, emit one mill-perf line ``op=wake.first_ok`` (ms + rpc + wrong +
retry + command). score_tick scrapes those lines for opt-in book KPIs (no Wall
chrome, no always-on Server-Timing).
"""
from __future__ import annotations

import threading
import time
from typing import Any

# Day-one useful commands (skill.md spine). Canonical names after outbound.canonical_command.
# create todo -> open; mail-thread kept. Not heartbeat/session/join.
DAY_ONE_OK_COMMANDS = frozenset(
    {
        "open",
        "todo",
        "claim",
        "assign",
        "unclaim",
        "pass",
        "send",
        "reply",
        "mail-thread",
        "inbox",
        "hold",
        "drop",
    }
)

# Noise: do not count toward rpc_n / wrong_n (keep-alives / session probes).
_SKIP_COMMANDS = frozenset({"heartbeat", "session", "join"})

KPI_WAKE_MS = "mill-office.wake_first_ms"
KPI_WAKE_RPC = "mill-office.wake_first_rpc"
KPI_WRONG_N = "mill-office.wrong_verb_n"
KPI_RETRY = "mill-office.retry_before_ok"
BOOK_PERF: dict[str, str] = {
    KPI_WAKE_MS: "p50 ms wake->first day-one ok (book); informational",
    KPI_WAKE_RPC: "p50 mill RPC count wake->first day-one ok (book); informational",
    KPI_WRONG_N: "p50 non-ok mill replies before first day-one ok (book); informational",
    KPI_RETRY: "p50 same-command fails before first day-one ok (book); informational",
}

_lock = threading.Lock()
# desk -> {t0: float, rpc_n: int, wrong_n: int, fails: dict[str,int], stamped: bool}
_sessions: dict[str, dict[str, Any]] = {}


def _who(desk: str) -> str:
    return str(desk or "").strip()


def mark_wake(desk: str) -> None:
    """Start (or reset) the desk clock. /ws connect."""
    who = _who(desk)
    if not who:
        return
    with _lock:
        _sessions[who] = {
            "t0": time.perf_counter(),
            "rpc_n": 0,
            "wrong_n": 0,
            "fails": {},
            "stamped": False,
        }


def clear_wake(desk: str) -> None:
    """Drop session on /ws down (optional; next connect remints)."""
    who = _who(desk)
    if not who:
        return
    with _lock:
        _sessions.pop(who, None)


def note_rpc(desk: str | None, command: str, *, ok: bool) -> None:
    """Count mill RPC; on first day-one ok emit wake.first_ok once per wake session.

    A2 fields on the same stamp: wrong= (non-ok count after t0), retry= (prior
    non-ok attempts of the same command that first-ok's). Stamp includes verb=.
    """
    who = _who(desk or "")
    if not who:
        return
    v = (command or "").strip().lower()
    if not v:
        return
    if v in _SKIP_COMMANDS:
        return
    stamp: dict[str, Any] | None = None
    with _lock:
        sess = _sessions.get(who)
        if not sess or sess.get("stamped"):
            return
        sess["rpc_n"] = int(sess.get("rpc_n") or 0) + 1
        if not ok:
            sess["wrong_n"] = int(sess.get("wrong_n") or 0) + 1
            fails = sess.setdefault("fails", {})
            if not isinstance(fails, dict):
                fails = {}
                sess["fails"] = fails
            fails[v] = int(fails.get(v) or 0) + 1
            return
        if v not in DAY_ONE_OK_COMMANDS:
            return
        t0 = float(sess.get("t0") or time.perf_counter())
        ms = max(0.0, (time.perf_counter() - t0) * 1000.0)
        rpc_n = int(sess["rpc_n"])
        wrong_n = int(sess.get("wrong_n") or 0)
        fails = sess.get("fails") or {}
        retry_n = int(fails.get(v) or 0) if isinstance(fails, dict) else 0
        sess["stamped"] = True
        stamp = {
            "ms": ms,
            "rpc": rpc_n,
            "wrong": wrong_n,
            "retry": retry_n,
            "desk": who,
            "verb": v,
        }
    if stamp is None:
        return
    try:
        from agent_coord.server.push import perf_log

        perf_log(
            "wake.first_ok",
            float(stamp["ms"]),
            rpc=int(stamp["rpc"]),
            wrong=int(stamp["wrong"]),
            retry=int(stamp["retry"]),
            desk=stamp["desk"],
            verb=stamp["verb"],
            ok=1,
        )
    except Exception:
        pass


def reset_for_tests() -> None:
    """Test helper: clear in-process sessions."""
    with _lock:
        _sessions.clear()


def session_snapshot(desk: str) -> dict[str, Any] | None:
    """Test helper: copy of desk session row."""
    who = _who(desk)
    with _lock:
        row = _sessions.get(who)
        if not row:
            return None
        out = dict(row)
        fails = out.get("fails")
        if isinstance(fails, dict):
            out["fails"] = dict(fails)
        return out
