"""name table. id is the primary key. type plus the bare string is unique."""

from __future__ import annotations

from agent_coord.const import (
    CONST_ALIAS_FILE,
    CONST_ALIAS_PROJ,
    CONST_ALIAS_RESOURCE,
    CONST_ROSTER,
    CONST_RES,
    CONST_ROSTER,
    NAME_TYPES,
)

from .db import call, rows_done, scalar, scalar_done

_KINDS = NAME_TYPES


def bare(name: str, kind: str) -> str:
    """Stored name for a known kind."""
    _k, stored = pair(name or "", kind)
    return stored


def pair(name: str, kind: str = "") -> tuple[str, str]:
    """(type, stored name). The stored name is the string given."""
    raw = (name or "").strip()
    k = (kind or "").strip().lower()
    if k == CONST_ALIAS_PROJ:
        k = CONST_ROSTER
    if k in (CONST_ALIAS_FILE, CONST_ALIAS_RESOURCE):
        k = CONST_RES
    if k not in _KINDS:
        raise ValueError(
            "kind must be "
            + ", ".join(_KINDS[:-1])
            + f", or {_KINDS[-1]}: {kind!r}"
        )
    return k, raw


def roster_name(name: str) -> str:
    """Stored name for a letter/card roster (one name type since 0.7.0)."""
    raw = (name or "").strip()
    if not raw:
        return ""
    return bare(raw, CONST_ROSTER)


def roster_ids(cn, names: list[str]) -> list[tuple[str, int]]:
    """Resolve many roster names in one read: [(requested name, id)], input order.

    Same rule as the SPs: a live roster. Unknown or retired
    names are skipped (never minted). A second name that resolves to an id already
    listed is dropped.
    """
    wanted: list[str] = []
    for raw in names or []:
        s = roster_name(str(raw or ""))
        if s and s not in wanted:
            wanted.append(s)
    if not wanted:
        return []
    marks = ",".join(["%s"] * len(wanted))
    cur = cn.cursor()
    try:
        cur.execute(
            "SELECT id, type, name FROM name"
            " WHERE type = 'roster' AND deleted IS NULL"
            " AND name IN (" + marks + ")",
            tuple(wanted),
        )
        rows = list(cur.fetchall())
    finally:
        cur.close()
    best: dict[str, tuple[str, int]] = {}
    for rid, rtype, rname in rows:
        if isinstance(rname, (bytes, bytearray)):
            rname = rname.decode("utf-8")
        if isinstance(rtype, (bytes, bytearray)):
            rtype = rtype.decode("utf-8")
        key = str(rname).casefold()
        have = best.get(key)
        if have is None:
            best[key] = (str(rtype), int(rid))
    out: list[tuple[str, int]] = []
    seen: set[int] = set()
    for s in wanted:
        hit = best.get(s.casefold())
        if hit is None or hit[1] in seen:
            continue
        seen.add(hit[1])
        out.append((s, hit[1]))
    return out


def get_or_insert(cn, name: str, kind: str = "") -> int:
    k, bare = pair(name, kind)
    nid = int(scalar(cn, "SELECT MILL_NAME_PUT(%s, %s)", (k, bare)))
    from agent_coord.server.records.db import commit as _db_commit

    _db_commit(cn)  # #818: not inside a request transaction
    return nid


def by_id(cn, nid: int | None) -> str:
    if not nid:
        return ""
    rec = scalar(cn, "SELECT name FROM name WHERE id=%s", (nid,))
    if rec is None:
        return ""
    if isinstance(rec, (bytes, bytearray)):
        rec = rec.decode("utf-8")
    return str(rec)


def get(cn, name: str, kind: str = "") -> int | None:
    try:
        k, bare = pair(name, kind)
    except ValueError:
        bare = (name or "").strip()
        k = ""
    if k:
        rec = scalar(
            cn,
            "SELECT id FROM name WHERE type=%s AND name=%s AND deleted IS NULL",
            (k, bare),
        )
    else:
        rec = scalar(
            cn,
            "SELECT id FROM name WHERE name=%s AND deleted IS NULL",
            (bare,),
        )
    return int(rec) if rec is not None else None


def _text(v) -> str:
    if isinstance(v, (bytes, bytearray)):
        return v.decode("utf-8")
    return str(v)


def live_roster(cn, name: str) -> str | None:
    """Stored name of the live roster that matches name, or None. One indexed
    read (idx_type). The match is the column's (case and accent blind); callers
    that need the exact name compare the result (F23)."""
    who = (name or "").strip()
    if not who:
        return None
    rec = scalar_done(
        cn,
        "SELECT name FROM name WHERE type=%s AND name=%s AND deleted IS NULL",
        (CONST_ROSTER, who),
    )
    return None if rec is None else _text(rec)


def live_roster_names(cn) -> list[str]:
    """Live roster names in id order, without the rest of the catalog (F23)."""
    rows = rows_done(
        cn,
        "SELECT name FROM name WHERE type=%s AND deleted IS NULL ORDER BY id",
        (CONST_ROSTER,),
    )
    return [_text(r.get("name") or "") for r in rows]


def select(cn, *, include_deleted: bool = False) -> list[dict]:
    cur = cn.cursor()
    try:
        where = "" if include_deleted else " WHERE deleted IS NULL"
        cur.execute(
            "SELECT id, type, updated, name, type AS name_type, deleted FROM name"
            + where
            + " ORDER BY id"
        )
        cols = list(cur.column_names)
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        cur.close()


# 0.8.0: the lifecycle verbs are sp_name_* (sp_beta_name.sql). `by` is the acting
# desk's name: the procedure checks Admin (and b_trust() for a mint) itself. A desk
# acts on itself (rename, retire) only with its own seat's token hash (`by_hash`).


def _by(by: str) -> str:
    return bare(by, "desk")


def retire(cn, name: str, kind: str = "", *, by: str, by_hash: str | None = None) -> list[dict]:
    k, bare_name = pair(name, kind)
    return call(cn, "sp_name_retire", [_by(by), by_hash, k, bare_name])


def rename(cn, old: str, new: str, kind: str = "", *, by: str, by_hash: str | None = None) -> list[dict]:
    k, old_b = pair(old, kind)
    _k2, new_b = pair(new, k)
    return call(cn, "sp_name_rename", [_by(by), by_hash, k, old_b, new_b])


def reclaim(cn, name: str, kind: str = "", *, by: str) -> list[dict]:
    k, bare_name = pair(name, kind)
    return call(cn, "sp_name_reclaim", [_by(by), k, bare_name])


def host_put(cn, name: str, kind: str = "") -> list[dict]:
    """Host path (first-use label in rpc, server setup): MILL_NAME_PUT, which refuses a roster or label at limited trust."""
    k, bare = pair(name, kind)
    return call(cn, "mill_name_host", [k, bare])


def mint(cn, name: str, kind: str = "", *, by: str) -> list[dict]:
    """Get or mint a roster, label, tree or res name as desk `by` (sp_name_mint: op created or exists)."""
    k, bare_name = pair(name, kind)
    return call(cn, "sp_name_mint", [_by(by), k, bare_name])


def ensure_roster(cn, name: str, kind: str = CONST_ROSTER) -> int:
    """Get-or-insert a roster."""
    from agent_coord.config import mill_catalog_open
    from agent_coord.helpers.errors import CoordError

    k, bare = pair(name, kind)
    if k != CONST_ROSTER:
        raise CoordError("roster kind is roster")
    existing = get(cn, bare, k)
    if existing is not None:
        return existing
    if not mill_catalog_open(k):
        raise CoordError(
            f"limited-trust: cannot auto-create {k} {bare} - Admin mill roster NAME NAME --yes"
        )
    return get_or_insert(cn, bare, k)
