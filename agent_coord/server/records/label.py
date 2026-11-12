"""label - tags on any activity. name_id is a label. mill label-add."""

from __future__ import annotations

from typing import Any

from agent_coord.const import CONST_LABEL
from agent_coord.helpers.errors import CoordError
from agent_coord.helpers.label_ord import missing_label, parse_label_ord
from .db import call


def _no_activity(type: str, id: int) -> str:
    return "label-add: no %s %s" % (type, int(id))


def _activity_live(cn, type: str, id: int) -> bool:
    from .db import scalar

    rec = scalar(
        cn,
        "SELECT 1 FROM activity WHERE type = %s AND id = %s AND deleted IS NULL",
        (type, int(id)),
    )
    return rec is not None


def put(cn, type: str, id: int, tag: str, ord: int | None = None) -> list[dict]:
    """Tag an activity. An unknown label name is refused and not minted (#198).

    A missing or deleted activity is a plain refusal. The raw 1452 names the book.
    """
    from . import name as rec_name
    from agent_coord.server.records.name import bare

    tag_b = bare(tag, CONST_LABEL)
    if rec_name.get(cn, tag_b, CONST_LABEL) is None:
        raise CoordError(missing_label(tag_b))
    if not _activity_live(cn, type, int(id)):
        raise CoordError(_no_activity(type, id))
    try:
        return call(cn, "mill_label_put", [type, int(id), tag_b, parse_label_ord(ord)])
    except CoordError:
        raise
    except Exception as exc:
        if int(getattr(exc, "errno", 0) or 0) == 1452:
            raise CoordError(_no_activity(type, id)) from exc
        raise


def delete(cn, type: str, id: int, tag: str) -> list[dict]:
    """Untag. A missing activity or a label not on it is a plain refusal (#245)."""
    from agent_coord.server.records.name import bare

    tag_b = bare(tag, CONST_LABEL)
    if len(tag_b) > 64:
        raise CoordError("label-remove: no label %s" % tag_b[:64])
    from . import name as rec_name

    if rec_name.get(cn, tag_b, CONST_LABEL) is None:
        from agent_coord.helpers.next_cmd import with_next

        raise CoordError(with_next("label: no such name %s" % tag_b, "mill trail --label %s" % tag_b))
    if not _activity_live(cn, type, int(id)):
        raise CoordError("label-remove: no %s %s" % (type, int(id)))
    return call(cn, "mill_label_delete", [type, int(id), tag_b])


def select(cn, type: str = "", id: int = 0) -> list[dict]:
    return call(cn, "mill_label_select", [type, int(id or 0)])


def rows_for(cn, tag: str) -> list[dict[str, Any]]:
    """Mail and todo wearing this label, ord then created. Deleted activity is out (#199)."""
    from agent_coord.server.records.name import bare

    tag_b = bare(tag, CONST_LABEL)
    cur = cn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT l.type, l.id, l.ord, l.created"
            " FROM label l"
            " JOIN name n ON n.id = l.name_id"
            " JOIN activity a ON a.type = l.type AND a.id = l.id"
            " WHERE n.type = 'label' AND n.name = %s AND n.deleted IS NULL"
            " AND a.deleted IS NULL"
            " AND l.type IN ('mail', 'todo')"
            " ORDER BY l.ord, l.created, l.type, l.id",
            (tag_b,),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        cur.close()


# Card 1153: the Wall PRIORITIES tab. A desk's list is the label named after the desk;
# human-priorities is the shared human list.
HUMAN_LIST = "human-priorities"
# The card's latest move (activity.act) as the tab's activity kind; other acts are not served.
_KIND = {"claim": "claim", "assign": "claim", "unclaim": "claim", "note": "note",
         "ship": "pass", "done": "pass", "back": "pass"}


def wall_rows(cn, names: list[str] | None = None) -> list[dict[str, Any]]:
    """Mail and todo wearing a desk-named label or human-priorities (or the given names).

    Office-wide: labels are not roster-scoped. Deleted activity is out, done cards stay
    in. Each row: label, type, id, ord, updated (when ord was last set) and, for a todo,
    card {roster, need, status, volunteer, eta_at?, progress?, last_activity_at?,
    last_activity_kind?} plus off_roster when the label is a desk that is not a member
    of the card's roster (Office counts for every desk). Read-only: one SELECT.
    """
    import json

    from agent_coord.helpers.ident import iso6

    if names:
        pick, args = "n.name IN (" + ",".join(["%s"] * len(names)) + ")", tuple(names)
    else:
        pick, args = "(dn.id IS NOT NULL OR n.name = %s)", (HUMAN_LIST,)
    cur = cn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT n.name AS label, l.type, l.id, l.ord, l.updated,"
            " t.status, t.meta, t.roster_id, rn.name AS roster, vn.name AS volunteer,"
            " a.act AS card_act, a.updated AS card_at,"
            " (SELECT MAX(da.updated) FROM doing d"
            "   JOIN activity da ON da.type = 'doing' AND da.id = d.id"
            "  WHERE d.on_type = 'todo' AND d.on_id = l.id AND d.act = 'task') AS tw_at,"
            " (dn.id IS NOT NULL AND t.roster_id <> 1 AND NOT EXISTS ("
            "   SELECT 1 FROM member m WHERE m.name_id = t.roster_id AND m.desk_id = dn.id)) AS off_roster"
            " FROM label l"
            " JOIN name n ON n.id = l.name_id AND n.type = 'label' AND n.deleted IS NULL"
            " JOIN activity a ON a.type = l.type AND a.id = l.id AND a.deleted IS NULL"
            " LEFT JOIN name dn ON dn.type = 'desk' AND dn.name = n.name AND dn.deleted IS NULL"
            " LEFT JOIN todo t ON l.type = 'todo' AND t.id = l.id"
            " LEFT JOIN name rn ON rn.id = t.roster_id"
            " LEFT JOIN name vn ON vn.id = t.assigned_id"
            " WHERE l.type IN ('mail', 'todo') AND " + pick +
            " ORDER BY n.name, l.ord, l.id, l.type",
            args,
        )
        raw = list(cur.fetchall())
    finally:
        cur.close()
    out: list[dict[str, Any]] = []
    for r in raw:
        row: dict[str, Any] = {
            "label": str(r.get("label") or ""),
            "type": r.get("type"),
            "id": int(r.get("id") or 0),
            "ord": int(r.get("ord") if r.get("ord") is not None else 65535),
            "updated": iso6(r.get("updated")),
        }
        if r.get("type") == "todo":
            meta = r.get("meta")
            if isinstance(meta, (bytes, bytearray)):
                meta = meta.decode()
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except json.JSONDecodeError:
                    meta = None
            meta = meta if isinstance(meta, dict) else {}
            card: dict[str, Any] = {
                "roster": str(r.get("roster") or ""),
                "need": str(meta.get("slug") or row["id"]),
                "status": str(r.get("status") or ""),
                "volunteer": str(r.get("volunteer") or ""),
            }
            for key in ("eta_at", "progress"):
                if meta.get(key) not in (None, ""):
                    card[key] = str(meta[key])
            moves = []
            kind = _KIND.get(str(r.get("card_act") or ""))
            if kind and r.get("card_at") is not None:
                moves.append((r["card_at"], kind))
            if r.get("tw_at") is not None:
                moves.append((r["tw_at"], "tw"))
            if moves:
                at, kind = max(moves, key=lambda m: m[0])
                card["last_activity_at"] = iso6(at)
                card["last_activity_kind"] = kind
            if r.get("off_roster"):
                card["off_roster"] = True
            row["card"] = card
        out.append(row)
    return out
