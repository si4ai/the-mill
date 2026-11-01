"""Card 980: mail feature transitions + score views (no new schema).

Emits into shared `transition` via mill_transition_put. Meta carries only
small tokens (counts/flags) - never bodies, names, or hosts.
"""
from __future__ import annotations

import statistics
from typing import Any

from agent_coord.server import transition as tr
from agent_coord.server.transition_enums import ActivityType, Reason, State

KPI_SEND_WAKE = "mail.send_to_wake_ms"
KPI_WAKE_ANSWER = "mail.wake_to_answer_ms"
KPI_RE_RINGS = "mail.re_rings_n"
KPI_NEVER = "mail.never_answered_n"

SCORE_NAMES = {
    KPI_SEND_WAKE,
    KPI_WAKE_ANSWER,
    KPI_RE_RINGS,
    KPI_NEVER,
    "send-to-wake",
    "wake-to-answer",
    "re-rings",
    "never-answered",
}


def join_key(mail_id: int, desk_id: int) -> str:
    return f"letter:{int(mail_id)}:{int(desk_id)}"


def _safe_put(cn, **kw) -> None:
    try:
        tr.put(cn, **kw)
    except Exception:
        # Instrumentation must not break mail. Unknown edges / SP gaps stay soft.
        pass


def emit_send(
    cn,
    *,
    mail_id: int,
    sender_desk_id: int,
    recipient_desk_ids: list[int],
) -> None:
    """M1 sender live + M1r recipient unread (join_key per recipient)."""
    mid = int(mail_id)
    sid = int(sender_desk_id)
    _safe_put(
        cn,
        activity_type=ActivityType.mail,
        activity_id=mid,
        from_state=State.none,
        to_state=State.live,
        reason=Reason.send_or_queue,
        desk_id=sid,
        role="sender",
        join_key=join_key(mid, sid),
        meta={"n_recipients": len(recipient_desk_ids)},
    )
    for rid in recipient_desk_ids:
        rid = int(rid)
        if rid <= 0:
            continue
        _safe_put(
            cn,
            activity_type=ActivityType.mail,
            activity_id=mid,
            from_state=State.none,
            to_state=State.unread,
            reason=Reason.send_or_queue,
            desk_id=rid,
            role="recipient",
            join_key=join_key(mid, rid),
            meta=None,
        )


def emit_reply(
    cn,
    *,
    mail_id: int,
    parent_id: int,
    sender_desk_id: int,
    recipient_desk_ids: list[int],
) -> None:
    """M2 reply live + answered on the parent for the answering desk."""
    mid = int(mail_id)
    sid = int(sender_desk_id)
    _safe_put(
        cn,
        activity_type=ActivityType.mail,
        activity_id=mid,
        from_state=State.none,
        to_state=State.live,
        reason=Reason.reply,
        desk_id=sid,
        role="sender",
        join_key=join_key(mid, sid),
        meta={"n_recipients": len(recipient_desk_ids)},
    )
    for rid in recipient_desk_ids:
        rid = int(rid)
        if rid <= 0:
            continue
        _safe_put(
            cn,
            activity_type=ActivityType.mail,
            activity_id=mid,
            from_state=State.none,
            to_state=State.unread,
            reason=Reason.send_or_queue,
            desk_id=rid,
            role="recipient",
            join_key=join_key(mid, rid),
            meta=None,
        )
    emit_answered(cn, mail_id=int(parent_id), desk_id=sid)


def emit_mark(cn, *, mail_id: int, desk_id: int) -> None:
    """M3 unread -> handled."""
    mid = int(mail_id)
    did = int(desk_id)
    _safe_put(
        cn,
        activity_type=ActivityType.mail,
        activity_id=mid,
        from_state=State.unread,
        to_state=State.handled,
        reason=Reason.mark,
        desk_id=did,
        role="recipient",
        join_key=join_key(mid, did),
        meta=None,
    )


def emit_delivered(cn, *, mail_id: int, desk_id: int) -> None:
    """M10 live -> delivered."""
    mid = int(mail_id)
    did = int(desk_id)
    _safe_put(
        cn,
        activity_type=ActivityType.mail,
        activity_id=mid,
        from_state=State.live,
        to_state=State.delivered,
        reason=Reason.delivered,
        desk_id=did,
        role="recipient",
        join_key=join_key(mid, did),
        meta=None,
    )


def emit_woken(cn, *, mail_id: int, desk_id: int) -> None:
    """M11 delivered -> woken (re-rings reuse the same edge)."""
    mid = int(mail_id)
    did = int(desk_id)
    _safe_put(
        cn,
        activity_type=ActivityType.mail,
        activity_id=mid,
        from_state=State.delivered,
        to_state=State.woken,
        reason=Reason.woken,
        desk_id=did,
        role="recipient",
        join_key=join_key(mid, did),
        meta=None,
    )


def emit_answered(cn, *, mail_id: int, desk_id: int) -> None:
    """M12b unread -> answered (covers reply before mark)."""
    mid = int(mail_id)
    did = int(desk_id)
    _safe_put(
        cn,
        activity_type=ActivityType.mail,
        activity_id=mid,
        from_state=State.unread,
        to_state=State.answered,
        reason=Reason.answered,
        desk_id=did,
        role="actor",
        join_key=join_key(mid, did),
        meta=None,
    )


def _fetch(cn, desk_id: int | None) -> list[dict[str, Any]]:
    cur = cn.cursor(dictionary=True)
    try:
        if desk_id is None or int(desk_id) <= 0:
            cur.execute(
                "SELECT id, activity_id, from_state, to_state, reason, desk_id, join_key, at"
                " FROM transition WHERE activity_type='mail' ORDER BY id"
            )
        else:
            cur.execute(
                "SELECT id, activity_id, from_state, to_state, reason, desk_id, join_key, at"
                " FROM transition WHERE activity_type='mail' AND desk_id=%s ORDER BY id",
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


def score_view(cn, desk_id: int | None = None) -> dict[str, Any]:
    """Median + worst latencies, re-rings, never-answered from transition rows.

    Empty samples are omitted (card 1019), not published as 0.
    """
    rows = _fetch(cn, desk_id)
    by_key: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        jk = str(r.get("join_key") or "")
        if not jk.startswith("letter:"):
            continue
        by_key.setdefault(jk, []).append(r)

    send_wake: list[float] = []
    wake_answer: list[float] = []
    re_rings = 0
    never = 0

    for jk, events in by_key.items():
        first_in = None
        woken_times: list = []
        answered_at = None
        for e in events:
            to = str(e.get("to_state") or "")
            at = e.get("at")
            if to in ("live", "unread", "delivered") and first_in is None:
                first_in = at
            if to == "woken":
                woken_times.append(at)
            if to == "answered" and answered_at is None:
                answered_at = at
        if woken_times:
            if len(woken_times) > 1:
                re_rings += len(woken_times) - 1
            ms = _ms(first_in, woken_times[0])
            if ms is not None:
                send_wake.append(ms)
            if answered_at is not None:
                ms2 = _ms(woken_times[0], answered_at)
                if ms2 is not None:
                    wake_answer.append(ms2)
            else:
                never += 1
        elif first_in is not None and answered_at is None:
            # delivered/unread with no wake and no answer
            if any(str(e.get("to_state")) in ("delivered", "unread", "live") for e in events):
                never += 1

    out: dict[str, Any] = {"unit": "mail"}
    sw = _summary(send_wake)
    if sw is not None:
        out["send_to_wake_ms"] = sw
    wa = _summary(wake_answer)
    if wa is not None:
        out["wake_to_answer_ms"] = wa
    if re_rings > 0:
        out["re_rings"] = {"n": re_rings, "unit": "count"}
    elif re_rings == 0 and send_wake:
        # measured zero re-rings when we had wakes
        out["re_rings"] = {"n": 0, "unit": "count"}
    if never > 0:
        out["never_answered"] = {"n": never, "unit": "count"}
    elif send_wake or wake_answer:
        out["never_answered"] = {"n": 0, "unit": "count"}
    return out


def score_view_for_name(cn, name: str, desk_id: int | None = None) -> dict[str, Any]:
    """Shape one KPI for mill score NAME."""
    view = score_view(cn, desk_id=desk_id)
    key = {
        KPI_SEND_WAKE: "send_to_wake_ms",
        "send-to-wake": "send_to_wake_ms",
        KPI_WAKE_ANSWER: "wake_to_answer_ms",
        "wake-to-answer": "wake_to_answer_ms",
        KPI_RE_RINGS: "re_rings",
        "re-rings": "re_rings",
        KPI_NEVER: "never_answered",
        "never-answered": "never_answered",
    }.get(name)
    if not key:
        return {}
    part = view.get(key)
    if part is None:
        return {"score": name, "missing": True}
    out = {"score": name, **part}
    return out


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
