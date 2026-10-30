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
    ("seat", "lan_ip"): "an address",
}
# Id-like columns that are not BIGINT UNSIGNED (main's id type, owner decision 2026-10-24), with the reason.
ID_TYPE_OK = {
    ("mill_invite", "key_id"): "an invite key string",
    ("mill_invite_join", "key_id"): "an invite key string",
    ("mill_invite_join", "party_id"): "FINDING F1",
}
# Kind tables (owner rule 2026-10-25): a name kind gets its own table only if the thing has its own data. seat is the
# desk kind (one FK to name, kind id = name.id); roster, label, tree and res have no data of their own, so their
# columns reference name with a kind-checked composite FK (col, <x>_kind) -> name (id, type) (F168).
KIND_REF_TO_NAME = {("seat", "desk_id"): "the desk kind"}
NAME_REF_NO_OWN_DATA = {("label", "name_id"), ("tree", "name_id"), ("tree_read", "tree_id"), ("hold", "resource_id"),
                        ("member", "name_id"), ("activity", "roster_id"), ("mail", "roster_id"), ("todo", "roster_id"),
                        ("doing", "roster_id"), ("score", "roster_id"), ("human_member", "name_id")}
# Desk columns FK to seat (desk_id); roster columns to name (id).
DESK_COLS = ("desk_id", "updated_id", "creator_id", "assigned_id")
ROSTER_COLS = ("roster_id",)
ROSTER_NAME_ID = {"member", "human_member"}  # name_id is a roster there (main's comments)
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


def test_ids_are_bigint_unsigned(book):
    cn, db = book
    rows = _rows(cn, "SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = %s"
                     " AND (COLUMN_NAME = 'id' OR COLUMN_NAME LIKE '%%\\_id' OR COLUMN_NAME = 'opt')", (db,))
    bad = sorted((t, c, ty) for t, c, ty in rows if ty != "bigint unsigned" and (t, c) not in ID_TYPE_OK)
    assert not bad, f"ids are BIGINT UNSIGNED as on main unless allowlisted with a reason: {bad}"
    assert ("name", "id", "bigint unsigned") in rows


def test_trees_are_nested_sets_no_edge_table(book):
    cn, db = book
    cols = _rows(cn, "SELECT TABLE_NAME, COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = %s", (db,))
    tables = {t for t, _ in cols}
    bad_cols = sorted((t, c) for t, c in cols if any(w in c.lower() for w in EDGE_WORDS))
    bad_tables = sorted(t for t in tables if any(w in t.lower() for w in EDGE_WORDS))
    assert not bad_cols and not bad_tables, f"no edge or adjacency structure: {bad_cols} {bad_tables}"
    tree = {c for t, c in cols if t == "tree"}
    assert {"lft", "rgt", "name_id", "type", "id"} <= tree


def _fks(cn, db):
    return _rows(cn, "SELECT k.TABLE_NAME, k.CONSTRAINT_NAME, GROUP_CONCAT(k.COLUMN_NAME ORDER BY k.ORDINAL_POSITION),"
                     " k.REFERENCED_TABLE_NAME, GROUP_CONCAT(k.REFERENCED_COLUMN_NAME ORDER BY k.ORDINAL_POSITION)"
                     " FROM information_schema.KEY_COLUMN_USAGE k WHERE k.TABLE_SCHEMA = %s AND k.REFERENCED_TABLE_NAME IS NOT NULL"
                     " GROUP BY k.TABLE_NAME, k.CONSTRAINT_NAME, k.REFERENCED_TABLE_NAME", (db,))


def test_only_kind_tables_reference_name(book):
    cn, db = book
    to_name = {(t, c.split(",")[0]): r for t, _fk, c, rt, r in _fks(cn, db) if rt == "name"}
    bad_shape = {k: r for k, r in to_name.items() if r != ("id" if k in KIND_REF_TO_NAME else "id,type")}
    assert not bad_shape, f"seat references name (id); the kind-checked columns name (id, type) (F168): {bad_shape}"
    assert set(KIND_REF_TO_NAME) <= set(to_name), f"each kind table links to name: {sorted(to_name)}"
    bad = sorted(set(to_name) - set(KIND_REF_TO_NAME) - NAME_REF_NO_OWN_DATA)
    assert not bad, f"only seat and the kinds with no data of their own reference name: {bad}"
    gen = _rows(cn, "SELECT TABLE_NAME, COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = %s"
                    " AND COLUMN_NAME LIKE 't\\_%%'", (db,))
    assert not gen, f"no generated type columns since the kind-table rework: {gen}"


def test_single_kind_columns_reference_their_kind_table(book):
    cn, db = book
    bad = []
    for t, fk, c, rt, r in _fks(cn, db):
        if "," in c or (t, c) in KIND_REF_TO_NAME:
            continue
        if c in DESK_COLS and (rt, r) != ("seat", "desk_id"):
            bad.append((t, fk, c, rt, r))
        if (c in ROSTER_COLS or (t in ROSTER_NAME_ID and c == "name_id")) and (rt, r) != ("name", "id"):
            bad.append((t, fk, c, rt, r))
    assert not bad, f"a desk column FKs to seat (desk_id), a roster column to name (id): {bad}"


def test_no_name_history_table(book):
    cn, db = book
    assert not _rows(cn, "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s"
                         " AND TABLE_NAME = 'name_event'", (db,))
    uniq = _rows(cn, "SELECT INDEX_NAME, GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX) FROM information_schema.STATISTICS"
                     " WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'name' AND NON_UNIQUE = 0 GROUP BY INDEX_NAME", (db,))
    assert sorted(uniq) == [("PRIMARY", "id"), ("idx_id_type", "id,type"), ("idx_type", "type,name")], uniq


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


def test_no_name_event_anywhere_in_the_book(book):
    # No name history (the owner): no table, trigger or routine names name_event, and the book has main's 22 tables (F166).
    cn, db = book
    tables = [t for (t,) in _rows(cn, "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s", (db,))]
    assert "name_event" not in tables
    assert len(tables) == 22, f"beta book has {len(tables)} tables"
    trig = _rows(cn, "SELECT TRIGGER_NAME FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA = %s"
                     " AND (TRIGGER_NAME LIKE '%%name\\_event%%' OR EVENT_OBJECT_TABLE = 'name_event'"
                     " OR ACTION_STATEMENT LIKE '%%name\\_event%%')", (db,))
    rout = _rows(cn, "SELECT ROUTINE_NAME FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA = %s"
                     " AND (ROUTINE_NAME LIKE '%%name\\_event%%' OR ROUTINE_DEFINITION LIKE '%%name\\_event%%')", (db,))
    assert not trig and not rout, f"still names name_event: triggers {trig}, routines {rout}"


# The owner (2026-10-25): a name kind gets its own table only if the thing has its own data. A roster has none, so
# there is no roster table and the seven roster columns reference name (id), with main's constraint names (F167).
ROSTER_FKS = {
    ("member", "fk_member_name", "name_id"): "RESTRICT",
    ("activity", "fk_activity_roster", "roster_id"): "RESTRICT",
    ("mail", "fk_mail_roster", "roster_id"): "RESTRICT",
    ("todo", "fk_todo_roster", "roster_id"): "RESTRICT",
    ("doing", "fk_doing_roster", "roster_id"): "RESTRICT",
    ("score", "fk_score_roster", "roster_id"): "RESTRICT",
    ("human_member", "fk_human_member_name", "name_id"): "CASCADE",
}


def test_no_roster_table_and_roster_columns_reference_name(book):
    cn, db = book
    tables = {t for (t,) in _rows(cn, "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s", (db,))}
    assert "roster" not in tables
    got = {(t, fk, c): (rt, rc, rule) for t, fk, c, rt, rc, rule in _rows(
        cn, "SELECT k.TABLE_NAME, k.CONSTRAINT_NAME, k.COLUMN_NAME, k.REFERENCED_TABLE_NAME, k.REFERENCED_COLUMN_NAME,"
            " r.DELETE_RULE FROM information_schema.KEY_COLUMN_USAGE k JOIN information_schema.REFERENTIAL_CONSTRAINTS r"
            " ON r.CONSTRAINT_SCHEMA = k.TABLE_SCHEMA AND r.CONSTRAINT_NAME = k.CONSTRAINT_NAME AND r.TABLE_NAME = k.TABLE_NAME"
            " WHERE k.TABLE_SCHEMA = %s AND k.REFERENCED_TABLE_NAME IS NOT NULL", (db,))}
    bad = {key: got.get(key) for key, rule in ROSTER_FKS.items() if got.get(key) != ("name", "id", rule)}
    assert not bad, f"each roster column FKs to name (id) with its rule: {bad}"
    assert not [k for k, v in got.items() if v[0] == "roster"], "nothing references a roster table"


# The owner (2026-10-25, approved review file): the eleven single-kind name references (twelve until the vote table
# was dropped, 2026-10-26) are kind-checked. Each has a
# plain `<x>_kind` ENUM pinned by DEFAULT and CHECK, and its FK is (col, <x>_kind) -> name (id, type), keeping the
# constraint name and ON DELETE rule. name carries UNIQUE idx_id_type (id, type) as the FK target. Desk columns keep
# referencing seat (desk_id) (F168).
KIND_FKS = {
    ("member", "fk_member_name"): ("name_id", "name_kind", "roster", "RESTRICT"),
    ("human_member", "fk_human_member_name"): ("name_id", "name_kind", "roster", "CASCADE"),
    ("activity", "fk_activity_roster"): ("roster_id", "roster_kind", "roster", "RESTRICT"),
    ("mail", "fk_mail_roster"): ("roster_id", "roster_kind", "roster", "RESTRICT"),
    ("todo", "fk_todo_roster"): ("roster_id", "roster_kind", "roster", "RESTRICT"),
    ("doing", "fk_doing_roster"): ("roster_id", "roster_kind", "roster", "RESTRICT"),
    ("score", "fk_score_roster"): ("roster_id", "roster_kind", "roster", "RESTRICT"),
    ("tree", "fk_tree_name"): ("name_id", "name_kind", "tree", "RESTRICT"),
    ("tree_read", "fk_tree_read_tree"): ("tree_id", "tree_kind", "tree", "RESTRICT"),
    ("label", "fk_label_name"): ("name_id", "name_kind", "label", "RESTRICT"),
    ("hold", "fk_hold_res"): ("resource_id", "resource_kind", "res", "RESTRICT"),
}
KINDS = ("desk", "roster", "label", "tree", "res")


def _one(cn, sql, args=()):
    cur = cn.cursor()
    try:
        cur.execute(sql, args)
        return cur.lastrowid
    finally:
        cur.close()


def test_kind_checked_fks_have_the_reviewed_shape(book):
    cn, db = book
    got = {}
    for t, fk, cols, rt, rcols, rule in _rows(
            cn, "SELECT k.TABLE_NAME, k.CONSTRAINT_NAME, GROUP_CONCAT(k.COLUMN_NAME ORDER BY k.ORDINAL_POSITION),"
                " k.REFERENCED_TABLE_NAME, GROUP_CONCAT(k.REFERENCED_COLUMN_NAME ORDER BY k.ORDINAL_POSITION),"
                " r.DELETE_RULE FROM information_schema.KEY_COLUMN_USAGE k JOIN information_schema.REFERENTIAL_CONSTRAINTS r"
                " ON r.CONSTRAINT_SCHEMA = k.TABLE_SCHEMA AND r.CONSTRAINT_NAME = k.CONSTRAINT_NAME AND r.TABLE_NAME = k.TABLE_NAME"
                " WHERE k.TABLE_SCHEMA = %s AND k.REFERENCED_TABLE_NAME = 'name'"
                " GROUP BY k.TABLE_NAME, k.CONSTRAINT_NAME, k.REFERENCED_TABLE_NAME, r.DELETE_RULE", (db,)):
        got[(t, fk)] = (cols, rt, rcols, rule)
    want = {key: (f"{c},{kc}", "name", "id,type", rule) for key, (c, kc, _k, rule) in KIND_FKS.items()}
    want[("seat", "fk_seat_desk")] = ("desk_id", "name", "id", "RESTRICT")
    assert got == want, f"FKs to name: {sorted(set(got.items()) ^ set(want.items()))}"
    cols = {(t, c): (ty, dflt, nul) for t, c, ty, dflt, nul in _rows(
        cn, "SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE, COLUMN_DEFAULT, IS_NULLABLE FROM information_schema.COLUMNS"
            " WHERE TABLE_SCHEMA = %s AND COLUMN_NAME LIKE '%%\\_kind'", (db,))}
    enum = "enum(" + ",".join(f"'{k}'" for k in KINDS) + ")"
    assert cols == {(t, kc): (enum, k, "NO") for (t, _fk), (_c, kc, k, _r) in KIND_FKS.items()}, cols
    checks = {(t, cc.replace("`", "").replace("_utf8mb4", "").replace("\\'", "'")) for t, cc in _rows(
        cn, "SELECT t.TABLE_NAME, c.CHECK_CLAUSE FROM information_schema.CHECK_CONSTRAINTS c JOIN"
            " information_schema.TABLE_CONSTRAINTS t ON t.CONSTRAINT_SCHEMA = c.CONSTRAINT_SCHEMA"
            " AND t.CONSTRAINT_NAME = c.CONSTRAINT_NAME WHERE c.CONSTRAINT_SCHEMA = %s AND c.CHECK_CLAUSE LIKE '%%\\_kind%%'",
        (db,))}
    assert checks == {(t, f"({kc} = '{k}')") for (t, _fk), (_c, kc, k, _r) in KIND_FKS.items()}, checks
    uniq = _rows(cn, "SELECT INDEX_NAME, GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX) FROM information_schema.STATISTICS"
                     " WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'name' AND NON_UNIQUE = 0 GROUP BY INDEX_NAME", (db,))
    assert ("idx_id_type", "id,type") in uniq, uniq


def test_wrong_kind_name_id_is_refused_for_each_kind_checked_column(book):
    # One name of each kind; each of the eleven columns takes its own kind and refuses the other four (FK, 1452).
    import mysql.connector

    cn, db = book
    ids = {k: _one(cn, "INSERT INTO name (type, name) VALUES (%s, %s)", (k, f"kchk-{k}")) for k in KINDS}
    desk = ids["desk"]
    _one(cn, "INSERT INTO seat (desk_id) VALUES (%s)", (desk,))
    human = _one(cn, "INSERT INTO human (bearer_hash) VALUES (%s)", ("k" * 64,))
    mail = _one(cn, "INSERT INTO mail (desk_id, roster_id, body) VALUES (%s, 1, 'kchk')", (desk,))
    _one(cn, "INSERT INTO activity (type, id, desk_id, roster_id) VALUES ('mail', %s, %s, 1)", (mail, desk))
    writes = {
        "member": ("INSERT INTO member (name_id, desk_id) VALUES (%s, %s)", lambda x: (x, desk)),
        "human_member": ("INSERT INTO human_member (human_id, name_id) VALUES (%s, %s)", lambda x: (human, x)),
        "activity": ("INSERT INTO activity (type, id, desk_id, roster_id) VALUES ('todo', 990001, %s, %s)",
                     lambda x: (desk, x)),
        "mail": ("INSERT INTO mail (desk_id, roster_id, body) VALUES (%s, %s, 'k')", lambda x: (desk, x)),
        "todo": ("INSERT INTO todo (updated_id, roster_id, creator_id) VALUES (%s, %s, %s)", lambda x: (desk, x, desk)),
        "doing": ("INSERT INTO doing (desk_id, roster_id) VALUES (%s, %s)", lambda x: (desk, x)),
        "score": ("INSERT INTO score (desk_id, roster_id, kpi) VALUES (%s, %s, 'kchk')", lambda x: (desk, x)),
        "tree": ("INSERT INTO tree (name_id, type, id, lft, rgt) VALUES (%s, 'mail', %s, 1, 2)", lambda x: (x, mail)),
        "tree_read": ("INSERT INTO tree_read (desk_id, tree_id, last_id) VALUES (%s, %s, 0)", lambda x: (desk, x)),
        "label": ("INSERT INTO label (type, id, name_id) VALUES ('mail', %s, %s)", lambda x: (mail, x)),
        "hold": ("INSERT INTO hold (desk_id, resource_id) VALUES (%s, %s)", lambda x: (desk, x)),
    }
    assert set(writes) == {t for t, _fk in KIND_FKS}
    wrong_ok, right_refused = [], []
    for (table, _fk), (_c, _kc, kind, _r) in KIND_FKS.items():
        sql, args = writes[table]
        for k in KINDS:
            cn.start_transaction()
            try:
                _one(cn, sql, args(ids[k]))
                if k != kind:
                    wrong_ok.append((table, k))
            except mysql.connector.Error as exc:
                if k == kind or exc.errno != 1452:
                    right_refused.append((table, k, exc.errno, str(exc)[:120]))
            finally:
                cn.rollback()
    assert not right_refused, f"a right-kind id (or a wrong kind with an error other than FK 1452): {right_refused}"
    assert not wrong_ok, f"a wrong-kind name id was accepted: {wrong_ok}"


def _declared_keys():
    # (table, index) for every key the DDL text declares, with whether it is UNIQUE. PRIMARY is always declared.
    import re

    ddl = (ROOT / "docs" / "requirements" / "beta" / "beta_ddl.sql").read_text(encoding="utf-8")
    out = {}
    for t, body in re.findall(r"^CREATE TABLE IF NOT EXISTS (\w+) \((.*?)^\)", ddl, re.M | re.S):
        for uniq, name in re.findall(r"^\s*(UNIQUE )?KEY (\w+) \(", body, re.M):
            out[(t, name)] = bool(uniq)
    return out


def test_no_implicit_indexes_beyond_primary_and_unique(book):
    # The owner (2026-10-25): PRIMARY and UNIQUE keys are indexed by definition; every other index is declared in the
    # DDL and named idx_*. An index MySQL creates for an FK (not declared in the DDL) is refused, so each FK must lead
    # a PRIMARY, a UNIQUE or a declared idx_* key (F169).
    cn, db = book
    declared = _declared_keys()
    got = {(t, i): nu for t, i, nu in _rows(
        cn, "SELECT DISTINCT TABLE_NAME, INDEX_NAME, NON_UNIQUE FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = %s",
        (db,))}
    fk_names = {(t, fk) for t, fk in _rows(
        cn, "SELECT TABLE_NAME, CONSTRAINT_NAME FROM information_schema.REFERENTIAL_CONSTRAINTS WHERE CONSTRAINT_SCHEMA = %s",
        (db,))}
    implicit = sorted(k for k in got if k[1] != "PRIMARY" and k not in declared)
    assert not implicit, f"indexes MySQL created for an FK (not declared in the DDL): {implicit}"
    assert not sorted(set(got) & fk_names), "an index named after an FK constraint"
    badname = sorted(k for k, uniq in declared.items() if not uniq and not k[1].startswith("idx_"))
    assert not badname, f"a declared non-unique key must be named idx_*: {badname}"
    assert sorted(k for k in declared if k not in got) == [], "a declared key the book does not have"
