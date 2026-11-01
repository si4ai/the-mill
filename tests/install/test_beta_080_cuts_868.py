"""0.8.0 schema cuts (card 868, the owner 2026-10-26; F173, F178, F179): no new table, one act list, seat.doing_id.

beta_ddl.sql (and beta_sp.sql) on one throwaway schema, then information_schema, EXPLAIN and a few writes.
The act list's one source is the table under "The act list" in docs/requirements/beta/BETA-CHANGES.md.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import mysql.connector
import pytest

# fresh_schema: applies beta DDL/SP pack, not the tip schema
pytestmark = [pytest.mark.sql, pytest.mark.fresh_schema]

ROOT = Path(__file__).resolve().parents[2]
CHANGES = ROOT / "docs" / "requirements" / "beta" / "BETA-CHANGES.md"
MAIN_22 = {"name", "seat", "member", "activity", "label", "tree", "watcher", "mail", "mail_to", "tree_read", "todo",
           "doing", "hold", "score", "score_point", "score_evidence", "human", "human_desk", "human_member",
           "mill_invite", "mill_invite_join", "wake", "transition", "transition_edge"}


def doc_acts() -> list[str]:
    text = CHANGES.read_text(encoding="utf-8")
    m = re.search(r"^## The act list.*?\n(.*?)(?=^## )", text, re.S | re.M)
    assert m, "BETA-CHANGES.md has a section '## The act list'"
    return re.findall(r"^\| `([a-z]+)` \|", m.group(1), re.M)


@pytest.fixture(scope="module")
def book():
    try:
        from tests.beta_book import drop_book, make_book

        cn, db = make_book("mill_cut868", sp=True)
    except Exception as exc:
        pytest.skip(f"no MySQL: {exc}")
    yield cn, db
    drop_book(cn, db)


def q(cn, sql, args=()):
    cur = cn.cursor()
    try:
        cur.execute(sql, args)
        return list(cur.fetchall()) if cur.with_rows else []
    finally:
        cur.close()


def col_type(cn, db, t, c):
    r = q(cn, "SELECT COLUMN_TYPE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s"
              " AND COLUMN_NAME=%s", (db, t, c))
    return r[0][0] if r else None


def test_no_new_tables(book):
    # card 1022 added wake/transition/transition_edge (owner 2026-11-01); still no vote/todo_event/etc.
    cn, db = book
    tables = {t for (t,) in q(cn, "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s", (db,))}
    assert tables == MAIN_22, sorted(tables ^ MAIN_22)
    trig = {t for (t,) in q(cn, "SELECT TRIGGER_NAME FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA=%s", (db,))}
    assert not {t for t in trig if t.startswith("vote")}, trig


def test_act_is_one_list_on_activity_and_doing(book):
    cn, db = book
    acts = doc_acts()
    assert acts and len(acts) == len(set(acts)) and len(acts) < 256, acts  # one byte
    want = "enum(" + ",".join(f"'{a}'" for a in acts) + ")"
    assert col_type(cn, db, "activity", "act") == want
    assert col_type(cn, db, "doing", "act") == want
    for gone in ("open", "status", "pass", "cast", "close", "start"):
        assert gone not in acts, gone


def test_activity_has_no_weight_or_n_and_keeps_bytes(book):
    cn, db = book
    assert col_type(cn, db, "activity", "weight") is None
    assert col_type(cn, db, "activity", "n") is None
    assert col_type(cn, db, "activity", "bytes") == "int unsigned"


def test_seat_doing_id_is_the_desks_own_row(book):
    cn, db = book
    fk = q(cn, "SELECT GROUP_CONCAT(k.COLUMN_NAME ORDER BY k.ORDINAL_POSITION), k.REFERENCED_TABLE_NAME,"
               " GROUP_CONCAT(k.REFERENCED_COLUMN_NAME ORDER BY k.ORDINAL_POSITION), r.DELETE_RULE"
               " FROM information_schema.KEY_COLUMN_USAGE k JOIN information_schema.REFERENTIAL_CONSTRAINTS r"
               " ON r.CONSTRAINT_SCHEMA = k.TABLE_SCHEMA AND r.CONSTRAINT_NAME = k.CONSTRAINT_NAME"
               " WHERE k.TABLE_SCHEMA=%s AND k.TABLE_NAME='seat' AND k.CONSTRAINT_NAME='fk_seat_doing'"
               " GROUP BY k.CONSTRAINT_NAME, k.REFERENCED_TABLE_NAME, r.DELETE_RULE", (db,))
    assert fk == [("doing_id,desk_id", "doing", "id,desk_id", "RESTRICT")], fk
    assert col_type(cn, db, "seat", "doing_id") == "bigint unsigned"
    q(cn, "INSERT INTO name (type, name) VALUES ('desk','cut-a'),('desk','cut-b')")
    a, b = (q(cn, "SELECT id FROM name WHERE type='desk' AND name=%s", (n,))[0][0] for n in ("cut-a", "cut-b"))
    q(cn, "INSERT INTO seat (desk_id) VALUES (%s),(%s)", (a, b))
    q(cn, "INSERT INTO doing (desk_id, text) VALUES (%s, 'b works')", (b,))
    other = q(cn, "SELECT id FROM doing WHERE desk_id=%s", (b,))[0][0]
    with pytest.raises(mysql.connector.Error) as ei:
        q(cn, "UPDATE seat SET doing_id=%s WHERE desk_id=%s", (other, a))
    assert ei.value.errno == 1452
    q(cn, "UPDATE seat SET doing_id=%s WHERE desk_id=%s", (other, b))
    with pytest.raises(mysql.connector.Error):
        q(cn, "DELETE FROM doing WHERE id=%s", (other,))


def test_doing_peer_is_a_seat(book):
    cn, db = book
    fk = q(cn, "SELECT REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME FROM information_schema.KEY_COLUMN_USAGE"
               " WHERE TABLE_SCHEMA=%s AND TABLE_NAME='doing' AND COLUMN_NAME='peer_id' AND REFERENCED_TABLE_NAME"
               " IS NOT NULL", (db,))
    assert fk == [("seat", "desk_id")]


def _plan(cn, sql):
    return json.loads(q(cn, "EXPLAIN FORMAT=JSON " + sql)[0][0])


def test_newest_list_is_a_reverse_idx_updated_read(book):
    cn, _db = book
    q(cn, "SET SESSION cte_max_recursion_depth = 30000")
    q(cn, "INSERT IGNORE INTO activity (type, id, updated, roster_id, act)"
          " WITH RECURSIVE n (i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < 20000)"
          " SELECT 'mail', 100000 + i, NOW(6) - INTERVAL i SECOND, 1, 'send' FROM n")
    q(cn, "ANALYZE TABLE activity")
    sql = "SELECT type, id, updated, desk_id, act FROM activity ORDER BY updated DESC LIMIT 50"
    plan = json.dumps(_plan(cn, sql))
    assert '"key": "idx_updated"' in plan, plan
    assert '"using_filesort": true' not in plan, plan
    tree = q(cn, "EXPLAIN FORMAT=TREE " + sql)[0][0]
    assert "idx_updated (reverse)" in tree, tree


def test_an_items_moves_read_in_id_order_with_no_filesort(book):
    cn, db = book
    keys = q(cn, "SELECT GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX) FROM information_schema.STATISTICS"
                 " WHERE TABLE_SCHEMA=%s AND TABLE_NAME='doing' AND INDEX_NAME='idx_on'", (db,))
    assert keys == [("on_type,on_id,id",)], keys
    sql = ("SELECT id, act FROM doing WHERE on_type='todo' AND on_id=7 AND act NOT IN ('focus','clear')"
           " ORDER BY id DESC LIMIT 1")
    plan = json.dumps(_plan(cn, sql))
    assert '"key": "idx_on"' in plan and '"using_filesort": true' not in plan, plan


def test_doing_evidence_is_nullable_2000_and_null_on_focus(book):
    """F187: doing.evidence VARCHAR(2000) NULL; focus/clear/finish keep it NULL (the owner, 2026-10-26)."""
    import time
    cn, db = book
    col = q(
        cn,
        "SELECT COLUMN_TYPE, IS_NULLABLE, CHARACTER_MAXIMUM_LENGTH FROM information_schema.COLUMNS"
        " WHERE TABLE_SCHEMA=%s AND TABLE_NAME='doing' AND COLUMN_NAME='evidence'",
        (db,),
    )
    assert col == [("varchar(2000)", "YES", 2000)], col
    n = 0

    def _desk():
        nonlocal n
        n += 1
        name = f"ev-desk-{n}-{time.time_ns()}"
        q(cn, "INSERT INTO name (type, name) VALUES ('desk', %s)", (name,))
        a = q(cn, "SELECT id FROM name WHERE type='desk' AND name=%s", (name,))[0][0]
        q(cn, "INSERT INTO seat (desk_id) VALUES (%s)", (a,))
        return a

    a = _desk()
    # CHECK: a focus row cannot carry evidence
    with pytest.raises(mysql.connector.Error):
        q(cn, "INSERT INTO doing (desk_id, text, act, evidence) VALUES (%s, 'x', 'focus', 'no')", (a,))
    cn.rollback()
    a = _desk()
    q(cn, "INSERT INTO doing (desk_id, text, act, evidence) VALUES (%s, 'x', 'focus', NULL)", (a,))
    q(cn, "INSERT INTO doing (desk_id, text, act, on_type, on_id, evidence)"
          " VALUES (%s, '', 'ship', 'todo', 1, %s)", (a, "e" * 2000))
    with pytest.raises(mysql.connector.Error):
        q(cn, "INSERT INTO doing (desk_id, text, act, on_type, on_id, evidence)"
              " VALUES (%s, '', 'ship', 'todo', 2, %s)", (a, "e" * 2001))
    cn.rollback()
