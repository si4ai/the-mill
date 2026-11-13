"""Cards 1205 and 1206: the Wall COLLAB replay, keyset pages with edges on each row.

The page is the transition log. `id < before ORDER BY id DESC LIMIT N` is a
primary-key seek. Mail recipients come from mail_to for that letter, not from
the newest 500 mailbox rows. A before= page is immutable; the head page is short.
"""
from __future__ import annotations

import hashlib
from typing import Any

REPLAY_DEFAULT = 100
REPLAY_CAP = 1000
_MOVE_ACTS = ("claim", "assign", "unclaim", "ship", "done", "replace")
_ENDED = ("finished", "failed", "cleared")


def parse_replay_page(qs: dict[str, list[str]] | None) -> tuple[int, int | None, int | None]:
    """limit (1..1000, default 100), before id, after id."""
    qs = qs or {}
    raw = str((qs.get("limit") or ["100"])[0] or "").strip()
    try:
        limit = int(raw) if raw else REPLAY_DEFAULT
    except (TypeError, ValueError):
        limit = REPLAY_DEFAULT
    if limit < 1:
        limit = 1
    if limit > REPLAY_CAP:
        limit = REPLAY_CAP

    def _one(name: str) -> int | None:
        text = str((qs.get(name) or [""])[0] or "").strip()
        if not text:
            return None
        try:
            return int(text)
        except (TypeError, ValueError):
            return None

    return limit, _one("before"), _one("after")


def cache_headers(payload: dict[str, Any], *, before: int | None) -> list[tuple[str, str]]:
    """before= pages are immutable. The head page stays short."""
    stamp = "|".join(
        str(payload.get(k)) for k in ("oldest_id", "newest_id", "has_more")
    )
    etag = '"' + hashlib.sha256(stamp.encode()).hexdigest()[:16] + '"'
    if before is not None:
        control = "public, max-age=31536000, immutable"
    else:
        control = "private, max-age=5"
    return [("Cache-Control", control), ("ETag", etag)]


def _projects(qs: dict[str, list[str]]) -> list[str]:
    names: list[str] = []
    for raw in (qs.get("projects") or []) + (qs.get("project") or []):
        names.extend(x.strip() for x in str(raw).split(",") if x.strip())
    return list(dict.fromkeys(names))


def v1_replay(cn, qs: dict[str, list[str]]) -> dict[str, Any]:
    """One merged page. Newest first. before= seeks older ids; after= seeks newer."""
    limit, before, after = parse_replay_page(qs)
    projects = _projects(qs)
    cur = cn.cursor(dictionary=True)
    try:
        roster_ids: list[int] = []
        if projects:
            marks = ",".join(["%s"] * len(projects))
            cur.execute(
                f"SELECT id FROM name WHERE type = 'roster' AND name IN ({marks})",
                projects,
            )
            roster_ids = [int(r["id"]) for r in cur.fetchall()]
        if projects and not roster_ids:
            return {"rows": [], "oldest_id": None, "newest_id": None, "has_more": False}

        where = ["1=1"]
        args: list[Any] = []
        if before is not None:
            where.append("t.id < %s")
            args.append(before)
        elif after is not None:
            where.append("t.id > %s")
            args.append(after)
        if roster_ids:
            where.append("a.roster_id IN (" + ",".join(["%s"] * len(roster_ids)) + ")")
            args.extend(roster_ids)
        order = "t.id ASC" if after is not None and before is None else "t.id DESC"
        cur.execute(
            "SELECT t.id, t.activity_type, t.activity_id, t.from_state, t.to_state, "
            "t.reason, t.at, t.desk_id, dn.name AS from_desk "
            "FROM transition t "
            "JOIN activity a ON a.type = t.activity_type AND a.id = t.activity_id "
            "LEFT JOIN name dn ON dn.id = t.desk_id AND t.desk_id <> 0 "
            f"WHERE {' AND '.join(where)} ORDER BY {order} LIMIT %s",
            [*args, limit + 1],
        )
        found = list(cur.fetchall())
    finally:
        cur.close()

    has_more = len(found) > limit
    page = found[:limit]
    if order.endswith("ASC"):
        page.reverse()
    rows = [_row(r) for r in page]
    _attach_mail(cn, rows)
    _attach_moves(cn, rows)
    ids = [int(r["id"]) for r in rows]
    return {
        "rows": rows,
        "oldest_id": min(ids) if ids else None,
        "newest_id": max(ids) if ids else None,
        "has_more": has_more,
    }


def _row(rec: dict) -> dict[str, Any]:
    ended = None
    if str(rec.get("activity_type")) == "doing" and str(rec.get("to_state")) in _ENDED:
        ended = str(rec.get("at") or "")[:19]
    return {
        "id": int(rec["id"]),
        "type": rec.get("activity_type"),
        "activity_id": int(rec["activity_id"]),
        "at": str(rec.get("at") or "")[:19],
        "from_desk": rec.get("from_desk") or "",
        "to_desks": [],
        "from_state": rec.get("from_state") or "",
        "to_state": rec.get("to_state") or "",
        "reason": rec.get("reason") or "",
        "ended_at": ended,
    }


def _attach_mail(cn, rows: list[dict]) -> None:
    ids = [int(r["activity_id"]) for r in rows if r["type"] == "mail"]
    if not ids:
        return
    cur = cn.cursor(dictionary=True)
    try:
        marks = ",".join(["%s"] * len(ids))
        cur.execute(
            "SELECT mt.id AS mail_id, n.name AS desk "
            "FROM mail_to mt JOIN name n ON n.id = mt.desk_id "
            f"WHERE mt.type = 'mail' AND mt.id IN ({marks})",
            ids,
        )
        by: dict[int, list[str]] = {}
        for rec in cur.fetchall():
            by.setdefault(int(rec["mail_id"]), []).append(str(rec["desk"]))
    finally:
        cur.close()
    for row in rows:
        if row["type"] == "mail":
            row["to_desks"] = sorted(set(by.get(int(row["activity_id"]), [])))


def _attach_moves(cn, rows: list[dict]) -> None:
    want = [r for r in rows if r["type"] in ("todo", "hold") and not r["to_desks"]]
    if not want:
        return
    cur = cn.cursor(dictionary=True)
    try:
        marks = ",".join(["%s"] * len(_MOVE_ACTS))
        pairs = {(r["type"], int(r["activity_id"])) for r in want}
        # one read of move rows for these items; peer is the other desk
        types = sorted({p[0] for p in pairs})
        ids = sorted({p[1] for p in pairs})
        cur.execute(
            "SELECT d.on_type, d.on_id, d.act, n.name AS peer "
            "FROM doing d LEFT JOIN name n ON n.id = d.peer_id "
            f"WHERE d.act IN ({marks}) AND d.on_type IN ({','.join(['%s'] * len(types))}) "
            f"AND d.on_id IN ({','.join(['%s'] * len(ids))})",
            [*_MOVE_ACTS, *types, *ids],
        )
        peer: dict[tuple[str, int], str] = {}
        for rec in cur.fetchall():
            if rec.get("peer"):
                peer[(str(rec["on_type"]), int(rec["on_id"]))] = str(rec["peer"])
    finally:
        cur.close()
    for row in want:
        name = peer.get((str(row["type"]), int(row["activity_id"])))
        if name:
            row["to_desks"] = [name]
