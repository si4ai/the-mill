"""0.8.0 schema cuts (card 868, the owner 2026-10-26; F173, F178, F179): no new table, one act list; card 1207: doing is six columns.

beta_ddl.sql (and beta_sp.sql) on one throwaway schema, then information_schema, EXPLAIN and a few writes.
The act list's one source is the table under "The act list" in docs/requirements/beta/BETA-CHANGES.md.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

# fresh_schema: applies beta DDL/SP pack, not the tip schema
pytestmark = [pytest.mark.sql, pytest.mark.fresh_schema]

ROOT = Path(__file__).resolve().parents[2]
CHANGES = ROOT / "docs" / "requirements" / "beta" / "BETA-CHANGES.md"
MAIN_22 = {"name", "seat", "member", "activity", "label", "tree", "watcher", "mail", "mail_to", "tree_read", "todo",
           "doing", "hold", "score", "score_point", "score_evidence", "human", "human_desk", "human_member",
           "mill_invite", "mill_invite_join", "wake", "transition", "transition_edge",
           "activity_history"}  # card 1133


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


def test_act_is_one_list_on_activity_and_doing_has_none(book):
    cn, db = book
    acts = doc_acts()
    assert acts and len(acts) == len(set(acts)) and len(acts) < 256, acts  # one byte
    want = "enum(" + ",".join(f"'{a}'" for a in acts) + ")"
    assert col_type(cn, db, "activity", "act") == want
    assert col_type(cn, db, "doing", "act") is None  # card 1207
    for gone in ("open", "status", "pass", "cast", "close", "start"):
        assert gone not in acts, gone


def test_activity_has_no_weight_or_n_and_keeps_bytes(book):
    cn, db = book
    assert col_type(cn, db, "activity", "weight") is None
    assert col_type(cn, db, "activity", "n") is None
    assert col_type(cn, db, "activity", "bytes") == "int unsigned"


def test_doing_is_six_columns_and_seat_has_no_doing_pointer(book):
    """Card 1207 (the owner GO, 2026-11-13): doing = type, id, created, desk_id, roster_id, text; seat.doing_id,
    fk_seat_doing, fk_doing_peer and the item, blocked-on and act columns are gone."""
    cn, db = book
    cols = [c for (c,) in q(cn, "SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s"
                               " AND TABLE_NAME='doing' ORDER BY ORDINAL_POSITION", (db,))]
    assert cols == ["type", "id", "created", "desk_id", "roster_id", "text"], cols
    idx = {i for (i,) in q(cn, "SELECT DISTINCT INDEX_NAME FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=%s"
                              " AND TABLE_NAME='doing'", (db,))}
    assert idx == {"PRIMARY", "idx_id", "idx_desk_created", "idx_roster"}, idx
    fks = {f for (f,) in q(cn, "SELECT CONSTRAINT_NAME FROM information_schema.REFERENTIAL_CONSTRAINTS"
                              " WHERE CONSTRAINT_SCHEMA=%s AND TABLE_NAME='doing'", (db,))}
    assert fks == {"fk_doing_desk", "fk_doing_roster"}, fks
    assert col_type(cn, db, "seat", "doing_id") is None
    assert not q(cn, "SELECT 1 FROM information_schema.REFERENTIAL_CONSTRAINTS WHERE CONSTRAINT_SCHEMA=%s"
                     " AND CONSTRAINT_NAME='fk_seat_doing'", (db,))


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


def test_a_desks_runs_read_newest_first_with_no_filesort(book):
    """Card 1207: live_doings reads a desk's runs by idx_desk_created (an item's moves are transition rows)."""
    cn, _db = book
    sql = "SELECT id, created FROM doing WHERE desk_id=7 ORDER BY created DESC LIMIT 20"
    plan = json.dumps(_plan(cn, sql))
    assert '"key": "idx_desk_created"' in plan and '"using_filesort": true' not in plan, plan


def test_doing_has_no_evidence_and_card_evidence_is_uncapped_meta(book):
    """F187, card 1207 (the owner, 2026-11-13): doing.evidence and chk_doing_evidence are gone; a card's evidence is
    todo.meta.evidence, a JSON key with no cap (kept whole: test_server_sp_only_867)."""
    cn, db = book
    col = q(
        cn,
        "SELECT COLUMN_NAME FROM information_schema.COLUMNS"
        " WHERE TABLE_SCHEMA=%s AND TABLE_NAME='doing' AND COLUMN_NAME='evidence'",
        (db,),
    )
    assert col == [], col
    chk = q(
        cn,
        "SELECT CONSTRAINT_NAME FROM information_schema.CHECK_CONSTRAINTS"
        " WHERE CONSTRAINT_SCHEMA=%s AND CONSTRAINT_NAME='chk_doing_evidence'",
        (db,),
    )
    assert chk == [], chk
