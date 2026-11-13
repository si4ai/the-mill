"""Card 1133 migration on an existing book: migrate_1133_history.sql through agent_coord.install.migrate.

The book is put back in the pre-1133 shape (no activity_history, no body stamps, no todo.meta, no replace act, card
documents whole in todo.body), then migrated. Each card's detail string becomes todo.body byte for byte, every
other key becomes todo.meta, updated is kept, and a second run is a no-op.
"""
from __future__ import annotations

import json

import pytest

from tests.server.records.conftest import seed_names

pytestmark = [pytest.mark.sql, pytest.mark.fresh_schema]

DOCS = [
    {"slug": "plain", "detail": "one line"},
    {"slug": "multi", "detail": "a\nb\n  c\t\"quoted\" \\ back", "progress": "2/5", "eta_at": "2026-11-12T10:00:00"},
    {"slug": "wide", "detail": "\u00e9\u00e8 \u4e2d\u6587 \U0001f600 end", "started_at": "2026-11-11T08:00:00"},
    {"slug": "renamed", "detail": "", "aliases": ["old-a", "old-b"]},
    {"slug": "no-detail"},
    {"slug": "legacy", "doing": "old title", "detail": "under it"},
]
RAW = ["not json at all", "", "{broken json", "[1, 2]"]


def _q(cn, sql, args=()):
    cur = cn.cursor(dictionary=True)
    try:
        cur.execute(sql, args)
        return cur.fetchall() if cur.with_rows else []
    finally:
        cur.close()


def _x(cn, sql, args=()):
    cur = cn.cursor()
    try:
        cur.execute(sql, args)
        if cur.with_rows:
            cur.fetchall()
    finally:
        cur.close()


def _to_pre_1133(cn) -> None:
    _x(cn, "DROP TABLE activity_history")
    for t, cols, fk in (("mail", ("body_updater_id", "body_updated"), "fk_mail_body_updater"),
                        ("todo", ("body_updater_id", "body_updated", "meta"), "fk_todo_body_updater")):
        _x(cn, f"ALTER TABLE {t} DROP FOREIGN KEY {fk}")
        _x(cn, f"ALTER TABLE {t} DROP KEY idx_body_updater")
        for c in cols:
            _x(cn, f"ALTER TABLE {t} DROP COLUMN {c}")
    for table, default in (("activity", "create"),):  # card 1207: doing has no act
        ctype = _q(cn, "SELECT COLUMN_TYPE AS c FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE()"
                       " AND TABLE_NAME = %s AND COLUMN_NAME = 'act'", (table,))[0]["c"]
        _x(cn, f"ALTER TABLE {table} MODIFY act {ctype.replace(',' + chr(39) + 'replace' + chr(39), '')}"
               f" NOT NULL DEFAULT '{default}'")
    cn.commit()


def _shape(cn) -> dict:
    cols = _q(cn, "SELECT TABLE_NAME AS t, COLUMN_NAME AS c, ORDINAL_POSITION AS p, COLUMN_TYPE AS ty, IS_NULLABLE AS n"
                  " FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE()"
                  " AND TABLE_NAME IN ('mail', 'todo', 'activity', 'doing', 'activity_history')"
                  " ORDER BY TABLE_NAME, ORDINAL_POSITION")
    keys = _q(cn, "SELECT TABLE_NAME AS t, INDEX_NAME AS i, SEQ_IN_INDEX AS s, COLUMN_NAME AS c, NON_UNIQUE AS u"
                  " FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = DATABASE()"
                  " AND TABLE_NAME IN ('mail', 'todo', 'activity_history') ORDER BY 1, 2, 3")
    fks = _q(cn, "SELECT r.TABLE_NAME AS t, r.CONSTRAINT_NAME AS k, r.DELETE_RULE AS d, r.REFERENCED_TABLE_NAME AS ref"
                 " FROM information_schema.REFERENTIAL_CONSTRAINTS r WHERE r.CONSTRAINT_SCHEMA = DATABASE()"
                 " AND r.TABLE_NAME IN ('mail', 'todo', 'activity_history') ORDER BY 1, 2")
    return {"cols": cols, "keys": keys, "fks": fks}


def test_migration_splits_cards_byte_equal_and_is_idempotent(cn):
    from agent_coord.install import migrate

    tip = _shape(cn)
    seed_names(cn, ("m1133", "roster"), ("m_ask", "desk"))
    _to_pre_1133(cn)
    assert migrate.history_1133_needed(cn)
    desk = _q(cn, "SELECT id FROM name WHERE type = 'desk' AND name = 'm_ask'")[0]["id"]
    roster = _q(cn, "SELECT id FROM name WHERE type = 'roster' AND name = 'm1133'")[0]["id"]
    bodies = [json.dumps(d) for d in DOCS] + RAW
    ids = []
    for b in bodies:
        _x(cn, "INSERT INTO todo (created, updated, updated_id, roster_id, creator_id, body)"
               " VALUES ('2026-11-01 08:00:00.123456', '2026-11-02 09:00:00.654321', %s, %s, %s, %s)",
           (desk, roster, desk, b))
        ids.append(int(_q(cn, "SELECT LAST_INSERT_ID() AS i")[0]["i"]))
    cn.commit()

    assert migrate.apply_history_1133(cn) == [migrate.HISTORY_1133]
    assert _shape(cn) == tip  # the same columns, order, keys and FKs as a fresh tables.sql book
    assert not migrate.history_1133_needed(cn)

    rows = {r["id"]: r for r in _q(cn, "SELECT id, body, meta, updated, body_updated, body_updater_id,"
                                       " MILL_TODO_DOC(body, meta) AS doc FROM todo WHERE id IN (%s)"
                                       % ",".join(str(i) for i in ids))}
    for tid, src in zip(ids, bodies):
        r = rows[tid]
        assert str(r["updated"]) == "2026-11-02 09:00:00.654321"  # the split is not a card edit
        assert r["body_updated"] is None and r["body_updater_id"] is None
        try:
            want = json.loads(src)
        except ValueError:
            want = None
        if isinstance(want, dict):
            text = want.get("detail") or ""
            assert r["body"].encode("utf-8") == text.encode("utf-8"), src
            assert json.loads(r["meta"]) == {k: v for k, v in want.items() if k != "detail"}
            assert json.loads(r["doc"]) == dict(want, detail=text)
        else:
            assert r["body"] == src and json.loads(r["meta"]) == {}

    before = _q(cn, "SELECT id, body, CAST(meta AS CHAR) AS meta, updated FROM todo ORDER BY id")
    assert migrate.apply_history_1133(cn) == []
    cur = cn.cursor()
    try:  # the script itself is a no-op on a migrated book
        for stmt in migrate.split_script((migrate.sql_dir() / migrate.HISTORY_1133).read_text(encoding="utf-8")):
            migrate._apply_stmt(cur, stmt)
        cn.commit()
    finally:
        cur.close()
    assert _q(cn, "SELECT id, body, CAST(meta AS CHAR) AS meta, updated FROM todo ORDER BY id") == before
    assert _shape(cn) == tip


def test_ensure_runs_the_1133_step_on_a_partial_book(cn):
    from agent_coord.install import migrate

    tip = _shape(cn)
    # A run killed after the first mail column: the second column, its key and FK are still missing.
    _x(cn, "ALTER TABLE mail DROP FOREIGN KEY fk_mail_body_updater")
    _x(cn, "ALTER TABLE mail DROP KEY idx_body_updater")
    _x(cn, "ALTER TABLE mail DROP COLUMN body_updater_id")
    cn.commit()
    assert migrate.history_1133_needed(cn)
    assert migrate.HISTORY_1133 in migrate.ensure(cn)["applied"]
    assert not migrate.history_1133_needed(cn)
    assert _shape(cn) == tip
