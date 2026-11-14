# -*- coding: utf-8 -*-
"""probe-delete: test-only soft delete of a desk's own fixture rows (#160).

Not a skill.md command and not a mill subcommand. tools/probe_deleted_rows.py
calls it over the sitting connect so a checker can make a deleted todo or
score row live and confirm state=deleted end to end (/api/v1/events,
mill_activity_select, mill_between, the Wall pill).

Guards, all checked before any write:
  - type is todo or score, id is a positive integer
  - the row's roster is a project named t-<8 hex> (a fixture project)
  - the calling desk made the row (todo creator, score desk)
Anything else is refused and nothing changes. The delete reuses the existing
soft-delete procedures (mill_todo_delete, mill_score_delete); no new SQL.
"""
from __future__ import annotations

from typing import Any

from agent_coord.const import CONST_ROSTER
from agent_coord.helpers.errors import CoordError
from agent_coord.lib.observe import is_fixture_project

COMMAND = "probe-delete"
TYPES = ("todo", "score")


def _nm(value: Any) -> str:
    return str(value or "").strip()


def _same(a: Any, b: Any) -> bool:
    # name collation is case-insensitive; compare the same way.
    return bool(_nm(a)) and _nm(a).lower() == _nm(b).lower()


def _target(body: dict[str, Any]) -> tuple[str, int]:
    typ = _nm(body.get("type") or body.get("kind")).lower()
    if typ not in TYPES:
        raise CoordError("probe-delete: type must be todo or score")
    raw = _nm(body.get("id"))
    try:
        rid = int(raw)
    except ValueError:
        rid = 0
    if rid <= 0:
        raise CoordError("probe-delete: id must be a positive integer")
    return typ, rid


def _activity_deleted(cn, typ: str, rid: int):
    from agent_coord.server.records.db import scalar

    return scalar(cn, "SELECT deleted FROM activity WHERE type = %s AND id = %s", (typ, rid))


def _todo_row(cn, rid: int) -> dict[str, Any] | None:
    from agent_coord.server.records import todo as rec_todo

    rows = rec_todo.get(cn, rid) or []
    if not rows:
        return None
    r = rows[0]
    return {
        "roster": r.get("roster"),
        "roster_type": r.get("roster_type"),
        "maker": r.get("creator"),
    }


def _score_row(cn, rid: int) -> dict[str, Any] | None:
    cur = cn.cursor(dictionary=True)
    try:
        cur.execute(
            # A roster-owned series (#288) was made by the desk of its first point.
            "SELECT an.name AS roster, an.type AS roster_type,"
            " COALESCE((SELECT pn.name FROM score_point sp JOIN name pn ON pn.id = sp.desk_id"
            " WHERE sp.score_id = s.id ORDER BY sp.id LIMIT 1), dn.name) AS maker"
            " FROM score s"
            " LEFT JOIN activity act ON act.type = 'score' AND act.id = s.id"
            " LEFT JOIN name an ON an.id = act.roster_id"
            " LEFT JOIN name dn ON dn.id = s.desk_id"
            " WHERE s.id = %s",
            (rid,),
        )
        row = cur.fetchone()
    finally:
        cur.close()
    return dict(row) if row else None


def check(cn, typ: str, rid: int, owner: str) -> dict[str, Any]:
    """Row facts when the caller may probe-delete it. CoordError otherwise. Read only."""
    if not _nm(owner):
        raise CoordError("probe-delete: owner required")
    row = _todo_row(cn, rid) if typ == "todo" else _score_row(cn, rid)
    if row is None:
        if _activity_deleted(cn, typ, rid) is not None:
            raise CoordError(f"probe-delete: {typ} {rid} is already deleted")
        raise CoordError(f"probe-delete: no such {typ} {rid}")
    aff = _nm(row.get("roster"))
    if _nm(row.get("roster_type")) != CONST_ROSTER or not is_fixture_project(aff):
        raise CoordError(
            f"probe-delete: {typ} {rid} is not in a fixture project (t-<8 hex>); refused"
        )
    if not _same(row.get("maker"), owner):
        raise CoordError(f"probe-delete: {typ} {rid} was not made by this desk; refused")
    if typ == "score" and _activity_deleted(cn, typ, rid) is not None:
        raise CoordError(f"probe-delete: {typ} {rid} is already deleted")
    return {"type": typ, "id": rid, "project": aff}


def handle(c, body: dict[str, Any], project: str, owner: str | None) -> dict[str, Any]:
    from agent_coord.helpers.ident import iso6
    from agent_coord.server.records import score as rec_score
    from agent_coord.server.records import todo as rec_todo

    del project  # the row's own roster decides, not the body
    typ, rid = _target(body)
    facts = check(c._cn, typ, rid, owner or "")
    # The delete procedure drops watchers. Read them first so the hint still goes out.
    watchers = None
    try:
        from agent_coord.server.records import watcher as rec_w

        watchers = list(rec_w.select(c._cn, typ, rid) or [])
    except Exception:
        watchers = None
    if typ == "todo":
        rec_todo.delete(c._cn, rid, _nm(owner))
    else:
        rec_score.delete(c._cn, rid, _nm(owner))
    gone = _activity_deleted(c._cn, typ, rid)
    facts["state"] = "deleted" if gone is not None else "unchanged"
    facts["deleted"] = iso6(gone) if gone is not None else None
    if facts["state"] == "deleted":
        # A hard activity delete drops watcher rows (activity_del_watchers).
        # The caller still gets the one deleted hint (#185).
        if not watchers:
            watchers = [{"desk": _nm(owner), "delivery_mode": "polling"}]
        try:
            from agent_coord.server.push import fanout

            fanout(c._cn, typ, rid, typ.upper(), rows=watchers)
        except Exception:
            pass
    return facts
