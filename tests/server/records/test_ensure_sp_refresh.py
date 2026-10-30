"""migrate.ensure refreshes sp_name / sp_member / sp_join on an existing book.

A live book that only runs ensure kept a stale mill_join_upsert (and
mill_member_put / mill_member_delete) that called mill_watcher_put('name', ...)
after tip mill_watcher_put dropped 'name' from its ENUM. The seat mint then
failed with 1265. ensure must bring those callers to tip with the watcher SPs.
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.sql

from agent_coord.install import migrate
from agent_coord.server.records import apply, connect
from agent_coord.server.records.db import conn_kwargs as _conn_kwargs
from tests.sql_isolate import throwaway_db

TEST_DB = throwaway_db("mill_ensure_sp_refresh_test")

# Old-shape callers: one statement each, so no DELIMITER is needed.
_STALE = {
    "mill_join_upsert": "CREATE PROCEDURE mill_join_upsert() CALL mill_watcher_put('name', 1, 1)",
    "mill_member_put": "CREATE PROCEDURE mill_member_put() CALL mill_watcher_put('name', 1, 1)",
    "mill_member_delete": "CREATE PROCEDURE mill_member_delete() CALL mill_watcher_delete('name', 1, 1)",
}


def _cn():
    import mysql.connector

    kw = _conn_kwargs()
    kw.pop("database", None)
    kw["autocommit"] = True
    admin = mysql.connector.connect(**kw)
    cur = admin.cursor()
    cur.execute(
        f"CREATE DATABASE IF NOT EXISTS `{TEST_DB}` "
        "DEFAULT CHARACTER SET utf8mb4 DEFAULT COLLATE utf8mb4_0900_ai_ci"
    )
    cur.close()
    admin.close()
    os.environ["AGENT_COORD_DATABASE"] = TEST_DB
    cn = connect(TEST_DB)
    apply(cn, wipe=True)
    return cn


@pytest.fixture(scope="module")
def cn():
    try:
        c = _cn()
    except Exception as e:
        pytest.skip(f"mysql mill records: {e}")
    yield c
    c.close()


def _exec(cn, sql: str) -> None:
    cur = cn.cursor()
    try:
        cur.execute(sql)
        cn.commit()
    finally:
        cur.close()


def _body(cn, name: str) -> str:
    cur = cn.cursor()
    try:
        cur.execute(
            "SELECT ROUTINE_DEFINITION FROM information_schema.ROUTINES "
            "WHERE ROUTINE_SCHEMA = DATABASE() AND ROUTINE_NAME = %s "
            "AND ROUTINE_TYPE = 'PROCEDURE'",
            (name,),
        )
        row = cur.fetchone()
    finally:
        cur.close()
    assert row is not None, name
    return str(row[0] or "")


def _watcher_type_enum(cn, proc: str) -> str:
    cur = cn.cursor()
    try:
        cur.execute(
            "SELECT DTD_IDENTIFIER FROM information_schema.PARAMETERS "
            "WHERE SPECIFIC_SCHEMA = DATABASE() AND SPECIFIC_NAME = %s "
            "AND PARAMETER_NAME = 'p_type'",
            (proc,),
        )
        row = cur.fetchone()
    finally:
        cur.close()
    assert row is not None, proc
    return str(row[0]).lower()


def _name_watcher_calls(body: str) -> bool:
    low = body.lower().replace(" ", "")
    return "mill_watcher_put('name'" in low or "mill_watcher_delete('name'" in low


def _plant_stale(cn) -> None:
    for name, create in _STALE.items():
        _exec(cn, f"DROP PROCEDURE IF EXISTS {name}")
        _exec(cn, create)


def test_tip_watcher_enum_has_no_name(cn) -> None:
    for proc in ("mill_watcher_put", "mill_watcher_delete"):
        enum = _watcher_type_enum(cn, proc)
        assert "'doing'" in enum and "'join'" not in enum
        assert "'name'" not in enum, proc


def test_stale_join_upsert_fails_against_tip_watcher(cn) -> None:
    """The live failure: the old caller hits the tip ENUM (1265 under strict mode)."""
    import mysql.connector

    _plant_stale(cn)
    cur = cn.cursor()
    try:
        with pytest.raises(mysql.connector.Error) as ei:
            cur.execute("CALL mill_join_upsert()")
        cn.rollback()
    finally:
        cur.close()
    assert ei.value.errno == 1265


def test_ensure_refreshes_name_watcher_callers(cn) -> None:
    _plant_stale(cn)
    for name in _STALE:
        assert _name_watcher_calls(_body(cn, name)), name

    out = migrate.ensure(cn)

    for name in _STALE:
        assert not _name_watcher_calls(_body(cn, name)), name
    up = _body(cn, "mill_join_upsert").lower().replace(" ", "")
    assert "mill_watcher_put('doing'" in up
    for f in ("sp_name.sql", "sp_member.sql", "sp_join.sql"):
        assert f in out["applied"], out["applied"]


def test_ensure_refreshes_every_sp_name_member_join_procedure(cn) -> None:
    """Each procedure in the three files is dropped + re-created from tip."""
    names = []
    for f in getattr(migrate, "_SP_FULL_REFRESH", ("sp_name.sql", "sp_member.sql", "sp_join.sql")):
        for stmt in migrate.split_script((migrate.sql_dir() / f).read_text(encoding="utf-8")):
            low = stmt.strip().lower()
            if low.startswith("create procedure"):
                names.append(stmt.split()[2].split("(")[0].strip("`"))
    assert "mill_join_upsert" in names and "mill_member_put" in names
    assert "mill_name_reclaim" in names
    assert "mill_label_delete" in names
    for n in names:
        _exec(cn, f"DROP PROCEDURE IF EXISTS {n}")
    migrate.ensure(cn)
    for n in names:
        assert _body(cn, n), n
    # Idempotent: a second ensure leaves the same shape.
    migrate.ensure(cn)
    for n in names:
        assert _body(cn, n), n


def test_ensure_refreshes_hold_upsert_rehold(cn) -> None:
    """#194: an existing book that only runs ensure gets the same-holder refresh branch."""
    _exec(cn, "DROP PROCEDURE IF EXISTS mill_hold_upsert")
    _exec(cn, "CREATE PROCEDURE mill_hold_upsert(IN p_project VARCHAR(64), IN p_desk VARCHAR(64), IN p_resource VARCHAR(64)) SELECT 0 AS ok")
    assert "v_held = v_desk" not in _body(cn, "mill_hold_upsert")
    out = migrate.ensure(cn)
    assert "sp_hold.sql" in out["applied"], out["applied"]
    body = _body(cn, "mill_hold_upsert")
    assert "v_held = v_desk" in body
    assert "UPDATE hold SET updated = v_ts WHERE id = v_id" in body
