"""Card 1212: part 1 attention scores, one read, roster rollup, no wakes.

GET /api/pov?part=scores&window=7d is the Wall read. It does not record a view.
A desk read passes viewer= and writes one score_view row per score (count and
last_seen), still with no hint and no wake.
"""
from __future__ import annotations

from typing import Any

SCORE_NAMES = (
    "oldest_unread_ask_age_ms",
    "unanswered_required_n",
    "unanswered_fyi_n",
    "ask_to_answer_ms",
    "outgoing_unanswered_n",
    "claimed_no_pass_age_ms",
    "claimed_age_ms",
    "claimed_claimant_inactive_n",
    "claimed_past_eta_n",
    "shipped_unaccepted_age_ms",
    "hold_open_age_ms",
    "force_taken_n",
    "stale_share",
    "ended_no_pass_or_mail_n",
    "to_done_ms",
    "stale_done_share",
    "hint_no_turn_n",
)

_ACTIVE_WAKE = ("wake_deliver", "wake_done")


def _window_sql(window: str) -> str:
    text = (window or "7d").strip().lower()
    if text.endswith("h") and text[:-1].isdigit():
        return f"INTERVAL {int(text[:-1])} HOUR"
    days = int(text[:-1]) if text.endswith("d") and text[:-1].isdigit() else 7
    return f"INTERVAL {days} DAY"


def _rows(cn, sql: str, args: tuple = ()) -> list[dict]:
    cur = cn.cursor(dictionary=True)
    try:
        cur.execute(sql, args)
        return list(cur.fetchall())
    finally:
        cur.close()


def active_desk_ids(cn, window: str) -> set[int]:
    """Desks with an actor transition, a wake take or wake-done, or a score read.

    A connect, a score point written about the desk, or a server wake_queue /
    wake_sent edge does not count.
    """
    span = _window_sql(window)
    rows = _rows(
        cn,
        "SELECT DISTINCT t.desk_id AS id FROM transition t "
        "WHERE t.desk_id <> 0 AND t.at >= NOW() - " + span + " AND ("
        " t.activity_type IN ('mail','todo','doing','hold')"
        " OR t.reason IN ('wake_deliver','wake_done'))",
    )
    ids = {int(r["id"]) for r in rows}
    try:
        views = _rows(
            cn,
            "SELECT viewer_id AS id FROM score_view WHERE last_seen >= NOW() - " + span,
        )
        ids.update(int(r["id"]) for r in views)
    except Exception:
        pass
    return ids


def _entry(name: str, window: str, value: Any, *, anchor: str = "", num: int | None = None,
           den: int | None = None, items: list | None = None, reason: str | None = None) -> dict:
    return {
        "name": name,
        "kind": "share" if den is not None else ("age" if name.endswith("_ms") else "count"),
        "owner": "desk",
        "value": value,
        "reason": reason,
        "anchor_at": anchor or None,
        "num": num,
        "den": den,
        "items": (items or [])[:5],
        "target": None,
        "window": window,
        "rollup": None,
    }


def _desk_scores(cn, desk_id: int, window: str, active: set[int]) -> list[dict]:
    span = _window_sql(window)
    scores = {name: _entry(name, window, None, reason="none") for name in SCORE_NAMES}

    unread = _rows(
        cn,
        "SELECT mt.id, mt.created FROM mail_to mt "
        "WHERE mt.type='mail' AND mt.desk_id=%s AND mt.asked=1 AND mt.opened IS NULL "
        "AND mt.created >= NOW() - " + span + " ORDER BY mt.created",
        (desk_id,),
    )
    if unread:
        scores["oldest_unread_ask_age_ms"] = _entry(
            "oldest_unread_ask_age_ms", window,
            None,
            anchor=str(unread[0]["created"])[:19],
            items=[int(r["id"]) for r in unread],
        )

    split = _rows(
        cn,
        "SELECT mt.receipt, COUNT(*) AS n FROM mail_to mt "
        "WHERE mt.type='mail' AND mt.desk_id=%s AND mt.asked=1 AND mt.opened IS NULL "
        "GROUP BY mt.receipt",
        (desk_id,),
    )
    for rec in split:
        key = "unanswered_fyi_n" if int(rec["receipt"] or 0) else "unanswered_required_n"
        scores[key] = _entry(key, window, int(rec["n"]))

    claims = _rows(
        cn,
        "SELECT t.id, t.at, t.activity_id FROM transition t "
        "WHERE t.desk_id=%s AND t.activity_type='todo' AND t.reason='claim' "
        "AND t.at >= NOW() - " + span + " ORDER BY t.at",
        (desk_id,),
    )
    if claims:
        scores["claimed_age_ms"] = _entry(
            "claimed_age_ms", window, None, anchor=str(claims[0]["at"])[:19],
            items=[int(r["activity_id"]) for r in claims],
        )
    edits = _rows(
        cn,
        "SELECT td.id, COALESCE(td.body_updated, td.updated) AS at FROM todo td "
        "WHERE td.assigned_id=%s AND td.status='claimed' ORDER BY at",
        (desk_id,),
    )
    if edits:
        scores["claimed_no_pass_age_ms"] = _entry(
            "claimed_no_pass_age_ms", window, None, anchor=str(edits[-1]["at"])[:19],
            items=[int(r["id"]) for r in edits],
        )

    holds = _rows(
        cn,
        "SELECT h.id, h.updated FROM hold h "
        "WHERE h.desk_id=%s ORDER BY h.updated",
        (desk_id,),
    )
    if holds:
        scores["hold_open_age_ms"] = _entry(
            "hold_open_age_ms", window, None, anchor=str(holds[0]["updated"])[:19],
            items=[int(r["id"]) for r in holds],
        )
    forced = _rows(
        cn,
        "SELECT COUNT(*) AS n FROM transition t "
        "WHERE t.desk_id=%s AND t.reason='hold_force'",
        (desk_id,),
    )
    scores["force_taken_n"] = _entry("force_taken_n", window, int(forced[0]["n"] or 0))

    stale = _rows(
        cn,
        "SELECT "
        "SUM(t.reason='wake_stale') AS num, "
        "SUM(t.reason IN ('wake_stale','wake_done','wake_expire')) AS den "
        "FROM transition t WHERE t.desk_id=%s AND t.at >= NOW() - " + span,
        (desk_id,),
    )
    num = int(stale[0]["num"] or 0)
    den = int(stale[0]["den"] or 0)
    scores["stale_share"] = _entry("stale_share", window, (num / den) if den else None, num=num, den=den)
    scores["stale_done_share"] = _entry("stale_done_share", window, (num / den) if den else None, num=num, den=den)
    scores["hint_no_turn_n"] = _entry("hint_no_turn_n", window, None, reason="new")
    if desk_id not in active:
        for row in scores.values():
            if row["reason"] is None and row["value"] is None and not row["anchor_at"]:
                row["reason"] = "inactive"
    return [scores[name] for name in SCORE_NAMES]


def _ensure_view_table(cn) -> None:
    return None


def read_scores(cn, window: str = "7d", viewer: str | None = None) -> dict[str, Any]:
    """Every active desk, each score, and a roster rollup. Wall reads pass no viewer."""
    _ensure_view_table(cn)
    window = (window or "7d").strip().lower() or "7d"
    active = active_desk_ids(cn, window)
    desks = _rows(cn, "SELECT id, name FROM name WHERE type='desk' ORDER BY name")
    by_roster = _rows(
        cn,
        "SELECT s.desk_id, n.name AS roster FROM seat s "
        "JOIN member m ON m.desk_id=s.desk_id "
        "JOIN name n ON n.id=m.name_id AND n.type='roster'",
    )
    roster_of = {int(r["desk_id"]): str(r["roster"]) for r in by_roster}
    out_desks = []
    values_by_name: dict[str, list[float]] = {n: [] for n in SCORE_NAMES}
    for desk in desks:
        did = int(desk["id"])
        if did not in active:
            continue
        rows = _desk_scores(cn, did, window, active)
        for row in rows:
            if isinstance(row["value"], (int, float)):
                values_by_name[row["name"]].append(float(row["value"]))
        out_desks.append({
            "desk": str(desk["name"]),
            "roster": roster_of.get(did, ""),
            "scores": rows,
        })
    n_active = len(out_desks)
    for desk in out_desks:
        for row in desk["scores"]:
            series = values_by_name[row["name"]]
            median = None
            if n_active >= 3 and series:
                ordered = sorted(series)
                median = ordered[len(ordered) // 2]
            row["rollup"] = {"median": median, "n_active": n_active, "window": window}
    if viewer:
        _record_views(cn, viewer, SCORE_NAMES)
    return {"window": window, "desks": out_desks, "unviewed": _unviewed(cn, window)}


def _record_views(cn, viewer: str, names: tuple[str, ...]) -> None:
    rows = _rows(cn, "SELECT id FROM name WHERE type='desk' AND name=%s", (viewer,))
    if not rows:
        return
    vid = int(rows[0]["id"])
    cur = cn.cursor()
    try:
        for name in names:
            cur.execute(
                "INSERT INTO score (desk_id, kpi) VALUES (%s, %s) "
                "ON DUPLICATE KEY UPDATE updated = updated",
                (vid, name),
            )
            cur.execute("SELECT id FROM score WHERE desk_id=%s AND kpi=%s", (vid, name))
            sid = int(cur.fetchone()[0])
            cur.execute(
                "INSERT INTO score_view (score_id, viewer_id, n, last_seen) VALUES (%s, %s, 1, NOW()) "
                "ON DUPLICATE KEY UPDATE n = n + 1, last_seen = NOW()",
                (sid, vid),
            )
        cn.commit()
    finally:
        cur.close()


def _unviewed(cn, window: str) -> list[str]:
    span = _window_sql(window)
    try:
        seen = {str(r["kpi"]) for r in _rows(
            cn,
            "SELECT DISTINCT s.kpi FROM score_view v JOIN score s ON s.id = v.score_id "
            "WHERE v.last_seen >= NOW() - " + span,
        )}
    except Exception:
        seen = set()
    return [name for name in SCORE_NAMES if name not in seen]
