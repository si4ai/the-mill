"""MAIL receipts.

Unread is a null opened on mail_to for this desk.
The opened table is gone. insert calls mill_mail_open, which stamps
mail_to.opened.
"""

from __future__ import annotations

from agent_coord.const import CONST_DESK
from .db import call


def insert(cn, mail_id: int, desk: str) -> list[dict]:
    from agent_coord.server.records.name import bare

    rows = call(cn, "mill_mail_open", [mail_id, bare(desk, CONST_DESK)])
    if rows and int((rows[0] or {}).get("push_receipt") or 0) == 1:
        from agent_coord.server.mail_push import push_receipt

        push_receipt(cn, rows[0])
    return rows


def read_ids(cn, mail_ids: list[int], desk: str) -> set[int]:
    """Mail ids this desk has opened (mail_to.opened is set). One query."""
    from agent_coord.server.records.name import bare
    from agent_coord.server.records.name import get as name_get

    ids = [int(i) for i in mail_ids if int(i or 0)]
    who = bare(desk, CONST_DESK) if desk else ""
    if not ids or not who:
        return set()
    did = name_get(cn, who, CONST_DESK)
    if not did:
        return set()
    marks = ",".join(["%s"] * len(ids))
    cur = cn.cursor()
    try:
        cur.execute(
            "SELECT t.id FROM mail_to t"
            " WHERE t.opened IS NOT NULL AND t.desk_id = %s"
            " AND t.id IN (" + marks + ")",
            (int(did), *ids),
        )
        return {int(row[0]) for row in cur.fetchall() if row and row[0]}
    finally:
        cur.close()
