"""member - N-N desk on a roster (unordered, members equal). Self only. Office never leave."""

from __future__ import annotations

from agent_coord.const import CONST_ROSTER

from .db import call


def _slot(cn, group: str, kind: str = "") -> tuple[str, str]:
    """Stored roster name plus its name type (always roster)."""
    from agent_coord.server.records.name import pair

    _k, stored = pair(group, CONST_ROSTER)
    return stored, CONST_ROSTER


def put(cn, group: str, desk: str, kind: str = "") -> list[dict]:
    from agent_coord.server.records import name as rec_name

    slot, k = _slot(cn, group, kind)
    rec_name.ensure_roster(cn, slot, k)
    return call(cn, "mill_member_put", [k, slot, (desk or "").strip()])


def delete(cn, group: str, desk: str, kind: str = "") -> list[dict]:
    slot, k = _slot(cn, group, kind)
    return call(cn, "mill_member_delete", [k, slot, (desk or "").strip()])


def select(cn, group: str = "", desk: str = "", kind: str = "") -> list[dict]:
    if group:
        slot, k = _slot(cn, group, kind)
    else:
        slot, k = "", kind or ""
    d = (desk or "").strip()
    return call(cn, "mill_member_select", [k, slot, d])


def put_admin(cn, desk: str) -> list[dict]:
    """Office host only (#675): the caller has checked the wall-set host flag."""
    return call(cn, "mill_member_admin_put", [(desk or "").strip()])


def delete_admin(cn, desk: str) -> list[dict]:
    """Office host only (#675): the caller has checked host and Admin."""
    return call(cn, "mill_member_admin_delete", [(desk or "").strip()])


def put_office(cn, desk: str) -> list[dict]:
    # #722: the Office roster is id 1 whatever an Admin renamed it to.
    from agent_coord.server.admin.guard import office_name

    return put(cn, office_name(cn), desk)


def list_rosters(cn) -> list[dict]:
    """Every live roster with its live-desk count and member names.

    Same rows as GET /api/pov?part=rosters (card 1193): Office first, then
    name. Each row is {name, desks, members} where desks is the count and
    members is the sorted live desk names. Retired desks and retired
    rosters are omitted (card 1204).
    """
    from agent_coord.const import CONST_OFFICE, CONST_ROSTER

    cur = cn.cursor()
    try:
        cur.execute(
            "SELECT ANY_VALUE(n.name), COUNT(d.id) AS desks FROM name n"
            " LEFT JOIN member m ON m.name_id=n.id"
            " LEFT JOIN name d ON d.id=m.desk_id"
            "  AND d.deleted IS NULL AND d.type = 'desk'"
            " WHERE n.deleted IS NULL AND n.type = %s"
            " GROUP BY n.id, n.name"
            " ORDER BY n.name",
            (CONST_ROSTER,),
        )
        rows = [
            {"name": str(r[0] or "").strip(), "desks": int(r[1] or 0), "members": []}
            for r in cur.fetchall() if r and r[0]
        ]
        cur.execute(
            "SELECT n.name, d.name FROM name n"
            " JOIN member m ON m.name_id=n.id"
            " JOIN name d ON d.id=m.desk_id"
            "  AND d.deleted IS NULL AND d.type = 'desk'"
            " WHERE n.deleted IS NULL AND n.type = %s"
            " ORDER BY n.name, d.name",
            (CONST_ROSTER,),
        )
        by_roster = {rec["name"]: rec for rec in rows}
        for r in cur.fetchall():
            rec = by_roster.get(str((r or ("", ""))[0] or "").strip())
            if rec is not None and r[1]:
                rec["members"].append(str(r[1]).strip())
        rows.sort(key=lambda rec: (rec["name"] != CONST_OFFICE, rec["name"].lower()))
        return rows
    finally:
        cur.close()

