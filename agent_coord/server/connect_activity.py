"""Card 1028: connect FEATURE transitions + score views (no new schema).

Uses existing D2/D3 edges (doing: seated<->connected / connect|disconnect).
activity_id is the desk_id (desk-level connect lifecycle); join_key
connect:{desk_id}:{session_id} scopes score reads. Meta carries startup_ms
only (no names/hosts).
"""
from __future__ import annotations

import statistics
import threading
from datetime import datetime, timezone
from typing import Any

from agent_coord.server import transition as tr
from agent_coord.server.records.db import call as db_call
from agent_coord.server.transition_enums import ActivityType, Reason, State

KPI_STARTUP = "connect.startup_ms"
KPI_SESSION = "connect.session_ms"
KPI_DROP = "connect.drop_n"
KPI_RECONNECT = "connect.reconnect_n"

SCORE_NAMES = {
    KPI_STARTUP,
    KPI_SESSION,
    KPI_DROP,
    KPI_RECONNECT,
    "connect-startup",
    "connect-session",
    "connect-drop",
    "connect-reconnect",
}

_lock = threading.Lock()
# desk_id -> last session_id still connected (for reconnect detection helpers)
_live: dict[int, int] = {}
_sess_seq = 0


def join_key(desk_id: int, session_id: int) -> str:
    return f"connect:{int(desk_id)}:{int(session_id)}"


def _safe_put(cn, **kw) -> None:
    try:
        tr.put(cn, **kw)
    except Exception:
        pass


def _ensure_activity(cn, desk_id: int) -> None:
    """activity(type=doing, id=desk_id) so fk_transition_activity is satisfied."""
    try:
        db_call(
            cn,
            "mill_activity_put",
            [
                "doing",
                int(desk_id),
                datetime.now(timezone.utc).replace(tzinfo=None),
                int(desk_id),
                1,
                "focus",
                None,
            ],
        )
    except Exception:
        pass


def next_session_id(desk_id: int | None = None) -> int:
    global _sess_seq
    with _lock:
        _sess_seq += 1
        return _sess_seq


def emit_connect(
    cn,
    *,
    desk_id: int,
    session_id: int | None = None,
    startup_ms: int | None = None,
) -> int:
    """D2 seated -> connected / connect. Returns session_id used."""
    did = int(desk_id)
    if did <= 0:
        return 0
    sid = int(session_id or next_session_id(did))
    _ensure_activity(cn, did)
    meta = None
    if startup_ms is not None:
        try:
            meta = {"startup_ms": max(0, int(startup_ms))}
        except (TypeError, ValueError):
            meta = None
    _safe_put(
        cn,
        activity_type=ActivityType.doing,
        activity_id=did,
        from_state=State.seated,
        to_state=State.connected,
        reason=Reason.connect,
        desk_id=did,
        role="actor",
        join_key=join_key(did, sid),
        meta=meta,
    )
    with _lock:
        _live[did] = sid
    return sid


def emit_disconnect(cn, *, desk_id: int, session_id: int | None = None) -> None:
    """D3 connected -> seated / disconnect."""
    did = int(desk_id)
    if did <= 0:
        return
    with _lock:
        sid = int(session_id or _live.pop(did, 0) or 0)
    if sid <= 0:
        sid = next_session_id(did)
    _ensure_activity(cn, did)
    _safe_put(
        cn,
        activity_type=ActivityType.doing,
        activity_id=did,
        from_state=State.connected,
        to_state=State.seated,
        reason=Reason.disconnect,
        desk_id=did,
        role="actor",
        join_key=join_key(did, sid),
        meta=None,
    )


def desk_id_for(cn, desk: str | None) -> int | None:
    if not desk:
        return None
    cur = cn.cursor()
    try:
        cur.execute(
            "SELECT id FROM name WHERE type='desk' AND name=%s AND deleted IS NULL LIMIT 1",
            (str(desk).strip(),),
        )
        row = cur.fetchone()
        return int(row[0]) if row else None
    finally:
        cur.close()


def _fetch(cn, desk_id: int | None) -> list[dict[str, Any]]:
    cur = cn.cursor(dictionary=True)
    try:
        if desk_id is None or int(desk_id) <= 0:
            cur.execute(
                "SELECT id, activity_id, from_state, to_state, reason, desk_id, join_key, at, meta"
                " FROM transition WHERE activity_type='doing' AND join_key LIKE 'connect:%'"
                " ORDER BY id"
            )
        else:
            cur.execute(
                "SELECT id, activity_id, from_state, to_state, reason, desk_id, join_key, at, meta"
                " FROM transition WHERE activity_type='doing' AND desk_id=%s"
                " AND join_key LIKE %s ORDER BY id",
                (int(desk_id), f"connect:{int(desk_id)}:%"),
            )
        return list(cur.fetchall())
    finally:
        cur.close()


def _ms(a, b) -> float | None:
    if a is None or b is None:
        return None
    try:
        return max(0.0, (b - a).total_seconds() * 1000.0)
    except Exception:
        return None


def _summary(vals: list[float]) -> dict[str, Any] | None:
    if not vals:
        return None
    vals = sorted(float(v) for v in vals)
    return {
        "n": len(vals),
        "median": int(statistics.median(vals)),
        "worst": int(vals[-1]),
        "unit": "ms",
    }


def _count(n: int) -> dict[str, Any]:
    return {"n": int(n), "unit": "count"}


def _meta_startup(meta) -> int | None:
    if meta is None:
        return None
    if isinstance(meta, (bytes, bytearray)):
        meta = meta.decode()
    if isinstance(meta, str):
        try:
            import json

            meta = json.loads(meta)
        except Exception:
            return None
    if isinstance(meta, dict) and "startup_ms" in meta:
        try:
            return max(0, int(meta["startup_ms"]))
        except (TypeError, ValueError):
            return None
    return None


def score_view(cn, desk_id: int | None = None) -> dict[str, Any]:
    """Startup/session medians+worst; drop and reconnect counts. Empty omitted."""
    rows = _fetch(cn, desk_id)
    by_sess: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        jk = str(r.get("join_key") or "")
        if not jk.startswith("connect:"):
            continue
        by_sess.setdefault(jk, []).append(r)

    startups: list[float] = []
    sessions: list[float] = []
    drops = 0
    reconnects = 0
    # ordered connect events across desk for reconnect: disconnect then later connect
    timeline = sorted(rows, key=lambda r: int(r.get("id") or 0))
    last_was_disconnect = False
    for e in timeline:
        reason = str(e.get("reason") or "")
        if reason == "disconnect":
            drops += 1
            last_was_disconnect = True
        elif reason == "connect":
            if last_was_disconnect:
                reconnects += 1
            last_was_disconnect = False
            ms = _meta_startup(e.get("meta"))
            if ms is not None:
                startups.append(float(ms))

    for _jk, events in by_sess.items():
        conn_at = None
        disc_at = None
        for e in events:
            reason = str(e.get("reason") or "")
            at = e.get("at")
            if reason == "connect" and conn_at is None:
                conn_at = at
            if reason == "disconnect":
                disc_at = at
        if conn_at is not None and disc_at is not None:
            ms = _ms(conn_at, disc_at)
            if ms is not None:
                sessions.append(ms)

    out: dict[str, Any] = {"unit": "connect"}
    s = _summary(startups)
    if s is not None:
        out["startup_ms"] = s
    s = _summary(sessions)
    if s is not None:
        out["session_ms"] = s
    if drops or reconnects or startups or sessions:
        out["drop_n"] = _count(drops)
        out["reconnect_n"] = _count(reconnects)
    return out


def score_view_for_name(cn, name: str, desk_id: int | None = None) -> dict[str, Any]:
    view = score_view(cn, desk_id=desk_id)
    key = {
        KPI_STARTUP: "startup_ms",
        "connect-startup": "startup_ms",
        KPI_SESSION: "session_ms",
        "connect-session": "session_ms",
        KPI_DROP: "drop_n",
        "connect-drop": "drop_n",
        KPI_RECONNECT: "reconnect_n",
        "connect-reconnect": "reconnect_n",
    }.get(name)
    if not key:
        return {}
    part = view.get(key)
    if part is None:
        return {"score": name, "missing": True}
    return {"score": name, **part}


def reset_for_tests() -> None:
    with _lock:
        _live.clear()
