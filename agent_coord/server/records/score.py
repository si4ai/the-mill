"""SCORE - KPI Last/Target. Update = presence type=score."""

from __future__ import annotations

from agent_coord.const import CONST_DESK, CONST_ROSTER
from .db import call


def upsert(
    cn,
    project: str,
    desk: str,
    kpi: str,
    value: str = "",
    target: str = "",
    note: str = "",
) -> list[dict]:
    from agent_coord.server.records.name import bare

    return call(
        cn,
        "mill_score_upsert",
        [bare(project, CONST_ROSTER), bare(desk, CONST_DESK), kpi, value, target, note],
    )


def admin_upsert(cn, kpi: str, value: str = "", target: str = "", note: str = "") -> list[dict]:
    """Office host score with no desk (mill_score_admin_upsert, desk_id NULL). No watcher."""
    return call(cn, "mill_score_admin_upsert", [kpi, value, target, note])


def delete(cn, score_id: int, desk: str) -> list[dict]:
    """Soft-delete: mill_score_delete(p_id, p_desk) keeps the card and stamps activity.deleted."""
    from agent_coord.server.records.name import bare
    from agent_coord.helpers.errors import CoordError

    desk_b = bare(desk, CONST_DESK) if desk else ""
    if not desk_b:
        raise CoordError("score delete: desk required")
    return call(cn, "mill_score_delete", [score_id, desk_b])


def select_rosters(cn, names: list[str]) -> list[tuple[str, dict]]:
    """mill_score_select for many projects/roles in one read: [(requested name, score row)].

    Ids resolved once (name.roster_ids), then one IN (...) read with the
    mill_score_select row shape. Input name order, then updated DESC. None resolved -> [].
    """
    from agent_coord.server.records.name import roster_ids

    pairs = roster_ids(cn, names)
    if not pairs:
        return []
    ids = [aid for _n, aid in pairs]
    marks = ",".join(["%s"] * len(ids))
    cur = cn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT s.type, s.id, s.created, s.updated, s.desk_id, s.roster_id, s.kpi,"
            " s.value, s.target, s.note,"
            " dn.name AS desk, dn.type AS desk_type, an.name AS roster, an.type AS roster_type"
            " FROM score s"
            " LEFT JOIN name dn ON dn.id = s.desk_id"
            " LEFT JOIN name an ON an.id = s.roster_id"
            " WHERE s.roster_id IN (" + marks + ")"
            " ORDER BY s.updated DESC",
            tuple(ids),
        )
        rows = list(cur.fetchall())
    finally:
        cur.close()
    by_aff: dict[int, list[dict]] = {}
    for r in rows:
        by_aff.setdefault(int(r.get("roster_id") or 0), []).append(r)
    return [(name, r) for name, aid in pairs for r in by_aff.get(aid, [])]


def select(cn, project: str) -> list[dict]:
    from agent_coord.server.records.name import roster_name

    return call(cn, "mill_score_select", [roster_name(project) if project else ""])


def point_add(
    cn,
    project: str,
    desk: str,
    kpi: str,
    value: float,
    *,
    target: str | None = None,
    note: str = "",
    better: str | None = None,
    unit: str | None = None,
    at: str | None = None,
) -> list[dict]:
    """#288: one numeric point on the roster's series (mill_score_point_add); at = --at (#308)."""
    from agent_coord.server.records.name import bare

    return call(
        cn,
        "mill_score_point_add",
        [bare(project, CONST_ROSTER), bare(desk, CONST_DESK), kpi, float(value), target, note, better, unit, at],
    )


def define(
    cn,
    project: str,
    desk: str,
    kpi: str,
    *,
    target: str | None = None,
    better: str | None = None,
    unit: str | None = None,
) -> list[dict]:
    """#306: set target, better or unit without a point (mill_score_define)."""
    from agent_coord.server.records.name import bare

    return call(
        cn,
        "mill_score_define",
        [bare(project, CONST_ROSTER), bare(desk, CONST_DESK), kpi, target, better, unit],
    )


def retire(cn, project: str, desk: str, kpi: str, *, admin: bool = False) -> list[dict]:
    """#302: soft-delete the score a read of kpi returns (mill_score_retire). Points stay."""
    from agent_coord.server.records.name import bare

    return call(
        cn,
        "mill_score_retire",
        [bare(project, CONST_ROSTER), bare(desk, CONST_DESK), kpi, 1 if admin else 0],
    )


def points(cn, project: str, kpi: str = "", limit: int = 10) -> list[dict]:
    """#288 step 1: one score and its newest points, or every score on the roster (kpi '')."""
    from agent_coord.server.records.name import bare

    return call(cn, "mill_score_points", [bare(project, CONST_ROSTER), kpi, int(limit)])


def cards_day_evidence(cn, project: str, when=None) -> dict | None:
    """Today's day rollup for the roster's cards score (card 955), or None."""
    from datetime import datetime

    from agent_coord.server.records.name import bare

    roster = bare(project, CONST_ROSTER)
    day = (when or datetime.now()).strftime("%Y-%m-%d 00:00:00")
    cur = cn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT e.value FROM score s"
            " JOIN name r ON r.id = s.roster_id AND r.name = %s"
            " JOIN score_evidence e ON e.score_id = s.id AND e.`timestamp` = %s"
            " WHERE s.kpi = 'cards' AND s.desk_id IS NULL LIMIT 1",
            (roster, day),
        )
        row = cur.fetchone()
    finally:
        cur.close()
    if not row:
        return None
    import json

    value = row.get("value")
    if isinstance(value, (bytes, bytearray)):
        value = value.decode()
    if isinstance(value, str):
        return json.loads(value)
    return value if isinstance(value, dict) else None


def system_commands_today(cn, desk: str, when=None) -> int | None:
    """Commands-used today for a desk from the system score evidence (card 955)."""
    from datetime import datetime

    from agent_coord.server.records.name import bare

    d = bare(desk, CONST_DESK) if desk else ""
    if not d:
        return None
    day = (when or datetime.now()).strftime("%Y-%m-%d 00:00:00")
    cur = cn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT e.value FROM score s"
            " JOIN name n ON n.id = s.desk_id AND n.name = %s"
            " JOIN score_evidence e ON e.score_id = s.id AND e.`timestamp` = %s"
            " WHERE s.kpi = 'system' LIMIT 1",
            (d, day),
        )
        row = cur.fetchone()
    finally:
        cur.close()
    if not row:
        return None
    import json

    value = row.get("value")
    if isinstance(value, (bytes, bytearray)):
        value = value.decode()
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        return None
    try:
        return int(value.get("n") or 0)
    except (TypeError, ValueError):
        return None
