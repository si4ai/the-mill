"""Activity rows for mail, todo, join, hold, and score. A watcher watches one activity."""

from __future__ import annotations

import json

from .db import call
from agent_coord.helpers.ident import iso6


def _nm(value) -> str:
    return str(value or "").strip()



def heartbeat_interval(lease_s: int | float) -> float:
    """One third of the lease, at least 5 seconds."""
    return max(5.0, float(lease_s) / 3.0)


def select(cn, desk_id: int | None = None, limit: int = 10) -> list[dict]:
    return call(cn, "mill_activity_select", [desk_id or 0, limit])


def get(cn, type_s: str, ident: int) -> dict | None:
    """One activity row by (type, id): created, updated, state. None if absent."""
    rows = call(cn, "mill_activity_get", [str(type_s or ""), int(ident or 0)])
    return rows[0] if rows else None


def bucket(
    cn,
    project: str,
    desk_id: int | None = None,
    type_s: str = "",
    since=None,
    bucket: str = "hour",
) -> list[dict]:
    return call(
        cn,
        "mill_activity_bucket",
        [project, desk_id or 0, type_s or "", since, bucket or "hour"],
    )


# Card 1160: bucket start without DATE_FORMAT, so the query text has no percent
# sign for the connector to escape. Each start is a naive book-clock DATETIME(6).
_BUCKET_START = {
    "min": "DATE_ADD(DATE(a.updated), INTERVAL HOUR(a.updated) * 60 + MINUTE(a.updated) MINUTE)",
    "hour": "DATE_ADD(DATE(a.updated), INTERVAL HOUR(a.updated) HOUR)",
    "day": "DATE(a.updated)",
}
# Default look-back per bucket when since is not given, in seconds of book clock.
BUCKET_SINCE_S = {"min": 6 * 3600, "hour": 2 * 86400, "day": 7 * 86400}


def buckets(
    cn,
    roster: str,
    grain: str,
    since=None,
    type_s: str = "",
    act: str = "",
) -> list[dict]:
    """Activity item counts per (bucket start, type, act, desk) on one roster.

    grain is min, hour or day. since is a naive book-clock time; None means
    BUCKET_SINCE_S[grain] before MILL_NOW(). type_s and act narrow the rows when set.
    Read-only: one SELECT on activity and name.
    """
    start = _BUCKET_START[grain]
    sql = (
        "SELECT CAST(" + start + " AS DATETIME(6)) AS updated, a.type, a.act, a.desk_id,"
        " COUNT(*) AS items, ANY_VALUE(dn.name) AS desk, ANY_VALUE(an.name) AS roster"
        " FROM activity a"
        " LEFT JOIN name dn ON dn.id = a.desk_id"
        " LEFT JOIN name an ON an.id = a.roster_id"
        " WHERE a.roster_id = MILL_NAME_GET('roster', %s)"
        " AND a.updated >= IFNULL(%s, DATE_SUB(MILL_NOW(), INTERVAL %s SECOND))"
        " AND (%s = '' OR a.type = %s)"
        " AND (%s = '' OR a.act = %s)"
        " GROUP BY 1, a.type, a.act, a.desk_id"
        " ORDER BY 1, a.type, a.act, a.desk_id"
    )
    args = (roster, since, BUCKET_SINCE_S[grain], type_s, type_s, act, act)
    cur = cn.cursor(dictionary=True)
    try:
        cur.execute(sql, args)
        raw = list(cur.fetchall())
    finally:
        cur.close()
    return [
        {
            "updated": iso6(r.get("updated")),
            "type": r.get("type"),
            "act": r.get("act") or "",
            "desk": _nm(r.get("desk")),
            "desk_id": r.get("desk_id"),
            "roster": _nm(r.get("roster")),
            "items": int(r.get("items") or 0),
        }
        for r in raw
    ]


def span(cn, kind: str, ident: str, grain: str) -> list[dict]:
    """min reads activity. hour and day read that desk's system score rollup."""
    return call(cn, "mill_span", [kind, ident, grain])


def between(cn, kind: str, ident: str, limit: int = 50) -> list[dict]:
    """Latest activity rows per desk in one project, role, or station."""
    return call(cn, "mill_between", [kind, ident, int(limit)])


def _doc(value):
    if isinstance(value, (bytes, bytearray)):
        value = value.decode()
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def span_rows(cn, kind: str, ident: str, grain: str) -> tuple[str, list[dict]]:
    """Rows for one scope. min matches the activity bucket shape. hour and day carry the JSON document."""
    raw = span(cn, kind, ident, grain)
    if grain == "min":
        out = []
        for r in raw:
            row = {
                "updated": iso6(r.get("updated")),
                "type": r.get("type"),
                "desk_id": r.get("desk_id"),
                "owner": _nm(r.get("desk") or ""),
                "roster_id": _nm(r.get("roster") or ""),
                "items": int(r.get("items") or 0),
            }
            row["id"] = "|".join(
                str(row.get(k) or "")
                for k in ("updated", "type", "desk_id", "owner", "roster_id")
            )
            out.append(row)
        return "activity", out
    out = []
    for r in raw:
        stamp = iso6(r.get("timestamp"))
        desk_id = r.get("desk_id")
        row = {
            "desk_id": desk_id,
            "owner": _nm(r.get("desk") or ""),
            "timestamp": stamp,
            "taken": iso6(r.get("taken"))[:10],
            "value": _doc(r.get("value")),
        }
        row["id"] = f"{desk_id}|{stamp}"
        out.append(row)
    return "score_evidence", out


def between_rows(cn, kind: str, ident: str, limit: int = 50) -> list[dict]:
    """One scope's latest rows. id is the mail, todo, hold, join, or score id.

    A letter is one row per recipient. other is that desk. A card's other is the
    assignee, or the creator when this row is already the assignee. Join, score,
    and hold leave other empty. state is deleted (any type), sent (live letter),
    or None.
    """
    out = []
    for r in between(cn, kind, ident, limit):
        other_id = r.get("other_desk_id")
        other = _nm(r.get("other_desk") or "")
        out.append(
            {
                "updated": iso6(r.get("updated")),
                "type": r.get("type"),
                "id": r.get("id"),
                "desk_id": r.get("desk_id"),
                "owner": _nm(r.get("desk") or ""),
                "roster_id": _nm(r.get("roster") or ""),
                "items": int(r.get("items") or 0),
                "other_desk_id": other_id,
                "other": other or None,
                "state": r.get("state"),
            }
        )
    return out
