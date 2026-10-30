"""Schema design invariants (card 868, F160). docs/requirements/schema-design.md.

DDL-only: beta_ddl.sql applied to a throwaway schema, then information_schema reads. No SPIN, no server.
Each invariant is a rule the owner set; an exception is an explicit allowlist entry with its reason.
The PR rule lives in test_schema_diff_rule_868.py (git only, no database).
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# Short VARCHAR columns that are not a name of the name table, each with its reason. A new one must be added here
# (and justified), so a name string cannot slip into a table unnoticed.
SHORT_TEXT_OK = {
    ("name", "name"): "the name itself",
    ("name_event", "old_name"): "history: the name before a rename",
    ("name_event", "new_name"): "history: the name after",
    ("score", "kpi"): "a kpi key, not a name row (main)",
    ("score", "value"): "a reading (main)",
    ("score", "target"): "a target (main)",
    ("score", "unit"): "a unit (main)",
    ("mill_invite", "label"): "free text on an invite (main)",
    ("mill_invite", "created_by"): "FINDING F1 in BETA-CHANGES.md: a desk name or 'wall'/'door' (main); pending the owner",
    ("mill_invite_join", "party_id"): "FINDING F1 in BETA-CHANGES.md: a desk name or human id (main); pending the owner",
    ("mill_invite", "key_id"): "an invite key id, ascii",
    ("mill_invite_join", "key_id"): "an invite key id, ascii",
    ("mill_invite_join", "party"): "desk or human, a kind",
    ("vote_option", "label"): "option text",
    ("seat", "lan_ip"): "an address",
}
# Id-like columns that are not INT UNSIGNED, with the reason.
ID_TYPE_OK = {
    ("push_queue", "id"): "bigint unsigned: a churning queue",
    ("mill_invite", "key_id"): "an invite key string",
    ("mill_invite_join", "key_id"): "an invite key string",
    ("mill_invite_join", "party_id"): "FINDING F1",
    ("office_setting", "id"): "the one row (tinyint)",
    ("glance_cache", "id"): "the one row (tinyint)",
    ("vote_option", "opt"): "option number 1..n, not an id",
    ("vote_cast", "opt"): "option number 1..n, not an id",
}
# The one untyped reference to name: name_event.name_id may point at any type (the history of every name).
UNTYPED_NAME_REF_OK = {("name_event", "name_id")}
EDGE_WORDS = ("parent", "reply_to", "from_card", "from_letter", "from_score", "edge", "link", "adjacen", "child")


@pytest.fixture(scope="module")
def book():
    try:
        from tests.beta_book import drop_book, make_book

        cn, db = make_book("mill_inv868", sp=True)
    except Exception as exc:  # no MySQL here: the invariants need one throwaway schema
        pytest.skip(f"no MySQL for the DDL invariants: {exc}")
    yield cn, db
    drop_book(cn, db)


def _rows(cn, sql, args=()):
    cur = cn.cursor()
    try:
        cur.execute(sql, args)
        return list(cur.fetchall())
    finally:
        cur.close()


pytestmark = pytest.mark.sql


def test_no_name_string_outside_name(book):
    cn, db = book
    rows = _rows(cn, "SELECT TABLE_NAME, COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = %s"
                     " AND DATA_TYPE IN ('varchar','char') AND CHARACTER_MAXIMUM_LENGTH <= 128", (db,))
    bad = sorted({(t, c) for t, c in rows if (t, c) not in SHORT_TEXT_OK
                  and not c.endswith("_hash") and not c.startswith("t_") and c not in ("version", "by_user")})
    assert not bad, f"short text columns that could hold a name string; justify in SHORT_TEXT_OK or use a name id: {bad}"


def test_ids_are_int_unsigned(book):
    cn, db = book
    rows = _rows(cn, "SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = %s"
                     " AND (COLUMN_NAME = 'id' OR COLUMN_NAME LIKE '%%\\_id' OR COLUMN_NAME = 'opt')", (db,))
    bad = sorted((t, c, ty) for t, c, ty in rows if ty != "int unsigned" and (t, c) not in ID_TYPE_OK)
    assert not bad, f"ids are INT UNSIGNED unless allowlisted with a reason: {bad}"
    assert ("push_queue", "id", "bigint unsigned") in [(t, c, ty) for t, c, ty in rows]


def test_trees_are_nested_sets_no_edge_table(book):
    cn, db = book
    cols = _rows(cn, "SELECT TABLE_NAME, COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = %s", (db,))
    tables = {t for t, _ in cols}
    bad_cols = sorted((t, c) for t, c in cols if any(w in c.lower() for w in EDGE_WORDS))
    bad_tables = sorted(t for t in tables if any(w in t.lower() for w in EDGE_WORDS))
    assert not bad_cols and not bad_tables, f"no edge or adjacency structure: {bad_cols} {bad_tables}"
    tree = {c for t, c in cols if t == "tree"}
    assert {"lft", "rgt", "name_id", "type", "id"} <= tree


def test_every_name_reference_is_typed(book):
    cn, db = book
    rows = _rows(cn, "SELECT k.TABLE_NAME, k.CONSTRAINT_NAME, GROUP_CONCAT(k.COLUMN_NAME ORDER BY k.ORDINAL_POSITION),"
                     " GROUP_CONCAT(k.REFERENCED_COLUMN_NAME ORDER BY k.ORDINAL_POSITION)"
                     " FROM information_schema.KEY_COLUMN_USAGE k WHERE k.TABLE_SCHEMA = %s AND k.REFERENCED_TABLE_NAME = 'name'"
                     " GROUP BY k.TABLE_NAME, k.CONSTRAINT_NAME", (db,))
    assert rows
    gen = {(t, c): e for t, c, e in _rows(cn, "SELECT TABLE_NAME, COLUMN_NAME, GENERATION_EXPRESSION FROM information_schema.COLUMNS"
                                              " WHERE TABLE_SCHEMA = %s AND COLUMN_NAME LIKE 't\\_%%'", (db,))}
    bad = []
    for t, fk, cols, refs in rows:
        cols_l, refs_l = cols.split(","), refs.split(",")
        if len(cols_l) == 1 and (t, cols_l[0]) in UNTYPED_NAME_REF_OK:
            continue
        if refs_l != ["type", "id"] or not cols_l[0].startswith("t_") or (t, cols_l[0]) not in gen:
            bad.append((t, fk, cols, refs))
    assert not bad, f"every reference to name is (generated t_<type>, id) -> name (type, id): {bad}"


def test_app_grant_is_execute_only(book):
    cn, db = book
    from agent_coord.install.beta_grant import grant_app_user

    user = ("inv868_" + str(os.getpid()))[:32]
    try:
        granted = grant_app_user(cn, db, user, "inv868-pw", "localhost")
    except Exception as exc:
        pytest.skip(f"no CREATE USER privilege here: {exc}")
    try:
        assert granted and "sp_admin_set" not in granted and not any(g.startswith("b_") for g in granted)
        grants = [r[0] for r in _rows(cn, "SHOW GRANTS FOR %s@'localhost'", (user,))]
        for g in grants:
            assert g.startswith("GRANT USAGE ON *.*") or g.startswith("GRANT EXECUTE ON "), g
    finally:
        _rows(cn, "DROP USER IF EXISTS %s@'localhost'", (user,))
