"""Card 981: hold feature transitions + score views (no new schema).

Emits into shared `transition` via mill_transition_put using existing H1-H9
edges only. Meta carries ids/counts/flags - never resource names, desk names,
or hosts. hold.blocked ms stays on the PERFORMANCE path (hold_blocked).
"""
from __future__ import annotations

import statistics
import threading
from typing import Any

from agent_coord.server import transition as tr
from agent_coord.server.transition_enums import ActivityType, Reason, State

_pending_lock = threading.Lock()
# (desk_id, hold_id) refused and still waiting to acquire
_pending_wait: set[tuple[int, int]] = set()

KPI_WAIT = "hold.wait_ms"
KPI_HELD = "hold.held_ms"
KPI_CONTENTION = "hold.contention_n"
KPI_FORCE = "hold.force_taken_n"
KPI_EXPIRED = "hold.expired_n"

SCORE_NAMES = {
    KPI_WAIT,
    KPI_HELD,
    KPI_CONTENTION,
    KPI_FORCE,
    KPI_EXPIRED,
    "hold-wait",
    "hold-held",
    "hold-contention",
    "hold-force-taken",
    "hold-expired",
}


def join_key(hold_id: int, desk_id: int) -> str:
    return f"hold:{int(hold_id)}:{int(desk_id)}"


def _safe_put(cn, **kw) -> None:
    try:
        tr.put(cn, **kw)
    except Exception:
        # Instrumentation must not break hold/drop.
        pass


def emit_grant(
    cn,
    *,
    hold_id: int,
    desk_id: int,
    from_state: State = State.free,
) -> None:
    """H1 no_row->held or H2 free->held / hold_grant."""
    hid = int(hold_id)
    did = int(desk_id)
    if hid <= 0 or did <= 0:
        return
    src = from_state if from_state in (State.no_row, State.free) else State.free
    _safe_put(
        cn,
        activity_type=ActivityType.hold,
        activity_id=hid,
        from_state=src,
        to_state=State.held,
        reason=Reason.hold_grant,
        desk_id=did,
        role="holder",
        join_key=join_key(hid, did),
        meta=None,
    )


def emit_refresh(cn, *, hold_id: int, desk_id: int) -> None:
    """H3 held->held / hold_refresh."""
    hid = int(hold_id)
    did = int(desk_id)
    if hid <= 0 or did <= 0:
        return
    _safe_put(
        cn,
        activity_type=ActivityType.hold,
        activity_id=hid,
        from_state=State.held,
        to_state=State.held,
        reason=Reason.hold_refresh,
        desk_id=did,
        role="holder",
        join_key=join_key(hid, did),
        meta=None,
    )


def emit_drop(cn, *, hold_id: int, desk_id: int) -> None:
    """H4 held->free / hold_drop (owner release)."""
    hid = int(hold_id)
    did = int(desk_id)
    if hid <= 0 or did <= 0:
        return
    _safe_put(
        cn,
        activity_type=ActivityType.hold,
        activity_id=hid,
        from_state=State.held,
        to_state=State.free,
        reason=Reason.hold_drop,
        desk_id=did,
        role="holder",
        join_key=join_key(hid, did),
        meta=None,
    )


def emit_force(
    cn,
    *,
    hold_id: int,
    desk_id: int,
    by_desk_id: int | None = None,
) -> None:
    """H5 held->free / hold_force (admin / release-other).

    desk_id is the holder who lost the lock. meta.by is the acting desk id.
    """
    hid = int(hold_id)
    did = int(desk_id)
    if hid <= 0 or did <= 0:
        return
    meta = None
    if by_desk_id is not None and int(by_desk_id) > 0:
        meta = {"by": int(by_desk_id)}
    _safe_put(
        cn,
        activity_type=ActivityType.hold,
        activity_id=hid,
        from_state=State.held,
        to_state=State.free,
        reason=Reason.hold_force,
        desk_id=did,
        role="holder",
        join_key=join_key(hid, did),
        meta=meta,
    )


def emit_refuse(
    cn,
    *,
    hold_id: int,
    desk_id: int,
    holder_desk_id: int | None = None,
) -> None:
    """H7 any->refused / hold_refuse (waiter blocked)."""
    hid = int(hold_id)
    did = int(desk_id)
    if hid <= 0 or did <= 0:
        return
    meta = None
    if holder_desk_id is not None and int(holder_desk_id) > 0:
        meta = {"holder": int(holder_desk_id)}
    _safe_put(
        cn,
        activity_type=ActivityType.hold,
        activity_id=hid,
        from_state=State.any,
        to_state=State.refused,
        reason=Reason.hold_refuse,
        desk_id=did,
        role="waiter",
        join_key=join_key(hid, did),
        meta=meta,
    )


def emit_wait_acquire(cn, *, hold_id: int, desk_id: int) -> None:
    """H8 refused->held / hold_wait_acquire (waiter finally granted)."""
    hid = int(hold_id)
    did = int(desk_id)
    if hid <= 0 or did <= 0:
        return
    _safe_put(
        cn,
        activity_type=ActivityType.hold,
        activity_id=hid,
        from_state=State.refused,
        to_state=State.held,
        reason=Reason.hold_wait_acquire,
        desk_id=did,
        role="holder",
        join_key=join_key(hid, did),
        meta=None,
    )


def emit_expire(cn, *, hold_id: int, desk_id: int) -> None:
    """H9 held->expired / hold_expire (TTL path; count ready for 1013)."""
    hid = int(hold_id)
    did = int(desk_id)
    if hid <= 0 or did <= 0:
        return
    _safe_put(
        cn,
        activity_type=ActivityType.hold,
        activity_id=hid,
        from_state=State.held,
        to_state=State.expired,
        reason=Reason.hold_expire,
        desk_id=did,
        role="holder",
        join_key=join_key(hid, did),
        meta=None,
    )



def note_refused(desk_id: int, hold_id: int) -> None:
    did, hid = int(desk_id), int(hold_id)
    if did <= 0 or hid <= 0:
        return
    with _pending_lock:
        _pending_wait.add((did, hid))


def take_waited(desk_id: int, hold_id: int) -> bool:
    """True when this desk had a refuse on hold_id (clears the flag)."""
    did, hid = int(desk_id), int(hold_id)
    if did <= 0 or hid <= 0:
        return False
    with _pending_lock:
        if (did, hid) in _pending_wait:
            _pending_wait.discard((did, hid))
            return True
    return False


def reset_for_tests() -> None:
    with _pending_lock:
        _pending_wait.clear()


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
                " FROM transition WHERE activity_type='hold' ORDER BY id"
            )
        else:
            cur.execute(
                "SELECT id, activity_id, from_state, to_state, reason, desk_id, join_key, at, meta"
                " FROM transition WHERE activity_type='hold' AND desk_id=%s ORDER BY id",
                (int(desk_id),),
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


def score_view(cn, desk_id: int | None = None) -> dict[str, Any]:
    """Median+worst wait/held; contention / force / expired counts.

    Empty samples omitted (card 1019). desk_id scopes to that desk's history;
    None is the office rollup.
    """
    rows = _fetch(cn, desk_id)
    by_key: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        jk = str(r.get("join_key") or "")
        if not jk.startswith("hold:"):
            continue
        by_key.setdefault(jk, []).append(r)

    wait_ms: list[float] = []
    held_ms: list[float] = []
    contention = 0
    force_n = 0
    expired_n = 0

    for jk, events in by_key.items():
        refuse_at = None
        grant_at = None
        end_at = None
        for e in events:
            reason = str(e.get("reason") or "")
            at = e.get("at")
            if reason == "hold_refuse":
                contention += 1
                if refuse_at is None:
                    refuse_at = at
            if reason in ("hold_grant", "hold_wait_acquire") and grant_at is None:
                grant_at = at
            if reason == "hold_wait_acquire" and refuse_at is not None:
                ms = _ms(refuse_at, at)
                if ms is not None:
                    wait_ms.append(ms)
            if reason in ("hold_drop", "hold_force", "hold_expire"):
                end_at = at
            if reason == "hold_force":
                force_n += 1
            if reason == "hold_expire":
                expired_n += 1
        if grant_at is not None and end_at is not None:
            ms = _ms(grant_at, end_at)
            if ms is not None:
                held_ms.append(ms)

    out: dict[str, Any] = {"unit": "hold"}
    w = _summary(wait_ms)
    if w is not None:
        out["wait_ms"] = w
    h = _summary(held_ms)
    if h is not None:
        out["held_ms"] = h
    if contention > 0 or wait_ms or held_ms or force_n or expired_n:
        out["contention_n"] = _count(contention)
    if force_n > 0 or wait_ms or held_ms or contention or expired_n:
        out["force_taken_n"] = _count(force_n)
    if expired_n > 0 or wait_ms or held_ms or contention or force_n:
        out["expired_n"] = _count(expired_n)
    return out


def score_view_for_name(cn, name: str, desk_id: int | None = None) -> dict[str, Any]:
    view = score_view(cn, desk_id=desk_id)
    key = {
        KPI_WAIT: "wait_ms",
        "hold-wait": "wait_ms",
        KPI_HELD: "held_ms",
        "hold-held": "held_ms",
        KPI_CONTENTION: "contention_n",
        "hold-contention": "contention_n",
        KPI_FORCE: "force_taken_n",
        "hold-force-taken": "force_taken_n",
        KPI_EXPIRED: "expired_n",
        "hold-expired": "expired_n",
    }.get(name)
    if not key:
        return {}
    part = view.get(key)
    if part is None:
        return {"score": name, "missing": True}
    return {"score": name, **part}
