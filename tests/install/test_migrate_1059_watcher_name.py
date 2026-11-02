"""card 1059: migrate_1022 drops illegal watcher type=name rows, then sets tip ENUM.

Name is not an activity (office decision 2026-10-03). A 0.8.5-era book can still
hold name watcher rows; the 0.8.6 fixed ENUM then fails with Data truncated.
Delete the rows first, then apply the tip ENUM. Also repairs a book that was
hand-widened to keep name (cloud office workaround).
"""
from __future__ import annotations

import pytest

from agent_coord.install import migrate
from agent_coord.install.migrate import apply_transition_1022, transition_1022_needed

# fresh_schema: builds throwaway books and mutates watcher.type
pytestmark = [pytest.mark.sql, pytest.mark.fresh_schema]

TIP_WATCHER_TYPE = "enum('todo','doing','hold','score','wake')"


def _mysql_up() -> None:
    try:
        from tests.beta_book import admin_conn

        cn, _ = admin_conn()
        cn.close()
    except Exception as exc:
        pytest.skip(f"no MySQL for card 1059 migration tests: {exc}")


def _admin_connect():
    import mysql.connector
    from agent_coord.server.records.db import conn_kwargs

    kw = conn_kwargs()
    kw.pop("database", None)
    kw["autocommit"] = True
    return mysql.connector.connect(**kw)


def _new_book(name: str):
    import mysql.connector
    from agent_coord.server.records.db import conn_kwargs

    admin = _admin_connect()
    cur = admin.cursor()
    cur.execute(f"DROP DATABASE IF EXISTS `{name}`")
    cur.execute(
        f"CREATE DATABASE `{name}` DEFAULT CHARACTER SET utf8mb4"
        " DEFAULT COLLATE utf8mb4_0900_ai_ci"
    )
    cur.close()
    admin.close()
    kw = conn_kwargs()
    kw["database"] = name
    return mysql.connector.connect(**kw)


def _drop_book(name: str) -> None:
    admin = _admin_connect()
    cur = admin.cursor()
    cur.execute(f"DROP DATABASE IF EXISTS `{name}`")
    cur.close()
    admin.close()


def _q(cn, sql, args=()):
    cur = cn.cursor()
    try:
        cur.execute(sql, args)
        return cur.fetchall() if cur.with_rows else []
    finally:
        cur.close()


def _exec(cn, sql, args=()):
    cur = cn.cursor()
    try:
        cur.execute(sql, args)
    finally:
        cur.close()


def _watcher_type(cn) -> str:
    rows = _q(
        cn,
        "SELECT COLUMN_TYPE FROM information_schema.COLUMNS"
        " WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'watcher'"
        " AND COLUMN_NAME = 'type'",
    )
    assert rows, "watcher.type missing"
    val = rows[0][0]
    if isinstance(val, (bytes, bytearray)):
        val = val.decode("utf-8")
    return str(val)


def _seed_pre_1022_with_name_watchers(cn) -> None:
    """0.8.5-shaped fragment: activity/watcher without wake; watcher ENUM keeps name."""
    for stmt in (
        "CREATE TABLE name ("
        " id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,"
        " type ENUM('desk','roster','label','tree','res') NOT NULL,"
        " name VARCHAR(64) NOT NULL,"
        " deleted DATETIME(6) NULL,"
        " trashed DATETIME(6) NULL,"
        " n INT UNSIGNED NOT NULL DEFAULT 0,"
        " PRIMARY KEY(id),"
        " UNIQUE KEY idx_type(type,name),"
        " UNIQUE KEY idx_id_type(id,type)"
        ") ENGINE=InnoDB",
        "CREATE TABLE seat ("
        " desk_id BIGINT UNSIGNED NOT NULL,"
        " token_hash CHAR(64) NULL,"
        " delivery_mode ENUM('websocket','webhook','polling') NOT NULL DEFAULT 'polling',"
        " wake_on ENUM('all','addressed') NOT NULL DEFAULT 'addressed',"
        " PRIMARY KEY(desk_id)"
        ") ENGINE=InnoDB",
        "CREATE TABLE activity ("
        " type ENUM('mail','todo','doing','hold','score') NOT NULL,"
        " id BIGINT UNSIGNED NOT NULL,"
        " created DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),"
        " updated DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),"
        " deleted DATETIME(6) NULL,"
        " desk_id BIGINT UNSIGNED NULL,"
        " roster_id BIGINT UNSIGNED NOT NULL DEFAULT 1,"
        " roster_kind ENUM('desk','roster','label','tree','res') NOT NULL DEFAULT 'roster',"
        " act ENUM('create','send') NOT NULL DEFAULT 'create',"
        " bytes INT UNSIGNED NULL,"
        " PRIMARY KEY(type,id)"
        ") ENGINE=InnoDB",
        # Drift: live books still carried type=name from older mill_watcher_* callers.
        "CREATE TABLE watcher ("
        " type ENUM('todo','doing','hold','score','name') NOT NULL,"
        " id BIGINT UNSIGNED NOT NULL,"
        " desk_id BIGINT UNSIGNED NOT NULL,"
        " hint VARCHAR(4096) NULL,"
        " updated DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),"
        " PRIMARY KEY(type, id, desk_id),"
        " KEY idx_desk (desk_id),"
        " CONSTRAINT fk_watcher_desk FOREIGN KEY (desk_id) REFERENCES seat (desk_id)"
        ") ENGINE=InnoDB",
        "INSERT INTO name (id,type,name) VALUES"
        " (1,'roster','Office'),(2,'roster','Admin'),(10,'desk','w-desk')",
        "INSERT INTO seat (desk_id) VALUES (10)",
        "INSERT INTO activity (type,id,desk_id,roster_id,act) VALUES ('todo',1,10,1,'create')",
        "INSERT INTO watcher (type,id,desk_id) VALUES ('name',1,10),('name',2,10),('todo',1,10)",
    ):
        _exec(cn, stmt)
    cn.commit()


def test_upgrade_from_085_with_name_watchers_deletes_rows_and_matches_tip():
    """0.8.5 book with name watcher rows upgrades; name rows gone; ENUM matches tip."""
    _mysql_up()
    from tests.sql_isolate import throwaway_db

    db = throwaway_db("mill_1059_085")
    cn = _new_book(db)
    try:
        _seed_pre_1022_with_name_watchers(cn)
        assert _q(cn, "SELECT COUNT(*) FROM watcher WHERE type='name'")[0][0] == 2
        assert "'name'" in _watcher_type(cn)
        assert "'wake'" not in _watcher_type(cn)
        assert transition_1022_needed(cn) is True
        applied = apply_transition_1022(cn)
        assert applied, "migrate_1022 should run"
        assert _q(cn, "SELECT COUNT(*) FROM watcher WHERE type='name'")[0][0] == 0
        assert _q(cn, "SELECT type,id,desk_id FROM watcher") == [("todo", 1, 10)]
        assert _watcher_type(cn) == TIP_WATCHER_TYPE
        # Idempotent: a second pass is a no-op once the tip shape is present.
        assert transition_1022_needed(cn) is False
        assert apply_transition_1022(cn) == []
    finally:
        cn.close()
        _drop_book(db)


def test_hand_widened_book_rerun_drops_name_and_matches_tip():
    """Hand-widen workaround: tip book whose watcher ENUM was widened to keep name."""
    _mysql_up()
    from tests.sql_isolate import throwaway_db

    db = throwaway_db("mill_1059_wide")
    cn = _new_book(db)
    try:
        migrate.ensure(cn)
        assert _watcher_type(cn) == TIP_WATCHER_TYPE
        assert transition_1022_needed(cn) is False
        # Put name back on the ENUM so ensure would skip the old wake-only ALTER.
        _exec(
            cn,
            "ALTER TABLE watcher MODIFY type"
            " ENUM('todo','doing','hold','score','wake','name') NOT NULL",
        )
        desk = _q(cn, "SELECT desk_id FROM seat WHERE desk_id > 0 ORDER BY desk_id LIMIT 1")
        if not desk:
            _exec(cn, "INSERT INTO name (type, name) VALUES ('desk', 'w1059')")
            desk_id = int(_q(cn, "SELECT LAST_INSERT_ID()")[0][0])
            _exec(cn, "INSERT INTO seat (desk_id) VALUES (%s)", (desk_id,))
        else:
            desk_id = int(desk[0][0])
        _exec(cn, "INSERT INTO watcher (type, id, desk_id) VALUES ('name', 99, %s)", (desk_id,))
        cn.commit()
        assert "'name'" in _watcher_type(cn)
        assert _q(cn, "SELECT COUNT(*) FROM watcher WHERE type='name'")[0][0] == 1
        assert transition_1022_needed(cn) is True
        applied = apply_transition_1022(cn)
        assert applied, "migrate_1022 must re-run to drop name"
        assert _q(cn, "SELECT COUNT(*) FROM watcher WHERE type='name'")[0][0] == 0
        assert _watcher_type(cn) == TIP_WATCHER_TYPE
        assert transition_1022_needed(cn) is False
        assert apply_transition_1022(cn) == []
    finally:
        cn.close()
        _drop_book(db)


def test_fresh_watcher_type_matches_tip_constant(cn):
    """Fresh tables.sql watcher.type is the tip ENUM (no name)."""
    assert _watcher_type(cn) == TIP_WATCHER_TYPE
    assert "'name'" not in _watcher_type(cn)
