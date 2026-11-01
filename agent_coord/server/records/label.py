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
