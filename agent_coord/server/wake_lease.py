# -*- coding: utf-8 -*-
"""Card 1140: the wake lease in the book, as transitions on the wake that rang it.

A lease starts at the ring (the webhook POST) and ends done (mill wake-done),
expired (no done before it lapsed) or cleared (reset or retire). Its transitions
sit on the wake row that rang it (the newest wake row of the desk when the ring
names none) and share join_key ``lease:TOKEN``:

    ring -> lease_live    wake_sent    the ring (W3c)
    lease_live -> done    wake_done    mill wake-done or the automatic one (W9)
    lease_live -> expired wake_expire  lapsed; meta.late_s = seconds after the lapse (W12)
    lease_live -> cleared clear        Admin reset or retire (W12b)

Ring-to-done time is the ring row's ``at`` to the end row's ``at``. The wake
row's own state is never touched here: it stays ``taken`` after take, so
mill_push_take never hands a finished wake out again (I3/I4).

The live gate itself stays in wall memory (wake._GATE); this is its record.
Every write here is instrumentation: a failure never blocks a wake.
"""
from __future__ import annotations

from typing import Any

PREFIX = "lease:"
# Auditor 5532: renewal pushes expiry out, never past this many lease_s from the ring.
CAP_LEASES = 4

ENDS = ("done", "expired", "cleared")


def join_key(token: str) -> str:
    return PREFIX + str(token or "").strip()


def _anchor(cn, desk: str, wake_id: int) -> tuple[int, int]:
    """(desk_id, wake id) to hang the lease on; wake id 0 when the desk has no row."""
    from agent_coord.server import mail_activity as ma

    did = int(ma.desk_id_for(cn, desk) or 0)
    wid = int(wake_id or 0)
    cur = cn.cursor()
    try:
        if wid > 0:
            cur.execute("SELECT 1 FROM activity WHERE type = 'wake' AND id = %s", (wid,))
            if cur.fetchone() is None:
                wid = 0
        if wid <= 0 and did > 0:
            cur.execute("SELECT MAX(id) FROM wake WHERE desk_id = %s", (did,))
            row = cur.fetchone()
            wid = int((row or [0])[0] or 0)
    finally:
        cur.close()
    return did, wid


def ring_row(cn, token: str) -> dict[str, Any] | None:
    """The ring transition of this lease and its end, if any: {wake_id, desk_id, at, end}."""
    cur = cn.cursor()
    try:
        cur.execute(
            "SELECT activity_id, desk_id, at, to_state FROM transition"
            " WHERE join_key = %s AND activity_type = 'wake' ORDER BY id",
            (join_key(token),),
        )
        rows = cur.fetchall() or []
    finally:
        cur.close()
    ring = next((r for r in rows if r[3] == "lease_live"), None)
    if ring is None:
        return None
    end = next((r[3] for r in rows if r[3] in ENDS), None)
    return {"wake_id": int(ring[0]), "desk_id": int(ring[1]), "at": ring[2], "end": end}


def record_ring(cn, desk: str, token: str, wake_id: int = 0) -> int:
    """W3c: the lease starts. Returns the wake id it hangs on (0: nothing recorded)."""
    from agent_coord.server.transition_enums import ActivityType, Reason, State, put

    did, wid = _anchor(cn, desk, wake_id)
    if wid <= 0:
        return 0
    put(
        cn,
        activity_type=ActivityType.wake,
        activity_id=wid,
        from_state=State.ring,
        to_state=State.lease_live,
        reason=Reason.wake_sent,
        desk_id=did,
        role="office",
        join_key=join_key(token),
        meta={"lease": token},
    )
    return wid


def _ended(cn, token: str) -> bool:
    cur = cn.cursor()
    try:
        cur.execute(
            "SELECT 1 FROM transition WHERE join_key = %s AND activity_type = 'wake'"
            " AND to_state IN ('done', 'expired', 'cleared') LIMIT 1",
            (join_key(token),),
        )
        return cur.fetchone() is not None
    finally:
        cur.close()


def record_end(
    cn, token: str, end: str, meta: dict[str, Any] | None = None, *, desk: str = "", wake_id: int = 0
) -> bool:
    """End the lease once. False when it already ended, or has no ring row and no
    desk to hang the end on (no row written). A lease with no ring row (rung
    before this record existed, or its ring write failed) ends on the wake it
    named, else the desk's newest wake."""
    from agent_coord.server.transition_enums import ActivityType, Reason, State, put

    row = ring_row(cn, token)
    if row is None:
        if not desk or _ended(cn, token):
            return False
        did, wid = _anchor(cn, desk, wake_id)
        if wid <= 0:
            return False
        row = {"wake_id": wid, "desk_id": did, "end": None}
    if row["end"]:
        return False
    to_state, reason = {
        "done": (State.done, Reason.wake_done),
        "expired": (State.expired, Reason.wake_expire),
        "cleared": (State.cleared, Reason.clear),
    }[end]
    body = {"lease": token}
    body.update(meta or {})
    put(
        cn,
        activity_type=ActivityType.wake,
        activity_id=row["wake_id"],
        from_state=State.lease_live,
        to_state=to_state,
        reason=reason,
        desk_id=row["desk_id"],
        role="actor" if end == "done" else "office",
        join_key=join_key(token),
        meta=body,
    )
    return True


def live_in_book(cn, desk: str, max_age_s: float) -> tuple[str, float] | None:
    """The desk's newest lease with a ring and no end, rung at most max_age_s ago:
    (token, age_s). Used when wall memory has no lease for the desk (after a restart)."""
    from agent_coord.server import mail_activity as ma

    did = int(ma.desk_id_for(cn, desk) or 0)
    if did <= 0:
        return None
    cur = cn.cursor()
    try:
        cur.execute(
            "SELECT r.join_key, TIMESTAMPDIFF(MICROSECOND, r.at, UTC_TIMESTAMP(6)) / 1e6 FROM transition r"
            " WHERE r.desk_id = %s AND r.activity_type = 'wake' AND r.to_state = 'lease_live'"
            " AND r.from_state = 'ring' AND r.join_key LIKE 'lease:%%'"
            " AND r.at > UTC_TIMESTAMP(6) - INTERVAL %s MICROSECOND"
            " AND NOT EXISTS (SELECT 1 FROM transition e WHERE e.join_key = r.join_key"
            " AND e.to_state IN ('done', 'expired', 'cleared'))"
            " ORDER BY r.id DESC LIMIT 1",
            (did, int(max_age_s * 1e6)),
        )
        row = cur.fetchone()
    finally:
        cur.close()
    if not row or len(row) < 2 or not isinstance(row[0], str) or not row[0].startswith(PREFIX):
        return None
    try:
        age = float(row[1] or 0.0)
    except (TypeError, ValueError):
        return None
    return row[0][len(PREFIX):], age
