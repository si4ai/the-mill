"""Throwaway beta book (card 868): beta_ddl.sql + beta_sp.sql on a fresh MySQL schema.

The beta files are a proposal under docs/requirements/beta/, outside the pack (F160).

Used by the beta SQL suites. No SPIN, no server: one connection, seconds of runtime.
"""
from __future__ import annotations

import os
from pathlib import Path

from agent_coord.install.migrate import split_script
from tests.sql_isolate import throwaway_db

BETA_DIR = Path(__file__).resolve().parents[1] / "docs" / "requirements" / "beta"


def admin_conn():
    import mysql.connector

    from agent_coord.server.records.db import conn_kwargs

    kw = conn_kwargs()
    kw.pop("database", None)
    kw["autocommit"] = True
    return mysql.connector.connect(**kw), kw


def apply_file(cn, name: str) -> int:
    blob = (BETA_DIR / name).read_text(encoding="utf-8")
    cur = cn.cursor()
    n = 0
    try:
        for stmt in split_script(blob):
            cur.execute(stmt)
            n += 1
            if cur.with_rows:
                cur.fetchall()
    finally:
        cur.close()
    return n


def make_book(prefix: str, *, sp: bool = True):
    """Fresh schema `prefix_<pid>` with the beta DDL (and SPs). Returns (connection, db name)."""
    import mysql.connector

    adm, kw = admin_conn()
    db = throwaway_db(prefix)
    cur = adm.cursor()
    cur.execute(f"DROP DATABASE IF EXISTS `{db}`")
    cur.execute(f"CREATE DATABASE `{db}` DEFAULT CHARACTER SET utf8mb4 DEFAULT COLLATE utf8mb4_0900_ai_ci")
    cur.close()
    adm.close()
    cn = mysql.connector.connect(database=db, **kw)
    apply_file(cn, "beta_ddl.sql")
    if sp:
        apply_file(cn, "beta_sp.sql")
    return cn, db


def set_trust(cn, level: str) -> None:
    """Re-create b_trust() with `level`, as the server does from config.toml at startup and on `mill trust`."""
    assert level in ("high", "limited"), level
    cur = cn.cursor()
    try:
        cur.execute("DROP FUNCTION IF EXISTS b_trust")
        cur.execute(f"CREATE FUNCTION b_trust() RETURNS VARCHAR(8) DETERMINISTIC NO SQL RETURN '{level}'")
    finally:
        cur.close()


def drop_book(cn, db: str) -> None:
    if os.environ.get("MILL_KEEP_TEST_DB"):
        return
    cur = cn.cursor()
    try:
        cur.execute(f"DROP DATABASE IF EXISTS `{db}`")
    finally:
        cur.close()
        cn.close()
