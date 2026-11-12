# -*- coding: utf-8 -*-
"""Card session stamp: claim -> done command count (A6 commands-to-done).

In-process per-card clock from successful claim/assign. Count mill commands that
target the card until pass reaches done. Note commands are stamped separately
(notes=) and excluded from verbs= (note spam). score_tick scrapes p50 into
opt-in book KPI (no Wall chrome, no always-on Server-Timing).
"""
from __future__ import annotations

import threading
import time
from typing import Any

from agent_coord.helpers.ident import slug

# Day-one card-targeting commands (skill.md todo spine).
CARD_COMMANDS = frozenset({"claim", "assign", "pass", "unclaim"})

# Start (or reset) a claim window.
_START_COMMANDS = frozenset({"claim", "assign"})

KPI_COMMANDS_TO_DONE = "mill-office.verbs_to_done"
BOOK_PERF: dict[str, str] = {
    KPI_COMMANDS_TO_DONE: (
        "p50 mill commands on a card claim->done excl. notes (book); informational"
    ),
}

_lock = threading.Lock()
# need_slug -> {t0, commands, notes, card_id, desk, stamped}
_sessions: dict[str, dict[str, Any]] = {}


def _who(desk: str) -> str:
    return str(desk or "").strip()


def _need_of(result: Any, body: dict[str, Any] | None) -> str:
    for src in (result, body or {}):
        if not isinstance(src, dict):
            continue
        for k in ("need_id", "need"):
            raw = src.get(k)
            if raw is not None and str(raw).strip():
                return slug(str(raw))
    return ""


def _card_id_of(result: Any) -> int:
    if not isinstance(result, dict):
        return 0
    try:
        return int(result.get("id") or 0)
    except (TypeError, ValueError):
        return 0


def note_card(
    desk: str | None,
    command: str,
    result: Any,
    *,
    body: dict[str, Any] | None = None,
) -> None:
    """Track ok card commands; on pass->done emit card.verbs_to_done once.

    Formula:
    - claim/assign ok starts (resets) the window; counts as verbs=1
    - subsequent ok card commands increment verbs= (note increments notes= only)
    - unclaim clears without stamp
    - pass -> shipped keeps counting (pass included in commands)
    - pass -> done stamps verbs= (excl notes) + notes= and closes
    """
    who = _who(desk or "")
    v = (command or "").strip().lower()
    if v not in CARD_COMMANDS:
        return
    if not isinstance(result, dict):
        return
    # Failed pass returns ok=False with no useful card window.
    if v == "pass" and result.get("ok") is False:
        return
    need = _need_of(result, body)
    if not need:
        return
    card_id = _card_id_of(result)
    stamp: dict[str, Any] | None = None
    with _lock:
        if v in _START_COMMANDS:
            # assign volunteer is the working desk when present.
            start_desk = who
            if v == "assign":
                vol = _who(str(result.get("volunteer") or ""))
                if vol:
                    start_desk = vol
            _sessions[need] = {
                "t0": time.perf_counter(),
                "verbs": 1,
                "notes": 0,
                "card_id": card_id,
                "desk": start_desk or who,
                "stamped": False,
            }
            return
        sess = _sessions.get(need)
        if not sess or sess.get("stamped"):
            return
        if card_id and not sess.get("card_id"):
            sess["card_id"] = card_id
        if v == "unclaim":
            _sessions.pop(need, None)
            return
        # pass / other card commands
        sess["verbs"] = int(sess.get("verbs") or 0) + 1
        if v == "pass" and str(result.get("status") or "") == "done":
            t0 = float(sess.get("t0") or time.perf_counter())
            ms = max(0.0, (time.perf_counter() - t0) * 1000.0)
            commands_n = int(sess.get("verbs") or 0)
            notes_n = int(sess.get("notes") or 0)
            cid = int(sess.get("card_id") or card_id or 0)
            desk_s = str(sess.get("desk") or who or "")
            sess["stamped"] = True
            stamp = {
                "ms": ms,
                "verbs": commands_n,
                "notes": notes_n,
                "card": cid,
                "need": need,
                "desk": desk_s,
            }
            # Drop after stamp so a re-claim can start fresh.
            _sessions.pop(need, None)
    if stamp is None:
        return
    try:
        from agent_coord.server.push import perf_log

        perf_log(
            "card.verbs_to_done",
            float(stamp["ms"]),
            verbs=int(stamp["verbs"]),
            notes=int(stamp["notes"]),
            card=int(stamp["card"]),
            need=stamp["need"],
            desk=stamp["desk"],
            ok=1,
        )
    except Exception:
        pass


def reset_for_tests() -> None:
    """Test helper: clear in-process card sessions."""
    with _lock:
        _sessions.clear()


def session_snapshot(need: str) -> dict[str, Any] | None:
    """Test helper: copy of card session row by need slug."""
    key = slug(str(need or ""))
    with _lock:
        row = _sessions.get(key)
        if not row:
            return None
        return dict(row)
