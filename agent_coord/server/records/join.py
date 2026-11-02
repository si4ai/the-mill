"""A desk's seat (one row per desk, table seat) and its doing entries (#818).

The seat is per-desk state, not an activity. doing rows are the activity:
append-only, the newest is the desk's current doing."""

from __future__ import annotations

from agent_coord.const import CONST_DESK, CONST_ROSTER
from agent_coord.helpers.ident import (
    STABLE_HUMANS,
    is_stable_human,
)

from .db import call, rows_done


def upsert(
    cn,
    project: str,
    desk: str,
    role: str = "",
    token_hash: str | None = None,
    doing: str | None = None,
) -> list[dict]:
    from agent_coord.server.records.doing_stack import PLACEHOLDERS
    from agent_coord.server.records.name import bare

    # #818 PR B: join and invite placeholders ("present", "invited") are not
    # something a desk is doing, so they never become a doing entry.
    if doing is not None and doing.strip() in PLACEHOLDERS:
        doing = None
    return call(
        cn,
        "mill_join_upsert",
        [
            bare(project, CONST_ROSTER),
            bare(desk, CONST_DESK),
            bare(role, CONST_ROSTER) if role else "",
            token_hash,
            doing,
        ],
    )


def note_connect(cn, desk: str, *, startup_ms: int | None = None) -> None:
    """Record that this desk opened /ws. Does not touch token_hash or lan_ip."""
    from agent_coord.server.records.name import bare

    if not (desk or "").strip():
        return
    rows = call(cn, "mill_join_connect", [bare(desk, CONST_DESK)]) or []
    jid = (rows[0] or {}).get("id") if rows else None
    desk_id = int((rows[0] or {}).get("desk_id") or 0) if rows else 0
    # Card 1028: D2 connect transition (soft-fail; ids only).
    try:
        from agent_coord.server import connect_activity as ca

        if desk_id <= 0:
            desk_id = int(ca.desk_id_for(cn, desk) or 0)
        if desk_id > 0:
            ca.emit_connect(cn, desk_id=desk_id, startup_ms=startup_ms)
    except Exception:
        pass
    if not jid:
        return
    from agent_coord.server.push import fanout

    # The connecting desk is not sitting yet; do not queue its own DOING back to it.
    fanout(cn, "doing", int(jid), "DOING", skip_desk=desk)


def mark_socket(cn, desk: str, *, up: bool) -> None:
    """First /ws sets time_connect and clears time_disconnect. Last socket sets time_disconnect."""
    from agent_coord.server.records.name import bare

    if not (desk or "").strip():
        return
    try:
        rows = call(cn, "mill_join_socket", [bare(desk, CONST_DESK), 1 if up else 0]) or []
        # Card 1028: last socket down -> D3 disconnect.
        if not up:
            try:
                from agent_coord.server import connect_activity as ca

                desk_id = int((rows[0] or {}).get("desk_id") or 0) if rows else 0
                if desk_id <= 0:
                    desk_id = int(ca.desk_id_for(cn, desk) or 0)
                if desk_id > 0:
                    ca.emit_disconnect(cn, desk_id=desk_id)
            except Exception:
                pass
    except Exception:
        try:
            cn.rollback()
        except Exception:
            pass


def set_lan_ip(cn, desk: str, ip: str) -> None:
    """Record the workstation LAN address on this desk's join row."""
    from agent_coord.server.records.name import bare

    ip_s = (ip or "").strip()[:45]
    if not ip_s or not desk:
        return
    try:
        call(cn, "mill_join_lan", [bare(desk, CONST_DESK), ip_s])
    except Exception:
        try:
            cn.rollback()
        except Exception:
            pass


def touch(cn, project: str, desk: str) -> list[dict]:
    """Bump the seat; no doing row and no activity bump (#635, #818; 0.8.0 heartbeats)."""
    from agent_coord.server.records.name import bare

    desk_b = bare(desk, CONST_DESK) if desk else ""
    if not desk_b:
        return []
    rows = call(cn, "mill_join_touch", [desk_b]) or []
    if not rows or not (rows[0] or {}).get("id"):
        return []
    return rows


def delete(cn, project: str, desk: str) -> list[dict]:
    from agent_coord.server.records.name import bare

    return call(cn, "mill_join_delete", [bare(project, CONST_ROSTER), bare(desk, CONST_DESK)])


def reset(cn, project: str, desk: str) -> list[dict]:
    """Clear token_hash so the desk name can mill join again (lost hash)."""
    from agent_coord.server.records.name import bare

    return call(cn, "mill_join_reset", [bare(project, CONST_ROSTER), bare(desk, CONST_DESK)])


def select(cn, project: str) -> list[dict]:
    from agent_coord.server.records.name import bare

    return call(cn, "mill_join_select", [bare(project, CONST_ROSTER) if project else ""])


def seen(cn, project: str, desk_ids: list[int]) -> dict[int, object]:
    """desk_id -> the seat's updated (else created), for seats mill_join_select
    would list for project. Missing desks are absent. One read on idx_desk (F23)."""
    from agent_coord.server.records.name import bare

    ids = sorted({int(d) for d in desk_ids or [] if d})
    if not ids:
        return {}
    marks = ",".join(["%s"] * len(ids))
    proj = bare(project, CONST_ROSTER) if project else ""
    # Same visibility as mill_join_select: token or a past disconnect (F190).
    live = " AND (h.token_hash IS NOT NULL OR h.time_disconnect IS NOT NULL)"
    if proj:
        sql = (
            "SELECT h.desk_id, h.updated, h.created FROM seat h"
            " JOIN member m ON m.desk_id = h.desk_id"
            " AND m.name_id = IFNULL((SELECT MILL_NAME_GET('roster', %s)), 0)"
            " WHERE h.desk_id IN (" + marks + ")" + live
        )
        args: tuple = (proj, *ids)
    else:
        sql = (
            "SELECT h.desk_id, h.updated, h.created FROM seat h"
            " WHERE h.desk_id IN (" + marks + ")" + live
        )
        args = tuple(ids)
    out: dict[int, object] = {}
    for r in rows_done(cn, sql, args):
        did = int(r.get("desk_id") or 0)
        if did and did not in out:
            out[did] = r.get("updated") or r.get("created")
    return out


def _fetchone(cn, sql: str, args: tuple):
    cur = cn.cursor()
    try:
        cur.execute(sql, args)
        return cur.fetchone()
    finally:
        try:
            cur.close()
        except Exception:
            pass


def desk_for_token_hash(cn, digest: str) -> str:
    """Desk whose seat.token_hash equals digest. Empty when none or retired (#608).

    Point lookup. Does not call mill_join_select.
    """
    digest = (digest or "").strip()
    if not digest:
        return ""
    find_hash = (
        "SELECT d.name FROM seat j "
        "JOIN name d ON d.id = j.desk_id AND d.type = 'desk' AND d.deleted IS NULL "
        "WHERE j.token_hash = %s LIMIT 1"
    )
    row = _fetchone(cn, find_hash, (digest,))
    if not row or row[0] is None:
        return ""
    return str(row[0]).strip()


def token_hash_for_desk(cn, desk: str) -> str | None:
    """Stored token_hash for this desk. None when that seat row is absent or the desk is retired (#608)."""
    from agent_coord.server.records.name import bare

    desk_b = bare(desk, CONST_DESK) if (desk or "").strip() else ""
    if not desk_b:
        return None
    find_desk = (
        "SELECT j.token_hash FROM seat j "
        "JOIN name d ON d.id = j.desk_id AND d.type = 'desk' AND d.deleted IS NULL "
        "WHERE d.name = %s LIMIT 1"
    )
    row = _fetchone(cn, find_desk, (desk_b,))
    if row is None:
        return None
    raw = row[0]
    return "" if raw is None else str(raw)


def token_matches(cn, desk: str, digest: str) -> bool:
    """True when this desk's stored token_hash equals digest."""
    digest = (digest or "").strip()
    if not digest:
        return False
    stored = token_hash_for_desk(cn, desk)
    return bool(stored) and stored == digest


def prune_dead(cn) -> dict:
    """Count join seats with no token_hash. Deletes nothing.

    #96 (join-desk-restrict-no-delete): a null token_hash is disconnect history,
    not prune fodder. The join row and its activity row stay. ``pruned`` is
    always 0; ``dead`` is how many seats have no token.
    """
    cur = cn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM seat WHERE token_hash IS NULL OR token_hash = ''"
    )
    n = int((cur.fetchone() or [0])[0] or 0)
    cur.execute("SELECT COUNT(*) FROM seat")
    left = int((cur.fetchone() or [0])[0] or 0)
    return {
        "ok": True,
        "pruned": 0,
        "dead": n,
        "join_left": left,
        "note": "seats with no token_hash are kept as disconnect history (#96)",
    }


def wake_arm(cn, desk: str, url: str, key: str, wake_on: str = "addressed") -> list[dict]:
    """#618: store the desk's webhook URL and its own key; delivery becomes webhook.
    #628: wake_on is all or addressed (room-only items do not POST)."""
    from agent_coord.server.records.name import bare

    return call(cn, "mill_join_wake_arm", [bare(desk, CONST_DESK), url, key, wake_on])


def wake_off(cn, desk: str) -> list[dict]:
    """#618: forget the URL and key; delivery goes back to websocket."""
    from agent_coord.server.records.name import bare

    return call(cn, "mill_join_wake_off", [bare(desk, CONST_DESK)])


def wake_state(cn, desk: str) -> dict:
    """{armed, host, wake_on} for one desk. The read never carries the URL path or the key."""
    from agent_coord.server.records.name import bare

    rows = call(cn, "mill_join_wake_state", [bare(desk, CONST_DESK)]) or []
    row = rows[0] if rows else {}
    return {
        "armed": bool(int(row.get("armed") or 0)),
        "host": str(row.get("host") or ""),
        "wake_on": str(row.get("wake_on") or "addressed"),
    }


def wake_target(cn, desk: str) -> tuple[str, str] | None:
    """(url, key) of an armed live desk, for the POST only. Never log or return it."""
    from agent_coord.server.records.name import bare

    rows = call(cn, "mill_join_wake_target", [bare(desk, CONST_DESK)]) or []
    if not rows:
        return None
    url = str(rows[0].get("endpoint_url") or "")
    key = str(rows[0].get("endpoint_key") or "")
    return (url, key) if url and key else None
