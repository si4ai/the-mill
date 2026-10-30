"""MAIL letters."""

from __future__ import annotations

from agent_coord.const import CONST_DESK, CONST_MAIL, CONST_ROSTER

from .db import call, scalar, scalar_done
from .db import commit as _db_commit


def _stored(value) -> str:
    return str(value or "").strip()


def insert(
    cn,
    project: str,
    desk: str,
    dst: str,
    body: str,
    receipt: int = 0,
    dst_kind: str = CONST_DESK,
) -> list[dict]:
    from agent_coord.server.records.name import roster_name, pair

    project_b = roster_name(project)
    _dk, desk_b = pair(desk, CONST_DESK)
    dst_type, dst_b = pair(dst, dst_kind or CONST_DESK)
    return call(
        cn,
        "mill_mail_insert",
        [project_b, desk_b, dst_type, dst_b, body, int(receipt or 0)],
    )


def update(cn, mail_id: int, desk: str, dst: str | None = None, body: str | None = None) -> list[dict]:
    from agent_coord.server.records.name import bare

    return call(cn, "mill_mail_update", [mail_id, bare(desk, CONST_DESK), dst or "", body])


def delete(cn, mail_id: int, desk: str) -> list[dict]:
    from agent_coord.server.records.name import bare

    return call(cn, "mill_mail_delete", [mail_id, bare(desk, CONST_DESK)])


def get(cn, mail_id: int) -> list[dict]:
    return call(cn, "mill_mail_get", [mail_id])


def select(cn, desk: str) -> list[dict]:
    """Desk inbox, every project. The procedure takes the desk only (#201)."""
    from agent_coord.server.records.name import bare

    return call(
        cn,
        "mill_mail_select",
        [bare(desk, CONST_DESK) if desk else ""],
    )


def inbox(cn, desk: str, *, all_mail: bool = False, limit: int = 100) -> list[dict]:
    """Inbox page cut in SQL. Unread: newest `limit` unread, newest first (card 846).
    all_mail: newest `limit` letters, newest first. Same rows as select()."""
    from agent_coord.server.records.name import bare

    return call(
        cn,
        "mill_mail_inbox",
        [bare(desk, CONST_DESK) if desk else "", 1 if all_mail else 0, max(1, int(limit or 100))],
    )


def list_project(cn, project: str) -> list[dict]:
    from agent_coord.server.records.name import roster_name

    return call(cn, "mill_mail_list", [roster_name(project) if project else ""])


def dest_rows_json(value) -> list[dict]:
    """Parse a dests JSON array (mill_mail_list / mill_floor_part mail) into to_list-shape rows.

    Rows: desk_id, desk, roster (None), receipt. Ordered by desk name like tos_by_id.
    """
    import json

    if value is None:
        return []
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    out: list[dict] = []
    seen: set[str] = set()
    for d in value if isinstance(value, list) else []:
        if not isinstance(d, dict):
            continue
        desk = str(d.get("desk") or "")
        if not desk or desk in seen:
            continue
        seen.add(desk)
        out.append(
            {
                "desk_id": d.get("desk_id"),
                "desk": desk,
                "roster": None,
                "receipt": d.get("receipt"),
            }
        )
    out.sort(key=lambda r: str(r.get("desk") or ""))
    return out


def list_rosters(cn, names: list[str]) -> list[tuple[str, dict]]:
    """mill_mail_list for many projects/roles in one read: [(requested name, letter row)].

    Ids are resolved once (name.roster_ids), then one IN (...) read with the same
    row shape as mill_mail_list (one row per letter, dests JSON). Newest 500 letters per
    roster, like one mill_mail_list call each. Output follows the input name order,
    then id DESC. No names resolved -> [].
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
            "SELECT m.type, m.id, m.created, m.created AS updated, m.desk_id,"
            " m.roster_id AS sender_roster_id, m.roster_id AS roster_id, m.body,"
            " srcn.name AS desk, srcn.type AS desk_type,"
            " affn.name AS roster, affn.type AS roster_type,"
            " affn.name AS sender_roster, affn.type AS sender_roster_type,"
            " JSON_ARRAYAGG(JSON_OBJECT('desk_id', t.desk_id, 'desk', dstn.name,"
            " 'desk_type', dstn.type, 'receipt', t.receipt)) AS dests"
            " FROM (SELECT id FROM (SELECT id, ROW_NUMBER() OVER"
            " (PARTITION BY roster_id ORDER BY id DESC) AS rn"
            " FROM mail WHERE roster_id IN (" + marks + ")) x WHERE x.rn <= %s) s"
            " JOIN mail m ON m.id = s.id"
            " JOIN mail_to t ON t.type = 'mail' AND t.id = m.id"
            " LEFT JOIN name srcn ON srcn.id = m.desk_id"
            " LEFT JOIN name dstn ON dstn.id = t.desk_id"
            " LEFT JOIN name affn ON affn.id = m.roster_id"
            " GROUP BY m.type, m.id"
            " ORDER BY m.id DESC",
            (*ids, LIST_ROSTER_MAX),
        )
        rows = list(cur.fetchall())
    finally:
        cur.close()
    by_aff: dict[int, list[dict]] = {}
    for r in rows:
        by_aff.setdefault(int(r.get("roster_id") or 0), []).append(r)
    out: list[tuple[str, dict]] = []
    for name, aid in pairs:
        for r in by_aff.get(aid, []):
            out.append((name, r))
    return out


# mill_mail_list newest-letter cap (per roster for list_rosters).
LIST_ROSTER_MAX = 500


def group_list_rows(rows: list[dict]) -> list[tuple[dict, list[dict]]]:
    """Collapse mill_mail_list JOIN rows (one row per dest) into (letter, dest_rows).

    mill_mail_list already JOINs mail_to. Prefer this over N x to_list.
    Letter fields come from the first row per mail id; dest_rows match to_list shape
    (desk, roster, receipt) for public_mail_tos.
    """
    order: list[int] = []
    letters: dict[int, dict] = {}
    dests: dict[int, list[dict]] = {}
    seen_dst: dict[int, set[str]] = {}
    for r in rows or []:
        try:
            mid = int(r.get("id") or 0)
        except (TypeError, ValueError):
            continue
        if not mid:
            continue
        if mid not in letters:
            order.append(mid)
            letters[mid] = {
                "id": mid,
                "created": r.get("created") or r.get("updated") or r.get("lastUpdated"),
                "desk": r.get("desk"),
                "sender_roster": r.get("sender_roster"),
                "body": r.get("body") or "",
            }
            dests[mid] = []
            seen_dst[mid] = set()
        if "dests" in r:
            for d in dest_rows_json(r.get("dests")):
                if d["desk"] in seen_dst[mid]:
                    continue
                seen_dst[mid].add(d["desk"])
                d["opened"] = None
                dests[mid].append(d)
            continue
        desk = str(r.get("dst") or "")
        if not desk or desk in seen_dst[mid]:
            continue
        seen_dst[mid].add(desk)
        dests[mid].append(
            {
                "desk": desk,
                "roster": None,
                "receipt": r.get("receipt"),
                "opened": r.get("opened"),
                "desk_id": r.get("dst_id"),
            }
        )
    return [(letters[mid], dests[mid]) for mid in order]


def _mail_id_list(mail_ids: list[int]) -> list[int]:
    """Distinct positive mail ids, input order kept."""
    ids: list[int] = []
    seen: set[int] = set()
    for raw in mail_ids or []:
        try:
            mid = int(raw)
        except (TypeError, ValueError):
            continue
        if mid and mid not in seen:
            seen.add(mid)
            ids.append(mid)
    return ids


def _mail_crumb(packed: list[dict], mid: int) -> dict:
    """Room root is the outermost mail card. A non-mail ancestor is not the room."""
    mail_anc = [r for r in packed if str(r.get("anc_type") or "") == "mail"]
    if not mail_anc:
        return {}
    root = mail_anc[0]
    self_row = mail_anc[-1]
    parent = mail_anc[-2] if len(mail_anc) >= 2 else None
    out = {
        "tree": str(root.get("tree") or ""),
        "root_id": int(root.get("anc_id") or 0),
        "root_type": "mail",
    }
    if parent and int(parent.get("anc_id") or 0) != int(self_row.get("anc_id") or 0):
        out["parent_id"] = int(parent.get("anc_id") or 0)
        out["parent_type"] = "mail"
    elif len(mail_anc) == 1:
        out["root_id"] = int(mid)
        out["root_type"] = "mail"
    return out


def tree_crumbs_batch(cn, mail_ids: list[int]) -> dict[int, dict]:
    """Batch tree_crumbs for many mail ids (one query). Missing ids -> omitted."""
    ids = _mail_id_list(mail_ids)
    if not ids:
        return {}
    marks = ",".join(["%s"] * len(ids))
    cur = cn.cursor()
    try:
        cur.execute(
            "SELECT node.id AS mail_id, n.name AS tree, n.type AS tree_type, anc.type AS anc_type,"
            " anc.id AS anc_id, anc.lft"
            " FROM tree AS node"
            " JOIN name n ON n.id = node.name_id"
            " JOIN tree AS anc"
            "   ON anc.name_id = node.name_id"
            "  AND anc.lft <= node.lft AND anc.rgt >= node.rgt"
            " WHERE node.type = 'mail' AND node.id IN (" + marks + ")"
            " ORDER BY node.id, anc.lft",
            tuple(ids),
        )
        cols = list(cur.column_names)
        by_mail: dict[int, list[dict]] = {}
        for tup in cur.fetchall():
            row = dict(zip(cols, tup))
            mid = int(row.get("mail_id") or 0)
            if not mid:
                continue
            by_mail.setdefault(mid, []).append(row)
    finally:
        cur.close()
    out: dict[int, dict] = {}
    for mid, packed in by_mail.items():
        crumb = _mail_crumb(packed, mid)
        if crumb:
            out[mid] = crumb
    return out



def to_put(
    cn,
    mail_id: int,
    project: str,
    dst: str,
    receipt: int = 0,
    dst_kind: str = CONST_DESK,
) -> list[dict]:
    """Add dest(s) onto an existing mail. A project or role dest expands to its members."""
    from agent_coord.server.records.name import pair

    _pk, project_b = pair(project, CONST_ROSTER)
    dst_type, dst_b = pair(dst, dst_kind or CONST_DESK)
    return call(
        cn,
        "mill_mail_to_put",
        [int(mail_id), project_b, dst_type, dst_b, int(receipt or 0)],
    )



def to_copied(cn, mail_id: int, desks) -> None:
    """#818 D1: mark these recipients copied (room members only) on one letter."""
    import json

    names = sorted({str(d or "").strip() for d in (desks or ()) if str(d or "").strip()})
    if names:
        call(cn, "mill_mail_to_copied", [int(mail_id), json.dumps(names)])


def letters_by_id(cn, mail_ids: list[int]) -> dict[int, dict]:
    """Letter rows for many ids. Same columns as letter_row. Missing ids omitted."""
    ids = _mail_id_list(mail_ids)
    if not ids:
        return {}
    marks = ",".join(["%s"] * len(ids))
    cur = cn.cursor()
    try:
        cur.execute(
            "SELECT m.id, m.created, m.body, srcn.name AS desk,"
            " saffn.name AS sender_roster"
            " FROM mail m"
            " LEFT JOIN name srcn ON srcn.id = m.desk_id"
            " LEFT JOIN name saffn ON saffn.id = m.roster_id"
            " WHERE m.type = 'mail' AND m.id IN (" + marks + ")",
            tuple(ids),
        )
        cols = list(cur.column_names)
        out: dict[int, dict] = {}
        for tup in cur.fetchall():
            row = dict(zip(cols, tup))
            mid = int(row.get("id") or 0)
            if mid:
                out[mid] = row
        return out
    finally:
        cur.close()


def letter_row(cn, mail_id: int) -> dict | None:
    """One letter row: id, created, desk (sender slug), sender_roster, body."""
    return letters_by_id(cn, [int(mail_id)]).get(int(mail_id))


def tos_by_id(cn, mail_ids: list[int]) -> dict[int, list[dict]]:
    """Dest desks for many mail ids. Same row shape as to_list, ordered by desk slug."""
    ids = _mail_id_list(mail_ids)
    if not ids:
        return {}
    marks = ",".join(["%s"] * len(ids))
    cur = cn.cursor()
    try:
        cur.execute(
            "SELECT t.id AS mail_id, t.desk_id, dn.name AS desk, NULL AS roster,"
            " t.receipt, t.opened"
            " FROM mail_to t"
            " LEFT JOIN name dn ON dn.id = t.desk_id"
            " WHERE t.type = 'mail' AND t.id IN (" + marks + ")"
            " ORDER BY t.id, dn.name",
            tuple(ids),
        )
        cols = list(cur.column_names)
        out: dict[int, list[dict]] = {}
        for tup in cur.fetchall():
            row = dict(zip(cols, tup))
            mid = int(row.pop("mail_id") or 0)
            if not mid:
                continue
            out.setdefault(mid, []).append(row)
        return out
    finally:
        cur.close()


def to_list(cn, mail_id: int) -> list[dict]:
    """Dest desks for one mail: desk_id, desk slug, roster slug."""
    return list(tos_by_id(cn, [int(mail_id)]).get(int(mail_id), []))


def ids_for_desk(cn, mail_ids: list[int], desk: str) -> list[int]:
    """Ids this desk sent or was named on, in the given order.

    A room read hides every other letter (#191). Room membership is not enough.
    """
    who = _stored(desk)
    ids = [int(i) for i in mail_ids if int(i or 0)]
    if not who or not ids:
        return []
    letters = letters_by_id(cn, ids)
    dests = tos_by_id(cn, ids)
    out: list[int] = []
    for mid in ids:
        letter = letters.get(mid)
        if letter and _stored(letter.get("desk")) == who:
            out.append(mid)
            continue
        for row in dests.get(mid) or []:
            if _stored(row.get("desk")) == who:
                out.append(mid)
                break
    return out


def public_mail_tos(dest_rows: list[dict]) -> list[dict]:
    """Agent-facing mail_to cast: [{deskId, receipt}, ...]. No ids / opened.

    mail_to has no roster column; roster lives on the letter (mail.roster_id).
    """
    out: list[dict] = []
    for r in dest_rows or []:
        desk = str(r.get("desk") or "").strip()
        if not desk:
            continue
        out.append({"deskId": desk, "receipt": int(r.get("receipt") or 0)})
    return out


def public_sender(row: dict) -> dict:
    """Sender identity: {deskId, roster}. Roster is the project or role name."""
    existing = row.get("sender")
    if isinstance(existing, dict):
        desk = str(existing.get("deskId") or existing.get("desk") or "").strip()
        aff_raw = existing.get("roster")
        aff = str(aff_raw).strip() if aff_raw else None
        return {"deskId": desk, "roster": aff or None}

    sender_raw = existing or row.get("desk") or row.get("src") or ""
    desk = str(sender_raw).strip() if sender_raw else ""
    aff_raw = (
        row.get("sender_roster")
        if row.get("sender_roster") is not None
        else row.get("sender_aff")
    )
    # Do NOT use row["roster"] - that is dest roster on join rows.
    aff = str(aff_raw).strip() if aff_raw else None
    return {"deskId": desk, "roster": aff or None}


def room_cast(pub_or_sender, mail_tos: list[dict] | None = None) -> list[dict]:
    """Visibility cast = sender ∪ mail_tos (deskId + roster; no receipt on sender).

    Every room includes the sender and all mail_to dests.
    """
    if isinstance(pub_or_sender, dict) and "mail_tos" in pub_or_sender:
        sender = pub_or_sender.get("sender") or {}
        tos = list(pub_or_sender.get("mail_tos") or [])
    else:
        sender = pub_or_sender if isinstance(pub_or_sender, dict) else {}
        tos = list(mail_tos or [])
    out: list[dict] = []
    seen: set[str] = set()
    desk = ""
    aff = None
    if isinstance(sender, dict):
        desk = str(sender.get("deskId") or sender.get("desk") or "")
        aff = sender.get("roster")
    elif sender:
        desk = str(sender)
    if desk and desk not in seen:
        seen.add(desk)
        out.append({"deskId": desk, "roster": aff if aff else None})
    for t in tos:
        d = str((t or {}).get("deskId") or (t or {}).get("desk") or "")
        if not d or d in seen:
            continue
        seen.add(d)
        out.append(
            {
                "deskId": d,
                "roster": (t or {}).get("roster") or None,
            }
        )
    return out



def read_cursor(cn, desk_id: int, tree_id: int) -> int:
    """Last id this desk read on this tree (tree_id = tree.name_id). 0 when unset."""
    rows = call(cn, "mill_read_cursor", [int(desk_id), int(tree_id)])
    return int((rows[0].get("last_id") if rows else 0) or 0)


def advance_read_cursor(cn, desk_id: int, tree_id: int, last_id: int) -> None:
    """Move the cursor forward, never back (#867: an SP, not an upsert)."""
    call(cn, "cmd_read_upto", [int(desk_id), int(tree_id), int(last_id)])


def room_tree_id(cn, mail_id: int) -> int | None:
    """tree.name_id of this letter's room, or None for an off-tree letter."""
    crumbs = tree_crumbs(cn, int(mail_id))
    name = str(crumbs.get("tree") or "") if crumbs else ""
    if not name:
        return None
    cur = cn.cursor()
    try:
        cur.execute("SELECT id FROM name WHERE type = 'tree' AND name = %s LIMIT 1", (name,))
        row = cur.fetchone()
    finally:
        cur.close()
    return int(row[0]) if row and row[0] else None


MAIL_BODY_LIST_MAX = 256


def lean_body(text: str | None, n: int = MAIL_BODY_LIST_MAX) -> tuple[str, bool]:
    """Truncate letter body for list/poll. Returns (body, truncated)."""
    body = text if isinstance(text, str) else ("" if text is None else str(text))
    limit = int(n) if n and int(n) > 0 else MAIL_BODY_LIST_MAX
    if len(body) <= limit:
        return body, False
    return body[:limit], True


def _to_desk(t) -> str:
    if isinstance(t, dict):
        return str(t.get("deskId") or t.get("desk") or "").strip()
    return str(t or "").strip()


def public_mail(
    row: dict,
    dest_rows: list[dict] | None = None,
    *,
    crumbs: dict | None = None,
    lean: bool = False,
    lean_n: int = MAIL_BODY_LIST_MAX,
) -> dict:
    """Public MAIL: id, created, from, sender, body, mail_tos (+ crumbs).

    `from` is the sender desk name, the one key every letter row carries
    (short rows and push arrivals too, card 837); `sender` adds its roster.
    `to` is the recipient desk names on every full letter and push arrival.

    lean=True (list/poll): truncate body to lean_n and set body_trunc when clipped.
    """
    mid = int(row.get("id") or 0)
    sender = public_sender(row)

    created = row.get("created")
    if created is None:
        created = row.get("updated")
    if hasattr(created, "isoformat"):
        try:
            created = created.isoformat(sep=" ")
        except TypeError:
            created = created.isoformat()
    elif created is not None:
        created = str(created)

    if dest_rows is not None:
        mail_tos = public_mail_tos(dest_rows)
    else:
        mail_tos = list(row.get("mail_tos") or [])

    body = row.get("body") or ""
    trunc = False
    if lean:
        body, trunc = lean_body(body, lean_n)

    out: dict = {
        "id": mid,
        "created": created,
        "from": sender["deskId"],
        "sender": sender,
        "body": body,
        "mail_tos": mail_tos,
        # The plain recipient list, as `from` is the plain sender (card 837).
        "to": [d for d in (_to_desk(t) for t in mail_tos) if d],
    }
    if trunc:
        out["body_trunc"] = True
    if crumbs:
        for k in ("tree", "root_id", "root_type", "parent_id", "parent_type"):
            if k in crumbs and crumbs[k] is not None and crumbs[k] != "":
                out[k] = crumbs[k]
    return out


def room_mail_nodes(cn, mail_id: int) -> list[dict]:
    """Mail nodes on this mail's room TREE in nested-set order: {id, lft, rgt}.

    Off-tree mail => [] (caller treats the letter as a room of one).
    """
    from agent_coord.server.records import tree as rec_tree

    crumbs = tree_crumbs(cn, int(mail_id))
    tree_name = str(crumbs.get("tree") or "") if crumbs else ""
    out: list[dict] = []
    seen: set[int] = set()
    if not tree_name:
        return out
    for n in rec_tree.select(cn, tree_name) or []:
        if str(n.get("type") or "") != CONST_MAIL:
            continue
        nid = int(n.get("id") or 0)
        if not nid or nid in seen:
            continue
        seen.add(nid)
        out.append({"id": nid, "lft": int(n.get("lft") or 0), "rgt": int(n.get("rgt") or 0)})
    return out


def public_mail_chain(
    cn, mail_id: int, ids: list[int] | None = None, room: "RoomRead | None" = None
) -> dict:
    """TREE/chain for one mail id as lean MAIL rows.

    ids=None: off-tree mail => chain of [self]; on-tree => every mail node on
    that TREE in nested-set order, each with crumbs. ids given: only those
    letters, in the given order (branch / subtree / summary reads).
    Does not expose opened.
    """
    mid = int(mail_id)
    r = room if room is not None and room.mail_id == mid else RoomRead(cn, mid)
    crumbs = r.crumbs

    if ids is not None:
        mail_ids = [int(i) for i in ids if int(i or 0)]
    else:
        mail_ids = r.ids()

    letters = letters_by_id(cn, mail_ids)
    dests = tos_by_id(cn, mail_ids)
    crumbs_by = r.crumbs_for(cn, mail_ids)

    chain: list[dict] = []
    for nid in mail_ids:
        letter = letters.get(nid)
        if not letter:
            # Fallback: join row from mill_mail_get (may lack sender_roster pre-migrate)
            mrows = get(cn, nid)
            if not mrows:
                continue
            letter = mrows[0]
        chain.append(
            public_mail(letter, dests.get(nid, []), crumbs=crumbs_by.get(nid) or None)
        )

    out: dict = {"id": mid, "chain": chain}
    if crumbs:
        for k in ("tree", "root_id", "root_type", "parent_id", "parent_type"):
            if k in crumbs and crumbs[k] is not None and crumbs[k] != "":
                out[k] = crumbs[k]
    return out


def public_chain(cn, mail_id: int) -> dict:
    """Alias for public_mail_chain (lean TREE/chain)."""
    return public_mail_chain(cn, mail_id)


def to_node_put(cn, mail_id: int, who_id: int) -> dict:
    """mill add mail:ID WHO (#265): recipient on this letter and every letter under it."""
    rows = call(cn, "mill_mail_to_node_put", [int(mail_id), int(who_id)]) or [{}]
    return {k: int(v or 0) for k, v in rows[0].items()}


def to_node_delete(cn, mail_id: int, who_id: int) -> dict:
    """mill remove mail:ID WHO (#265): drop those recipient rows. Refuses an orphan letter."""
    rows = call(cn, "mill_mail_to_node_delete", [int(mail_id), int(who_id)]) or [{}]
    return {k: int(v or 0) for k, v in rows[0].items()}


def dest_count(cn, mail_id: int) -> int:
    n = scalar(
        cn,
        "SELECT COUNT(*) FROM mail_to WHERE type = 'mail' AND id = %s",
        (int(mail_id),),
    )
    return int(n or 0)


def tree_crumbs(cn, mail_id: int) -> dict:
    """parent_id / root_id / tree name for a mail node (empty if not on a plan)."""
    cur = cn.cursor()
    try:
        cur.execute(
            "SELECT n.name AS tree, n.type AS tree_type, anc.type AS anc_type, anc.id AS anc_id, anc.lft"
            " FROM tree AS node"
            " JOIN name n ON n.id = node.name_id"
            " JOIN tree AS anc"
            "   ON anc.name_id = node.name_id"
            "  AND anc.lft <= node.lft AND anc.rgt >= node.rgt"
            " WHERE node.type = 'mail' AND node.id = %s"
            " ORDER BY anc.lft",
            (int(mail_id),),
        )
        rows = cur.fetchall()
        if not rows:
            return {}
        cols = list(cur.column_names)
        packed = [dict(zip(cols, r)) for r in rows]
        return _mail_crumb(packed, int(mail_id))
    finally:
        cur.close()


def room_participants(cn, mail_id: int, room: "RoomRead | None" = None) -> set[str]:
    """Desk names that sent or received (mail_to) any letter on this mail's room.

    Room = the TREE the mail sits on (named via send --room, or opened by reply).
    Off-tree mail => that one letter's sender U mail_tos (plain thread rule).
    Joining a room = mill add mail:ID WHO at a letter of it; you are then a dest.
    Names only (no bodies, no sort); pass room to reuse this request's tree read.
    """
    mid = int(mail_id)
    r = room if room is not None else RoomRead(cn, mid)
    ids = [int(n["id"]) for n in r.nodes]
    if mid not in ids:
        ids.append(mid)
    out: set[str] = set()
    for sender, dests in room_cast_by_id(cn, ids).values():
        if sender:
            out.add(sender)
        out.update(d for d in dests if d)
    return out

class RoomRead:
    """One read of a letter's room per request (perf: one tree read, not 3 to 7).

    crumb(mid) gives the same crumbs as tree_crumbs, nodes the same list as
    room_mail_nodes, tree_id the same id as room_tree_id. Off-tree letter: no tree,
    nodes [], crumbs {}.
    """

    def __init__(self, cn, mail_id: int):
        from agent_coord.server.records import tree as rec_tree

        self.mail_id = int(mail_id)
        self.crumbs = tree_crumbs(cn, self.mail_id)
        self.tree = str(self.crumbs.get("tree") or "") if self.crumbs else ""
        self.tree_id: int | None = None
        self.nodes: list[dict] = []
        self._crumb_by: dict[int, dict] = {}
        if not self.tree:
            return
        rows = rec_tree.select(cn, self.tree) or []
        seen: set[int] = set()
        stack: list[dict] = []
        for n in rows:
            if self.tree_id is None and n.get("name_id") is not None:
                self.tree_id = int(n.get("name_id") or 0) or None
            lft, rgt = int(n.get("lft") or 0), int(n.get("rgt") or 0)
            # Rows come in lft order, so the stack holds exactly this node's ancestors
            # once every node that closed before it (rgt < this rgt) is popped.
            while stack and int(stack[-1]["rgt"]) < rgt:
                stack.pop()
            row = {
                "tree": str(n.get("tree") or self.tree),
                "anc_type": str(n.get("type") or ""),
                "anc_id": int(n.get("id") or 0),
                "lft": lft,
                "rgt": rgt,
            }
            stack.append(row)
            if row["anc_type"] != CONST_MAIL:
                continue
            nid = row["anc_id"]
            if not nid or nid in seen:
                continue
            seen.add(nid)
            self.nodes.append({"id": nid, "lft": lft, "rgt": rgt})
            crumb = _mail_crumb(list(stack), nid)
            if crumb:
                self._crumb_by[nid] = crumb
        if self.tree_id is None:
            self.tree_id = room_tree_id(cn, self.mail_id)

    def crumbs_for(self, cn, mail_ids: list[int]) -> dict[int, dict]:
        """Crumbs for these ids: from the one tree read; a letter off this room by query."""
        ids = _mail_id_list(mail_ids)
        out = {i: self._crumb_by[i] for i in ids if i in self._crumb_by}
        rest = [i for i in ids if i not in out]
        if rest:
            out.update(tree_crumbs_batch(cn, rest))
        return out

    def ids(self) -> list[int]:
        return [int(n["id"]) for n in self.nodes] or [self.mail_id]


def room_participant(cn, mail_id: int, desk: str, room: "RoomRead | None" = None) -> bool:
    """Did this desk send or receive any letter on this mail's room? One EXISTS read.

    Same rule as `desk in room_participants(...)`: off-tree mail is that one letter.
    """
    who = _stored(desk)
    if not who:
        return False
    r = room if room is not None else RoomRead(cn, int(mail_id))
    # Resolve the desk first, then drive from its own letters (mail.idx_desk,
    # mail_to.idx_desk) and probe the tree primary key: a desk that is not in the
    # room costs its own rows only, not the whole room.
    cur = cn.cursor()
    try:
        cur.execute("SELECT id FROM name WHERE name = %s", (who,))
        dids = [int(x[0]) for x in cur.fetchall() if x and x[0]]
    finally:
        cur.close()
    if not dids:
        try:
            _db_commit(cn)  # #818: not inside a request transaction
        except Exception:
            pass
        return False
    marks = ",".join(["%s"] * len(dids))
    if r.tree_id:
        sql = (
            "SELECT 1 FROM mail_to t FORCE INDEX (idx_desk)"
            " JOIN tree x ON x.name_id = %s AND x.type = 'mail' AND x.id = t.id"
            " WHERE t.type = 'mail' AND t.desk_id IN (" + marks + ")"
            " UNION ALL "
            "SELECT 1 FROM mail m FORCE INDEX (idx_desk)"
            " JOIN tree x ON x.name_id = %s AND x.type = 'mail' AND x.id = m.id"
            " WHERE m.type = 'mail' AND m.desk_id IN (" + marks + ")"
            " UNION ALL "
        )
        args: tuple = (int(r.tree_id), *dids, int(r.tree_id), *dids)
    else:
        sql, args = "", ()
    sql += (
        "SELECT 1 FROM mail m WHERE m.type = 'mail' AND m.id = %s"
        " AND m.desk_id IN (" + marks + ")"
        " UNION ALL "
        "SELECT 1 FROM mail_to t WHERE t.type = 'mail' AND t.id = %s"
        " AND t.desk_id IN (" + marks + ")"
        " LIMIT 1"
    )
    args = args + (int(mail_id), *dids, int(mail_id), *dids)
    return scalar_done(cn, sql, args) is not None


def room_cast_by_id(cn, mail_ids: list[int]) -> dict[int, tuple[str, list[str]]]:
    """(sender name, recipient names) per letter. Names only: no bodies, no sort."""
    ids = _mail_id_list(mail_ids)
    if not ids:
        return {}
    marks = ",".join(["%s"] * len(ids))
    cur = cn.cursor()
    try:
        cur.execute(
            "SELECT m.id, s.name, 0 FROM mail m LEFT JOIN name s ON s.id = m.desk_id"
            " WHERE m.type = 'mail' AND m.id IN (" + marks + ")"
            " UNION ALL "
            "SELECT t.id, d.name, 1 FROM mail_to t LEFT JOIN name d ON d.id = t.desk_id"
            " WHERE t.type = 'mail' AND t.id IN (" + marks + ")",
            tuple(ids) + tuple(ids),
        )
        out: dict[int, tuple[str, list[str]]] = {}
        for mid, nm, is_dest in cur.fetchall():
            mid = int(mid or 0)
            if not mid:
                continue
            sender, dests = out.get(mid, ("", []))
            if int(is_dest or 0):
                dests.append(_stored(nm or ""))
            else:
                sender = _stored(nm or "")
            out[mid] = (sender, dests)
        return out
    finally:
        cur.close()
