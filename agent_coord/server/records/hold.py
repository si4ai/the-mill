"""HOLD - mutex on a resource name. Activity type=hold. mill hold / mill drop."""

from __future__ import annotations

from agent_coord.const import CONST_DESK, CONST_ROSTER, CONST_RES
from .db import call, rows_done


def upsert(cn, project: str, desk: str, resource: str) -> list[dict]:
    from agent_coord.server.records.name import bare

    return call(
        cn,
        "mill_hold_upsert",
        [bare(project, CONST_ROSTER), bare(desk, CONST_DESK), bare(resource, CONST_RES)],
    )


def delete(cn, hold_id: int, desk: str) -> list[dict]:
    from agent_coord.server.records.name import bare

    return call(cn, "mill_hold_delete", [int(hold_id), bare(desk, CONST_DESK)])


def select(cn, project: str) -> list[dict]:
    from agent_coord.server.records.name import bare

    return call(cn, "mill_hold_select", [bare(project, CONST_ROSTER) if project else ""])


# mill_hold_select's columns and order, as a plain read with a WHERE (F23).
_FIND_SQL = (
    "SELECT h.type, h.id, h.created, h.updated, h.desk_id, h.resource_id,"
    " dn.name AS desk, dn.type AS desk_type,"
    " an.name AS roster, an.type AS roster_type,"
    " rn.name AS resource, rn.type AS resource_type,"
    " (SELECT CONCAT('[', GROUP_CONCAT(JSON_QUOTE(ln.name) ORDER BY l.ord, ln.name SEPARATOR ','), ']')"
    "    FROM label l JOIN name ln ON ln.id = l.name_id"
    "   WHERE l.type = 'hold' AND l.id = h.id) AS labels"
    " FROM hold h"
    " LEFT JOIN activity a ON a.type = 'hold' AND a.id = h.id"
    " LEFT JOIN name dn ON dn.id = h.desk_id"
    " LEFT JOIN name an ON an.id = a.roster_id"
    " LEFT JOIN name rn ON rn.id = h.resource_id"
)
# Any name type, the way the old python loop compared names (idx_type range).
_NAME_IDS = (
    "(SELECT n.id FROM name n"
    " WHERE n.type IN ('desk','roster','label','tree','res') AND n.name = %s)"
)


def find(cn, *, desk: str = "", resource: str = "", held: bool = False) -> list[dict]:
    """mill_hold_select rows narrowed in SQL (F23): one desk, one resource, held only.

    desk uses fk_hold_desk, resource the unique idx_hold. The name match is the
    index's (case and accent blind); callers keep their exact compare, so a
    near-miss name reads the same as before.
    """
    from agent_coord.server.records.name import bare

    where: list[str] = []
    args: list[str] = []
    who = bare(desk, CONST_DESK) if str(desk or "").strip() else ""
    res = bare(resource, CONST_RES) if str(resource or "").strip() else ""
    if who:
        where.append("h.desk_id IN " + _NAME_IDS)
        args.append(who)
    if res:
        where.append("h.resource_id IN " + _NAME_IDS)
        args.append(res)
    if held:
        where.append("h.desk_id IS NOT NULL")
    sql = _FIND_SQL + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY h.id"
    return rows_done(cn, sql, tuple(args))


def own(cn, desk: str) -> list[dict]:
    """Holds this desk owns. A free row (no desk) is omitted.

    since is the row's updated time. created stays at the first insert and does
    not move when a freed row is taken again, so it is the wrong held-since.
    The resource is the stored name. A path such as docs/a.md is kept as stored.
    """
    from agent_coord.server.records.name import bare

    who = bare(desk, CONST_DESK) if str(desk or "").strip() else ""
    if not who:
        return []
    out: list[dict] = []
    for rec in find(cn, desk=who):
        holder = bare(str(rec.get("desk") or ""), CONST_DESK)
        if not holder or holder != who:
            continue
        resource = rec.get("resource")
        if resource is None or str(resource) == "":
            continue
        out.append({"resource": resource, "since": rec.get("updated")})
    return out


def peek(cn, project: str, resource: str) -> dict:
    """Who holds this resource. Does not insert, take, or refresh (#223).

    A missing row and a freed row are both free: owner is null and held is false.
    since is the row's updated time when a row exists.
    """
    from agent_coord.server.records.name import bare

    want = bare(resource, CONST_RES)
    for rec in find(cn, resource=want) if want else []:
        got = bare(str(rec.get("resource") or ""), CONST_RES)
        if got != want:
            continue
        holder = bare(str(rec.get("desk") or ""), CONST_DESK)
        return {
            "ok": True,
            "peek": True,
            "resource": got or resource,
            "id": rec.get("id"),
            "owner": holder or None,
            "held": bool(holder),
            "since": rec.get("updated"),
        }
    return {
        "ok": True,
        "peek": True,
        "resource": want or resource,
        "id": None,
        "owner": None,
        "held": False,
        "since": None,
    }


def seat_connected(cn, desk: str) -> bool:
    """True when the desk has a live connected seat (floor alive; F223).

    Floor definition (sp_floor_scope / glance): time_connect is set and
    time_disconnect is null or not after time_connect. A missing seat, a never-
    connected seat, or a socket-down seat is not connected.
    """
    from agent_coord.server.records.db import scalar_done
    from agent_coord.server.records.name import bare

    who = bare(desk, CONST_DESK) if str(desk or "").strip() else ""
    if not who:
        return False
    return (
        scalar_done(
            cn,
            "SELECT 1 FROM seat j JOIN name n ON n.id = j.desk_id"
            " AND n.type = 'desk' AND n.name = %s AND n.deleted IS NULL"
            " WHERE j.time_connect IS NOT NULL"
            "   AND (j.time_disconnect IS NULL OR j.time_connect >= j.time_disconnect)"
            " LIMIT 1",
            (who,),
        )
        is not None
    )


def hold_since(rec: dict):
    """Held-since timestamp for stale age (activity take time preferred; else hold.updated)."""
    return rec.get("activity_updated") or rec.get("updated")


def _hold_age_days(cn, hold_id: int, since) -> float | None:
    """Age of the hold in days from since (or activity.updated / hold.updated)."""
    from datetime import datetime, timezone

    from agent_coord.server.records.db import scalar_done

    raw = since
    if raw is None and hold_id:
        raw = scalar_done(
            cn,
            "SELECT COALESCE("
            " (SELECT a.updated FROM activity a WHERE a.type = 'hold' AND a.id = %s),"
            " (SELECT h.updated FROM hold h WHERE h.id = %s))",
            (int(hold_id), int(hold_id)),
        )
    if raw is None:
        return None
    if isinstance(raw, datetime):
        at = raw.replace(tzinfo=None) if raw.tzinfo else raw
    else:
        s = str(raw).strip().replace("T", " ").replace("Z", "").split("+")[0].strip()
        try:
            at = datetime.fromisoformat(s)
        except ValueError:
            return None
        if at.tzinfo:
            at = at.replace(tzinfo=None)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return max(0.0, (now - at).total_seconds() / 86400.0)


def may_drop_other(cn, actor: str, holder: str, *, hold_id: int = 0, since=None) -> tuple[bool, str]:
    """May actor drop holder's hold? (F223). Returns (allowed, refusal_reason)."""
    from agent_coord.config import hold_stale_days, mill_trust
    from agent_coord.server.admin.guard import is_role_admin

    if is_role_admin(cn, actor):
        return True, ""
    if mill_trust() == "limited":
        return False, (
            f"drop: held by {holder}, not you "
            f"(limited trust: only the holder or Admin may drop)"
        )
    if seat_connected(cn, holder):
        return False, (
            f"drop: held by {holder}, not you "
            f"(holder is connected; Admin only for a live hold)"
        )
    age = _hold_age_days(cn, hold_id, since)
    need = hold_stale_days()
    if age is None or age < float(need):
        return False, (
            f"drop: held by {holder}, not you "
            f"(stale needs holder disconnected and held {need}+ days; Admin only until then)"
        )
    return True, ""


def delete_other(cn, hold_id: int, actor: str, *, expect: str) -> list[dict]:
    """Release another desk's hold as actor (card 931). Auth checked by caller.

    expect is the holder the caller approved against; the SP refuses when the
    row's holder no longer matches (check-then-act race guard).
    """
    from agent_coord.server.records.name import bare

    return call(
        cn,
        "mill_hold_release_other",
        [int(hold_id), bare(actor, CONST_DESK), bare(expect, CONST_DESK)],
    )


def drop(cn, project: str, desk: str, resource: str) -> dict:
    """Release the lock. Own hold: always. Other desk's hold: Admin, or high-trust stale (F223).

    The row stays, desk_id NULL. Reply: released true/false, owner is who holds it
    now (null once released), was_owner is the desk that let go. A drop of another's
    hold writes the drop move by the acting desk with peer_id = the holder; the
    holder's seat token is untouched.
    """
    from agent_coord.server.records.name import bare

    want = bare(resource, CONST_RES)
    who = bare(desk, CONST_DESK)
    other = ""
    for rec in find(cn, resource=want) if want else []:
        got = bare(str(rec.get("resource") or ""), CONST_RES)
        holder = bare(str(rec.get("desk") or ""), CONST_DESK)
        if got != want:
            continue
        nid = int(rec.get("id") or 0)
        if not holder:
            # Freed row still present; not held by anyone (same as a missing row).
            continue
        if holder == who:
            released = delete(cn, nid, desk)
            ok = bool(released) and int((released[0] or {}).get("ok") or 0) == 1
            if ok:
                return {
                    "ok": True,
                    "released": True,
                    "resource": got or resource,
                    "id": nid,
                    "owner": None,
                    "was_owner": holder or desk,
                }
            return {
                "ok": False,
                "released": False,
                "resource": got or resource,
                "id": nid,
                "owner": holder or None,
                "reason": "release refused",
            }
        other = other or holder
        allowed, reason = may_drop_other(
            cn, who, holder, hold_id=nid, since=None
        )
        if not allowed:
            return {
                "ok": False,
                "released": False,
                "resource": got or resource,
                "id": nid,
                "owner": holder or None,
                "reason": reason,
            }
        released = delete_other(cn, nid, desk, expect=holder)
        ok = bool(released) and int((released[0] or {}).get("ok") or 0) == 1
        if ok:
            return {
                "ok": True,
                "released": True,
                "resource": got or resource,
                "id": nid,
                "owner": None,
                "was_owner": holder,
            }
        sp_reason = str((released[0] or {}).get("reason") or "").strip() if released else ""
        now_owner = holder
        for again in find(cn, resource=want) if want else []:
            got2 = bare(str(again.get("resource") or ""), CONST_RES)
            if got2 != want:
                continue
            now_owner = bare(str(again.get("desk") or ""), CONST_DESK) or ""
            break
        else:
            # Row gone or no longer held: do not report the stale expect holder.
            now_owner = ""
        if sp_reason.lower() in ("already free", "gone"):
            now_owner = ""
        return {
            "ok": False,
            "released": False,
            "resource": got or resource,
            "id": nid,
            "owner": now_owner or None,
            "reason": sp_reason or "release refused",
        }
    return {
        "ok": False,
        "released": False,
        "resource": want or resource,
        "owner": other or None,
        "reason": f"held by {other}, not you" if other else "not held by you",
    }
