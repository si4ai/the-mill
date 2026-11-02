"""Card 982: open-cards queue FEATURE transitions + score views (no new schema).

Emits into shared `transition` via existing T1-T12 edges only. Meta carries
ids/flags (fixture) - never roster names, desk names, need slugs, or hosts.
"""
from __future__ import annotations

import re
import statistics
from datetime import datetime, timezone
from typing import Any

from agent_coord.server import transition as tr
from agent_coord.server.transition_enums import ActivityType, Reason, State

KPI_OPEN_TO_CLAIM = "todo.open_to_claim_ms"
KPI_CLAIM_TO_SHIP = "todo.claim_to_ship_ms"
KPI_SHIP_TO_DONE = "todo.ship_to_done_ms"
KPI_OPEN_AGE = "todo.open_age_ms"
KPI_CLAIMED_AGE = "todo.claimed_age_ms"
KPI_OPEN_N = "todo.open_n"
KPI_CLAIMED_N = "todo.claimed_n"

SCORE_NAMES = {
    KPI_OPEN_TO_CLAIM,
    KPI_CLAIM_TO_SHIP,
    KPI_SHIP_TO_DONE,
    KPI_OPEN_AGE,
    KPI_CLAIMED_AGE,
    KPI_OPEN_N,
    KPI_CLAIMED_N,
    "open-cards-open-to-claim",
    "open-cards-claim-to-ship",
    "open-cards-ship-to-done",
    "open-cards-open-age",
    "open-cards-claimed-age",
    "open-cards-open-n",
    "open-cards-claimed-n",
}

_FX_ROSTER = re.compile(r"^(fx-|cold-test\b|t-[0-9a-f]{8}$)", re.I)


def roster_excluded(roster: str | None) -> bool:
    who = str(roster or "").strip()
    if not who:
        return False
    if _FX_ROSTER.match(who):
        return True
    try:
        from agent_coord.lib.observe import is_fixture_project

        return bool(is_fixture_project(who))
    except Exception:
        return False


def join_key(todo_id: int) -> str:
    return f"card:{int(todo_id)}"


def _safe_put(cn, **kw) -> None:
    try:
        tr.put(cn, **kw)
    except Exception:
        pass


def _meta(fixture: bool) -> dict[str, int] | None:
    return {"fx": 1} if fixture else None


def emit_create(
    cn,
    *,
    todo_id: int,
    desk_id: int,
    parked: bool = False,
    fixture: bool = False,
) -> None:
    """T1 none->open / create, or T2 none->parked / create_parked."""
    tid = int(todo_id)
    did = int(desk_id)
    if tid <= 0 or did <= 0:
        return
    if parked:
        _safe_put(
            cn,
            activity_type=ActivityType.todo,
            activity_id=tid,
            from_state=State.none,
            to_state=State.parked,
            reason=Reason.create_parked,
            desk_id=did,
            role="actor",
            join_key=join_key(tid),
            meta=_meta(fixture),
        )
    else:
        _safe_put(
            cn,
            activity_type=ActivityType.todo,
            activity_id=tid,
            from_state=State.none,
            to_state=State.open,
            reason=Reason.create,
            desk_id=did,
            role="actor",
            join_key=join_key(tid),
            meta=_meta(fixture),
        )


def emit_unpark(cn, *, todo_id: int, desk_id: int, fixture: bool = False) -> None:
    tid, did = int(todo_id), int(desk_id)
    if tid <= 0 or did <= 0:
        return
    _safe_put(
        cn,
        activity_type=ActivityType.todo,
        activity_id=tid,
        from_state=State.parked,
        to_state=State.open,
        reason=Reason.unpark,
        desk_id=did,
        role="actor",
        join_key=join_key(tid),
        meta=_meta(fixture),
    )


def emit_claim(
    cn,
    *,
    todo_id: int,
    desk_id: int,
    take_over: bool = False,
    fixture: bool = False,
) -> None:
    """T4 claim or T6 take_over (claimed->claimed)."""
    tid, did = int(todo_id), int(desk_id)
    if tid <= 0 or did <= 0:
        return
    if take_over:
        _safe_put(
            cn,
            activity_type=ActivityType.todo,
            activity_id=tid,
            from_state=State.claimed,
            to_state=State.claimed,
            reason=Reason.take_over,
            desk_id=did,
            role="actor",
            join_key=join_key(tid),
            meta=_meta(fixture),
        )
    else:
        _safe_put(
            cn,
            activity_type=ActivityType.todo,
            activity_id=tid,
            from_state=State.open,
            to_state=State.claimed,
            reason=Reason.claim,
            desk_id=did,
            role="actor",
            join_key=join_key(tid),
            meta=_meta(fixture),
        )


def emit_unclaim(cn, *, todo_id: int, desk_id: int, fixture: bool = False) -> None:
    tid, did = int(todo_id), int(desk_id)
    if tid <= 0 or did <= 0:
        return
    _safe_put(
        cn,
        activity_type=ActivityType.todo,
        activity_id=tid,
        from_state=State.claimed,
        to_state=State.open,
        reason=Reason.unclaim,
        desk_id=did,
        role="actor",
        join_key=join_key(tid),
        meta=_meta(fixture),
    )


def emit_ship(cn, *, todo_id: int, desk_id: int, fixture: bool = False) -> None:
    tid, did = int(todo_id), int(desk_id)
    if tid <= 0 or did <= 0:
        return
    _safe_put(
        cn,
        activity_type=ActivityType.todo,
        activity_id=tid,
        from_state=State.claimed,
        to_state=State.shipped,
        reason=Reason.pass_ship,
        desk_id=did,
        role="actor",
        join_key=join_key(tid),
        meta=_meta(fixture),
    )


def emit_done(cn, *, todo_id: int, desk_id: int, fixture: bool = False) -> None:
    tid, did = int(todo_id), int(desk_id)
    if tid <= 0 or did <= 0:
        return
    _safe_put(
        cn,
        activity_type=ActivityType.todo,
        activity_id=tid,
        from_state=State.shipped,
        to_state=State.done,
        reason=Reason.pass_done,
        desk_id=did,
        role="actor",
        join_key=join_key(tid),
        meta=_meta(fixture),
    )


def emit_pass_back(
    cn,
    *,
    todo_id: int,
    desk_id: int,
    from_state: State,
    to_state: State,
    fixture: bool = False,
) -> None:
    """T10/T11 pass --back."""
    tid, did = int(todo_id), int(desk_id)
    if tid <= 0 or did <= 0:
        return
    if (from_state, to_state) not in (
        (State.done, State.shipped),
        (State.shipped, State.claimed),
        (State.shipped, State.open),
    ):
        return
    _safe_put(
        cn,
        activity_type=ActivityType.todo,
        activity_id=tid,
        from_state=from_state,
        to_state=to_state,
        reason=Reason.pass_back,
        desk_id=did,
        role="actor",
        join_key=join_key(tid),
        meta=_meta(fixture),
    )


def emit_retire(cn, *, todo_id: int, desk_id: int, fixture: bool = False) -> None:
    tid, did = int(todo_id), int(desk_id)
    if tid <= 0 or did <= 0:
        return
    _safe_put(
        cn,
        activity_type=ActivityType.todo,
        activity_id=tid,
        from_state=State.any,
        to_state=State.retired,
        reason=Reason.retire,
        desk_id=did,
        role="actor",
        join_key=join_key(tid),
        meta=_meta(fixture),
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
                " FROM transition WHERE activity_type='todo' ORDER BY id"
            )
        else:
            # Per-desk history: cards this desk touched (any event), full card timeline.
            cur.execute(
                "SELECT id, activity_id, from_state, to_state, reason, desk_id, join_key, at, meta"
                " FROM transition WHERE activity_type='todo' AND activity_id IN ("
                "  SELECT DISTINCT activity_id FROM transition"
                "  WHERE activity_type='todo' AND desk_id=%s"
                ") ORDER BY id",
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


def _is_fx(meta) -> bool:
    if meta is None:
        return False
    if isinstance(meta, (bytes, bytearray)):
        meta = meta.decode()
    if isinstance(meta, str):
        try:
            import json

            meta = json.loads(meta)
        except Exception:
            return '"fx": 1' in meta or '"fx":1' in meta
    if isinstance(meta, dict):
        return int(meta.get("fx") or 0) == 1
    return False


def score_view(cn, desk_id: int | None = None) -> dict[str, Any]:
    """Flow medians/worst, open/claimed counts and ages. Fixtures (meta.fx) omitted."""
    rows = _fetch(cn, desk_id)
    by_card: dict[int, list[dict[str, Any]]] = {}
    for r in rows:
        jk = str(r.get("join_key") or "")
        if not jk.startswith("card:"):
            continue
        aid = int(r.get("activity_id") or 0)
        if aid <= 0:
            continue
        by_card.setdefault(aid, []).append(r)

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    open_to_claim: list[float] = []
    claim_to_ship: list[float] = []
    ship_to_done: list[float] = []
    open_ages: list[float] = []
    claimed_ages: list[float] = []
    open_n = 0
    claimed_n = 0

    for _aid, events in by_card.items():
        if any(_is_fx(e.get("meta")) for e in events):
            continue
        open_at = None
        claim_at = None
        ship_at = None
        done_at = None
        last_state = None
        last_at = None
        for e in events:
            to = str(e.get("to_state") or "")
            reason = str(e.get("reason") or "")
            at = e.get("at")
            if to == "retired":
                last_state = "retired"
                last_at = at
                continue
            if to == "open" and open_at is None and reason in ("create", "unpark", "unclaim", "pass_back"):
                open_at = at
            if to == "open":
                last_state, last_at = "open", at
                if reason in ("create", "unpark") and open_at is None:
                    open_at = at
            if to == "claimed":
                if claim_at is None:
                    claim_at = at
                last_state, last_at = "claimed", at
            if to == "shipped":
                if ship_at is None:
                    ship_at = at
                last_state, last_at = "shipped", at
            if to == "done":
                if done_at is None:
                    done_at = at
                last_state, last_at = "done", at
            if to == "parked":
                last_state, last_at = "parked", at

        if open_at is not None and claim_at is not None:
            ms = _ms(open_at, claim_at)
            if ms is not None:
                open_to_claim.append(ms)
        if claim_at is not None and ship_at is not None:
            ms = _ms(claim_at, ship_at)
            if ms is not None:
                claim_to_ship.append(ms)
        if ship_at is not None and done_at is not None:
            ms = _ms(ship_at, done_at)
            if ms is not None:
                ship_to_done.append(ms)

        if last_state == "open" and last_at is not None:
            open_n += 1
            ms = _ms(last_at, now)
            if ms is not None:
                open_ages.append(ms)
        elif last_state == "claimed" and last_at is not None:
            claimed_n += 1
            ms = _ms(last_at, now)
            if ms is not None:
                claimed_ages.append(ms)

    out: dict[str, Any] = {"unit": "todo"}
    for key, vals in (
        ("open_to_claim_ms", open_to_claim),
        ("claim_to_ship_ms", claim_to_ship),
        ("ship_to_done_ms", ship_to_done),
        ("open_age_ms", open_ages),
        ("claimed_age_ms", claimed_ages),
    ):
        s = _summary(vals)
        if s is not None:
            out[key] = s
    if open_n or claimed_n or open_to_claim or claim_to_ship or ship_to_done:
        out["open_n"] = _count(open_n)
        out["claimed_n"] = _count(claimed_n)
    return out


def score_view_for_name(cn, name: str, desk_id: int | None = None) -> dict[str, Any]:
    view = score_view(cn, desk_id=desk_id)
    key = {
        KPI_OPEN_TO_CLAIM: "open_to_claim_ms",
        "open-cards-open-to-claim": "open_to_claim_ms",
        KPI_CLAIM_TO_SHIP: "claim_to_ship_ms",
        "open-cards-claim-to-ship": "claim_to_ship_ms",
        KPI_SHIP_TO_DONE: "ship_to_done_ms",
        "open-cards-ship-to-done": "ship_to_done_ms",
        KPI_OPEN_AGE: "open_age_ms",
        "open-cards-open-age": "open_age_ms",
        KPI_CLAIMED_AGE: "claimed_age_ms",
        "open-cards-claimed-age": "claimed_age_ms",
        KPI_OPEN_N: "open_n",
        "open-cards-open-n": "open_n",
        KPI_CLAIMED_N: "claimed_n",
        "open-cards-claimed-n": "claimed_n",
    }.get(name)
    if not key:
        return {}
    part = view.get(key)
    if part is None:
        return {"score": name, "missing": True}
    return {"score": name, **part}
