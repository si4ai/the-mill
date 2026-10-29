"""b_trust(): the book's copy of config.toml's trust level (0.8.0, schema-design.md section 9).

The procedures read b_trust() and never take trust as an argument. One routine
re-creates the function: init_trust_fn, at server startup (before the first
request) and on `mill trust high|limited` after config.toml is written. It runs
on its own connection under the config.toml login (the one `migrate.ensure`
installs routines with), so the DDL never commits a request transaction.

A book with no b_trust() (main's shape) is left alone.
"""

from __future__ import annotations

from typing import Any

LEVELS = ("high", "limited")
# Main's spellings that mean limited (config.mill_trust).
_LIMITED = ("limited", "low", "strict")


class TrustLevelError(ValueError):
    """config.toml trust holds something that is not a trust level."""


def config_level(raw: Any = None) -> str:
    """The level config.toml (or AGENT_COORD_TRUST) asks for: high when the key is absent.

    Any value that is not a trust level raises TrustLevelError, so the server does not start on it.
    """
    if raw is None:
        from agent_coord.config import settings

        raw = settings().get("trust")
    if raw is None or str(raw).strip() == "":
        return "high"
    s = str(raw).strip().lower()
    if s == "high":
        return "high"
    if s in _LIMITED:
        return "limited"
    raise TrustLevelError(f"config.toml trust = {str(raw)!r} is not a trust level: use high or limited")


def _database(cn) -> str:
    db = getattr(cn, "database", None)
    if callable(db):
        db = db()
    if not db:
        from agent_coord.server.records.db import conn_kwargs

        db = conn_kwargs().get("database")
    return str(db or "")


def _has_fn(cur, db: str) -> bool:
    cur.execute(
        "SELECT 1 FROM information_schema.ROUTINES"
        " WHERE ROUTINE_SCHEMA = %s AND ROUTINE_TYPE = 'FUNCTION' AND ROUTINE_NAME = 'b_trust' LIMIT 1",
        (db,),
    )
    return cur.fetchone() is not None


def init_trust_fn(cn, level: str | None = None) -> str | None:
    """Re-create b_trust() in cn's book with `level` (default: config.toml's). Returns the level set,
    or None when the book has no b_trust() (main's shape: left alone)."""
    import mysql.connector

    from agent_coord.server.records.db import conn_kwargs

    want = config_level(level) if level is not None else config_level()
    if want not in LEVELS:  # config_level only answers a level; keep the SQL literal closed
        raise TrustLevelError(f"trust {want!r} is not a trust level")
    kw = conn_kwargs()
    kw["database"] = _database(cn)
    kw["autocommit"] = True
    own = mysql.connector.connect(**kw)
    try:
        cur = own.cursor()
        try:
            if not _has_fn(cur, kw["database"]):
                return None
            cur.execute("DROP FUNCTION IF EXISTS b_trust")
            cur.execute(
                "CREATE FUNCTION b_trust() RETURNS VARCHAR(8) DETERMINISTIC NO SQL RETURN '%s'" % want
            )
        finally:
            cur.close()
    finally:
        own.close()
    return want
