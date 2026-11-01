"""card 1022 fold: push_queue -> wake; hand-back is a transition; two-desk live wake."""
from __future__ import annotations

import json

import pytest

from agent_coord.install.migrate import apply_transition_1022, transition_1022_needed
from agent_coord.server.records import push as push_rec
from agent_coord.server.records.db import call
from tests.server.records.conftest import admin_desk

pytestmark = pytest.mark.sql


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


def test_fresh_book_has_wake_not_push_queue(cn):
    tables = {r[0] for r in _q(cn, "SHOW TABLES")}
    assert "wake" in tables
    assert "push_queue" not in tables
    cols = {r[0] for r in _q(cn, "SHOW COLUMNS FROM wake")}
    assert {"id", "type", "desk_id", "cause", "state", "payload", "created"} <= cols


def test_hint_push_writes_activity_wake_and_transition_survives_handback(cn):
    desk = admin_desk(cn)
    rows = push_rec.put(cn, desk, "hint", {"route": "todo:NOTE", "id": 1}, "missed")
    cn.commit()
    assert rows and int(rows[0]["id"]) > 0
    wid = int(rows[0]["id"])
    act = _q(cn, "SELECT type, id, desk_id, act FROM activity WHERE type='wake' AND id=%s", (wid,))
    assert act == [("wake", wid, 0, "ring")]
    wake = _q(
        cn,
        "SELECT desk_id, cause, state FROM wake WHERE type='wake' AND id=%s",
        (wid,),
    )
    desk_id = _q(cn, "SELECT id FROM name WHERE type='desk' AND name=%s", (desk,))[0][0]
    assert wake == [(desk_id, "hint", "missed")]
    # transitions seeded on put
    tos = {r[0] for r in _q(cn, "SELECT to_state FROM transition WHERE activity_type='wake' AND activity_id=%s", (wid,))}
    assert "queued" in tos and "missed" in tos
    # hand-back via take marks taken; row remains (sync item id is payload id, not wake id)
    taken = push_rec.take(cn, desk)
    cn.commit()
    assert taken, "take returned no items"
    st = _q(cn, "SELECT state FROM wake WHERE id=%s", (wid,))
    assert st == [("taken",)]
    tos2 = {r[0] for r in _q(cn, "SELECT to_state FROM transition WHERE activity_type='wake' AND activity_id=%s", (wid,))}
    assert "taken" in tos2
    # second take: wake stays taken, not handed again
    taken2 = push_rec.take(cn, desk)
    cn.commit()
    assert _q(cn, "SELECT state FROM wake WHERE id=%s", (wid,)) == [("taken",)]


def test_two_desk_mail_wake_handback_no_lost_or_duplicate(cn):
    """Live-style: desk A queues a mail wake for desk B; B takes once; no lost/dup."""
    a = f"desk-a-1022-{id(cn) % 100000}"
    b = f"desk-b-1022-{id(cn) % 100000}"
    for d in (a, b):
        _exec(cn, "INSERT INTO name (type, name) VALUES ('desk', %s)", (d,))
        did = _q(cn, "SELECT id FROM name WHERE type='desk' AND name=%s", (d,))[0][0]
        _exec(
            cn,
            "INSERT IGNORE INTO seat (desk_id, token_hash, delivery_mode, wake_on)"
            " VALUES (%s, NULL, 'polling', 'addressed')",
            (did,),
        )
    cn.commit()
    b_id = _q(cn, "SELECT id FROM name WHERE type='desk' AND name=%s", (b,))[0][0]

    # A "sends" a mail wake toward B (payload carries mail id)
    mail_id = 9100221
    put_rows = push_rec.put(cn, b, "mail", {"id": mail_id, "from": a}, "missed")
    cn.commit()
    wid = int(put_rows[0]["id"])
    before = _q(cn, "SELECT COUNT(*) FROM wake WHERE desk_id=%s AND cause='mail' AND state<>'taken'", (b_id,))[0][0]
    assert before >= 1

    # B is woken: take once (hand-back). Sync item carries mail id in payload.
    got = push_rec.take(cn, b)
    cn.commit()
    mail_items = [it for it in got if int(it.get("id") or 0) == mail_id and it.get("kind") == "mail"]
    assert len(mail_items) == 1, (got, _q(cn, "SELECT id,desk_id,cause,state FROM wake"))
    row = _q(cn, "SELECT state, cause FROM wake WHERE id=%s", (wid,))
    assert row == [("taken", "mail")]
    assert _q(
        cn,
        "SELECT 1 FROM transition WHERE activity_type='wake' AND activity_id=%s AND to_state='taken' LIMIT 1",
        (wid,),
    )
    # no second delivery of this wake row
    got2 = push_rec.take(cn, b)
    cn.commit()
    assert not [it for it in got2 if int(it.get("id") or 0) == mail_id and it.get("kind") == "mail"]
    assert _q(cn, "SELECT COUNT(*) FROM wake WHERE id=%s", (wid,)) == [(1,)]


def test_migrate_moves_queued_push_queue_rows(cn):
    """Simulate a pre-fold book fragment: push_queue row moves into activity+wake."""
    import mysql.connector
    from agent_coord.server.records.db import conn_kwargs
    from tests.sql_isolate import throwaway_db

    # Build a tiny pre-fold schema with push_queue only (plus seat/name/activity)
    dst = throwaway_db("mill_1022_fold")
    kw = conn_kwargs()
    kw.pop("database", None)
    kw["autocommit"] = True
    admin = mysql.connector.connect(**kw)
    cur = admin.cursor()
    cur.execute(f"DROP DATABASE IF EXISTS `{dst}`")
    cur.execute(
        f"CREATE DATABASE `{dst}` DEFAULT CHARACTER SET utf8mb4"
        " DEFAULT COLLATE utf8mb4_0900_ai_ci"
    )
    cur.close()
    admin.close()
    kw2 = conn_kwargs()
    kw2["database"] = dst
    book = mysql.connector.connect(**kw2)
    c = book.cursor()
    for stmt in (
        "CREATE TABLE name (id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, type ENUM('desk','roster','label','tree','res') NOT NULL, name VARCHAR(64) NOT NULL, deleted DATETIME(6) NULL, trashed DATETIME(6) NULL, n INT UNSIGNED NOT NULL DEFAULT 0, PRIMARY KEY(id), UNIQUE KEY idx_type(type,name), UNIQUE KEY idx_id_type(id,type)) ENGINE=InnoDB",
        "CREATE TABLE seat (id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, desk_id BIGINT UNSIGNED NOT NULL, token_hash CHAR(64) NULL, delivery_mode ENUM('websocket','webhook','polling') NOT NULL DEFAULT 'polling', wake_on ENUM('all','addressed') NOT NULL DEFAULT 'addressed', PRIMARY KEY(id), UNIQUE KEY idx_desk(desk_id)) ENGINE=InnoDB",
        "CREATE TABLE activity (type ENUM('mail','todo','doing','hold','score') NOT NULL, id BIGINT UNSIGNED NOT NULL, created DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), updated DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), deleted DATETIME(6) NULL, desk_id BIGINT UNSIGNED NULL, roster_id BIGINT UNSIGNED NOT NULL DEFAULT 1, roster_kind ENUM('desk','roster','label','tree','res') NOT NULL DEFAULT 'roster', act ENUM('create','send') NOT NULL DEFAULT 'create', bytes INT UNSIGNED NULL, PRIMARY KEY(type,id)) ENGINE=InnoDB",
        "CREATE TABLE push_queue (id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, desk_id BIGINT UNSIGNED NOT NULL, kind ENUM('hint','mail','receipt','expired') NOT NULL, payload JSON NOT NULL, outcome ENUM('sent','missed','error') NOT NULL, created DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), PRIMARY KEY(id)) ENGINE=InnoDB",
        "INSERT INTO name (id,type,name) VALUES (1,'roster','Office'),(2,'roster','Admin'),(10,'desk','fold-desk')",
        "INSERT INTO seat (desk_id) VALUES (10)",
        "INSERT INTO push_queue (desk_id, kind, payload, outcome) VALUES (10, 'hint', JSON_OBJECT('id', 1), 'missed')",
    ):
        c.execute(stmt)
    book.commit()
    c.close()
    assert transition_1022_needed(book) is True
    applied = apply_transition_1022(book)
    assert applied
    cur = book.cursor()
    cur.execute("SHOW TABLES")
    tables = {r[0] for r in cur.fetchall()}
    assert "push_queue" not in tables
    assert "wake" in tables
    cur.execute("SELECT id, cause, state, desk_id FROM wake")
    rows = cur.fetchall()
    assert rows and rows[0][1] == "hint" and rows[0][2] == "missed" and rows[0][3] == 10
    wid = rows[0][0]
    cur.execute("SELECT type, id, desk_id, act FROM activity WHERE type='wake' AND id=%s", (wid,))
    act = cur.fetchone()
    assert act == ("wake", wid, 0, "ring"), act
    cur.close()
    book.close()
    kw_admin = conn_kwargs()
    kw_admin.pop("database", None)
    kw_admin["autocommit"] = True
    admin = mysql.connector.connect(**kw_admin)
    cur = admin.cursor()
    cur.execute(f"DROP DATABASE `{dst}`")
    cur.close()
    admin.close()
