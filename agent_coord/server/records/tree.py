"""Plan nested set. Structure only. The first card is the root. Payload is activity (type, id)."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from .db import call

# mill_tree_add mints 10 hex when the parent is on no plan yet.
_HIDDEN_TREE = re.compile(r"^[0-9a-f]{10}$", re.I)


def create(cn, tree: str, type: str = "", id: int = 0) -> list[dict]:
    return call(cn, "mill_tree_create", [(tree or "").strip(), type or "", int(id or 0)])


def add(
    cn,
    parent_type: str,
    parent_id: int,
    type: str,
    id: int,
    tree: str = "",
) -> list[dict]:
    t = (tree or "").strip()
    return call(
        cn,
        "mill_tree_add",
        [t, parent_type, int(parent_id), type, int(id)],
    )


def move(
    cn,
    type: str,
    id: int,
    parent_type: str,
    parent_id: int,
    tree: str = "",
) -> list[dict]:
    t = (tree or "").strip()
    return call(
        cn,
        "mill_tree_move",
        [t, type, int(id), parent_type, int(parent_id)],
    )


def remove(cn, type: str, id: int, tree: str = "") -> list[dict]:
    t = (tree or "").strip()
    return call(cn, "mill_tree_remove", [t, type, int(id)])


def prune(cn, type: str, id: int, tree: str = "") -> list[dict]:
    t = (tree or "").strip()
    return call(cn, "mill_tree_prune", [t, type, int(id)])


def delete(cn, tree: str) -> list[dict]:
    return call(cn, "mill_tree_delete", [(tree or "").strip()])


def select(cn, tree: str) -> list[dict]:
    return call(cn, "mill_tree_select", [(tree or "").strip()])


def subtree(cn, tree: str, type: str, id: int) -> list[dict]:
    return call(cn, "mill_tree_subtree", [(tree or "").strip(), type, int(id)])


def ancestors(cn, tree: str, type: str, id: int) -> list[dict]:
    return call(cn, "mill_tree_ancestors", [(tree or "").strip(), type, int(id)])


def watchers(cn, type: str, id: int) -> list[dict]:
    return call(cn, "mill_tree_watchers", [type, int(id)])


def plan_names(cn, type: str, id: int) -> list[str]:
    """Plan names this activity sits on, in name order (#225)."""
    cur = cn.cursor()
    try:
        cur.execute(
            "SELECT DISTINCT n.name AS name"
            " FROM tree t"
            " JOIN name n ON n.id = t.name_id"
            " WHERE t.type = %s AND t.id = %s"
            " ORDER BY n.name",
            (type, int(id)),
        )
        cols = list(cur.column_names)
        out: list[str] = []
        for rec in cur.fetchall():
            row = dict(zip(cols, rec))
            name = str(row.get("name") or "").strip()
            if name and name not in out:
                out.append(name)
        return out
    finally:
        cur.close()


def on_tree(cn, type: str, id: int) -> bool:
    """True when (type, id) appears on any TREE plan (root or child)."""
    from .db import scalar

    return (
        scalar(
            cn,
            "SELECT 1 FROM tree WHERE type = %s AND id = %s LIMIT 1",
            (type, int(id)),
        )
        is not None
    )


def has_parent(cn, type: str, id: int) -> bool:
    """True when (type, id) has a TREE ancestor (depth >= 1)."""
    from .db import scalar

    return (
        scalar(
            cn,
            "SELECT 1 FROM tree AS node"
            " JOIN tree AS anc"
            "   ON anc.name_id = node.name_id"
            "  AND anc.lft < node.lft"
            "  AND anc.rgt > node.rgt"
            " WHERE node.type = %s AND node.id = %s"
            " LIMIT 1",
            (type, int(id)),
        )
        is not None
    )


_TREE_GLANCE_FROM = (
    " FROM tree t"
    " JOIN name n ON n.id = t.name_id"
    " LEFT JOIN activity a ON a.type = t.type AND a.id = t.id"
    " LEFT JOIN todo td ON t.type = 'todo' AND td.id = t.id"
    " LEFT JOIN mail mb ON t.type = 'mail' AND mb.id = t.id"
    " LEFT JOIN name msn ON msn.id = mb.desk_id"
    " LEFT JOIN doing j ON t.type = 'doing' AND j.id = t.id"
    " LEFT JOIN name jd ON jd.id = j.desk_id"
    " LEFT JOIN hold h ON t.type = 'hold' AND h.id = t.id"
    " LEFT JOIN name hd ON hd.id = h.desk_id"
    " LEFT JOIN name hr ON hr.id = h.resource_id"
    " LEFT JOIN score s ON t.type = 'score' AND s.id = t.id"
    " LEFT JOIN name sd ON sd.id = s.desk_id"
)


def _roster_marks(roster_ids: list[int]) -> tuple[str, list[int]]:
    marks = ",".join(["%s"] * len(roster_ids))
    return marks, list(roster_ids)


def mail_room_root_rows(cn, roster_ids: list[int] | None = None) -> list[dict]:
    """Lean MAIL room roots: WHERE type=mail AND lft=1. No bodies."""
    if roster_ids is not None and not roster_ids:
        return []
    cur = cn.cursor()
    try:
        sql = (
            "SELECT n.name AS tree, n.type AS tree_type, t.type, t.id, t.lft, t.rgt, a.roster_id"
            " FROM tree t"
            " JOIN name n ON n.id = t.name_id"
            " LEFT JOIN activity a ON a.type = t.type AND a.id = t.id"
            " WHERE t.type = 'mail' AND t.lft = 1"
        )
        args: list[int] = []
        if roster_ids:
            marks, one = _roster_marks(roster_ids)
            args = one + one
            sql += (
                " AND ("
                f"a.roster_id IN ({marks})"
                " OR EXISTS ("
                "SELECT 1 FROM tree c"
                " JOIN activity ac ON ac.type = c.type AND ac.id = c.id"
                " WHERE c.name_id = t.name_id"
                " AND c.type = 'mail'"
                " AND t.lft < c.lft AND c.rgt < t.rgt"
                f" AND ac.roster_id IN ({marks})"
                "))"
            )
        sql += " ORDER BY n.name"
        cur.execute(sql, args)
        cols = list(cur.column_names)
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        cur.close()


def glance_rows(cn, roster_ids: list[int] | None = None) -> list[dict]:
    """Every nested-set row for the Wall. No list CALL exists."""
    if roster_ids is not None and not roster_ids:
        return []
    cur = cn.cursor()
    try:
        sql = (
            "SELECT n.name AS tree, n.type AS tree_type,"
            " t.type, t.id, t.lft, t.rgt, a.roster_id,"
            " td.status AS todo_status, td.body AS todo_body,"
            " mb.body AS mail_body, msn.name AS mail_src,"
            " jd.name AS join_desk, j.text AS join_doing,"
            " hd.name AS hold_desk, hr.name AS hold_resource,"
            " s.kpi AS score_kpi, sd.name AS score_desk"
            + _TREE_GLANCE_FROM
        )
        args: list[int] = []
        if roster_ids:
            marks, args = _roster_marks(roster_ids)
            sql += f" WHERE a.roster_id IN ({marks})"
        sql += " ORDER BY n.name, t.lft"
        cur.execute(sql, args)
        cols = list(cur.column_names)
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        cur.close()


def activity_forest_rows(
    cn, activity_type: str, roster_ids: list[int] | None = None
) -> list[dict]:
    """Every node of one activity type on trees that touch the roster set.

    A tree is included when any node of this type carries one of those
    rosters. Every node of this type on that tree is returned, including
    nodes filed under a different roster. The row keeps roster_id.
    """
    if roster_ids is not None and not roster_ids:
        return []
    cur = cn.cursor()
    try:
        sql = (
            "SELECT n.name AS tree, n.type AS tree_type,"
            " t.type, t.id, t.lft, t.rgt, a.roster_id,"
            " td.status AS todo_status, td.body AS todo_body,"
            " mb.body AS mail_body, msn.name AS mail_src,"
            " jd.name AS join_desk, j.text AS join_doing,"
            " hd.name AS hold_desk, hr.name AS hold_resource,"
            " s.kpi AS score_kpi, sd.name AS score_desk"
            + _TREE_GLANCE_FROM
            + " WHERE t.type = %s"
        )
        args: list = [activity_type]
        if roster_ids:
            marks, one = _roster_marks(roster_ids)
            args.append(activity_type)
            args.extend(one)
            sql += (
                " AND t.name_id IN ("
                "SELECT c.name_id FROM tree c"
                " JOIN activity ac ON ac.type = c.type AND ac.id = c.id"
                " WHERE c.type = %s"
                f" AND ac.roster_id IN ({marks})"
                ")"
            )
        sql += " ORDER BY n.name, t.lft"
        cur.execute(sql, args)
        cols = list(cur.column_names)
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        cur.close()


def mail_forest_rows(cn, roster_ids: list[int] | None = None) -> list[dict]:
    """Every mail node on trees that have at least one letter in the roster set."""
    return activity_forest_rows(cn, "mail", roster_ids)


def todo_forest_rows(cn, roster_ids: list[int] | None = None) -> list[dict]:
    """Every todo node on trees that have at least one card in the roster set."""
    return activity_forest_rows(cn, "todo", roster_ids)


def forest_last_activity(
    cn, roster_ids: list[int] | None = None
) -> dict[str, object]:
    """MAX(activity.updated) per TREE name for nest-set nodes. Real last TREE activity."""
    if roster_ids is not None and not roster_ids:
        return {}
    cur = cn.cursor()
    try:
        sql = (
            "SELECT ANY_VALUE(n.name) AS tree, MAX(a.updated) AS last_activity"
            " FROM tree t"
            " JOIN name n ON n.id = t.name_id"
            " LEFT JOIN activity a ON a.type = t.type AND a.id = t.id"
        )
        args: list = []
        if roster_ids:
            marks, one = _roster_marks(roster_ids)
            args = list(one)
            sql += (
                " WHERE t.name_id IN ("
                "SELECT c.name_id FROM tree c"
                " JOIN activity ac ON ac.type = c.type AND ac.id = c.id"
                f" WHERE ac.roster_id IN ({marks})"
                ")"
            )
        sql += " GROUP BY n.name"
        cur.execute(sql, args)
        out: dict[str, object] = {}
        for row in cur.fetchall():
            name = str(row[0] or "")
            if not name:
                continue
            last = row[1]
            if last is not None:
                out[name] = last
        return out
    finally:
        cur.close()



def pack_trees(rows: list[dict] | None) -> list[dict]:
    """Group glance rows into floor trees. Depth from lft/rgt. Hex mint stays hidden."""
    groups: dict[str, list[dict]] = {}
    order: list[str] = []
    for raw in rows or []:
        name = str(raw.get("tree") or "")
        if name not in groups:
            groups[name] = []
            order.append(name)
        groups[name].append(raw)
    out: list[dict] = []
    for name in order:
        incoming = groups[name]
        nodes: list[dict] = []
        for raw in incoming:
            lft = int(raw.get("lft") or 0)
            rgt = int(raw.get("rgt") or 0)
            depth = sum(
                1
                for other in incoming
                if int(other.get("lft") or 0) < lft and int(other.get("rgt") or 0) > rgt
            )
            nodes.append(
                {
                    "type": str(raw.get("type") or ""),
                    "id": int(raw.get("id") or 0),
                    "lft": lft,
                    "rgt": rgt,
                    "depth": depth,
                    "title": str(raw.get("title") or ""),
                    "status": str(raw.get("status") or ""),
                    "who": str(raw.get("who") or ""),
                    "roster_id": str(raw.get("roster_id") or ""),
                    "has_children": rgt > lft + 1,
                }
            )
        out.append(
            {
                "name": name,
                "hidden": bool(_HIDDEN_TREE.match(name)),
                "nodes": nodes,
            }
        )
    return out


def node_tree(cn, type: str, id: int) -> str:
    """Name of the plan where (type, id) roots the biggest branch. '' when on none."""
    cur = cn.cursor()
    try:
        cur.execute(
            "SELECT n.name FROM tree t JOIN name n ON n.id = t.name_id"
            " WHERE t.type = %s AND t.id = %s"
            " ORDER BY (t.rgt - t.lft) DESC, n.name LIMIT 1",
            (type, int(id)),
        )
        row = cur.fetchone()
    finally:
        cur.close()
    return str(row[0]) if row else ""


def trail_details(cn, nodes: list[tuple[str, int]]) -> dict[tuple[str, int], dict]:
    """One read: (type, id) -> activity + todo/mail fields for `mill trail`.

    Times come back as UTC (session offset removed) in *_utc keys.
    """
    want = [(str(t), int(i)) for t, i in nodes if str(t) in ("mail", "todo")]
    if not want:
        return {}
    marks = ",".join(["(%s,%s)"] * len(want))
    args: list[Any] = []
    for t, i in want:
        args.extend([t, i])
    cur = cn.cursor(dictionary=True)
    try:
        cur.execute("SELECT TIMESTAMPDIFF(SECOND, UTC_TIMESTAMP(), NOW()) AS off")
        off_row = cur.fetchone() or {}
        off_s = int(off_row.get("off") or 0)
        cur.execute(
            "SELECT a.type, a.id, a.deleted, a.updated AS a_updated,"
            " ad.name AS actor,"
            " td.status AS todo_status, td.body AS todo_body, td.updated AS todo_updated,"
            " tc.name AS todo_creator, ts.name AS todo_assigned,"
            " mb.body AS mail_body, mb.created AS mail_created, ms.name AS mail_src"
            " FROM activity a"
            " LEFT JOIN name ad ON ad.id = a.desk_id"
            " LEFT JOIN todo td ON a.type = 'todo' AND td.id = a.id"
            " LEFT JOIN name tc ON tc.id = td.creator_id"
            " LEFT JOIN name ts ON ts.id = td.assigned_id"
            " LEFT JOIN mail mb ON a.type = 'mail' AND mb.id = a.id"
            " LEFT JOIN name ms ON ms.id = mb.desk_id"
            " WHERE (a.type, a.id) IN (" + marks + ")",
            args,
        )
        rows = list(cur.fetchall())
    finally:
        cur.close()
    shift = timedelta(seconds=off_s)
    out: dict[tuple[str, int], dict] = {}
    for r in rows:
        rec = dict(r)
        for src, dst in (
            ("deleted", "deleted_utc"),
            ("a_updated", "updated_utc"),
            ("todo_updated", "todo_updated_utc"),
            ("mail_created", "mail_created_utc"),
        ):
            v = rec.pop(src, None)
            rec[dst] = (v - shift) if isinstance(v, datetime) else None
        out[(str(rec["type"]), int(rec["id"]))] = rec
    return out


def mail_tos_names(cn, mail_ids: list[int]) -> dict[int, set[str]]:
    """mail id -> dest desk names (for trail read access)."""
    ids = sorted({int(i) for i in mail_ids if int(i or 0) > 0})
    if not ids:
        return {}
    marks = ",".join(["%s"] * len(ids))
    cur = cn.cursor()
    try:
        cur.execute(
            "SELECT mt.id, n.name FROM mail_to mt JOIN name n ON n.id = mt.desk_id"
            " WHERE mt.type = 'mail' AND mt.id IN (" + marks + ")",
            ids,
        )
        rows = cur.fetchall()
    finally:
        cur.close()
    out: dict[int, set[str]] = {}
    for mid, nm in rows:
        out.setdefault(int(mid), set()).add(str(nm or ""))
    return out


def is_hidden_tree(name: str) -> bool:
    """10-hex plan minted by mill_tree_add (not a room name)."""
    return bool(_HIDDEN_TREE.match(str(name or "")))
