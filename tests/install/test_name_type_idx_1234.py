"""Card 1234: name gets a plain (type, name) key back; idx_name stays the one unique name key.

A fresh install (tables.sql), a main book (0.7.18) after migrate.ensure, and a tip book that lost the key
(the 0.8.15 shape) after migrate.ensure all show the same SHOW INDEX FROM name. A type-filtered name read
uses idx_type_name (EXPLAIN). apply_080 leaves a card 1163 book alone, so it never puts idx_id_type back.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TABLES = ROOT / "agent_coord" / "server" / "sql" / "tables.sql"
BETA_DDL = ROOT / "docs" / "requirements" / "beta" / "beta_ddl.sql"
MIGRATE = ROOT / "agent_coord" / "install" / "migrate.py"
DESIGN = ROOT / "docs" / "requirements" / "schema-design.md"

# (Key_name, Non_unique, Seq_in_index, Column_name) on every book.
WANT = [
    ("PRIMARY", 0, 1, "id"),
    ("idx_name", 0, 1, "name"),
    ("idx_type_name", 1, 1, "type"),
    ("idx_type_name", 1, 2, "name"),
]


def _name_ddl(path: Path) -> str:
    m = re.search(r"^CREATE TABLE IF NOT EXISTS name \((.*?)^\)", path.read_text(encoding="utf-8"), re.M | re.S)
    assert m, path
    return m.group(1)


@pytest.mark.parametrize("path", [TABLES, BETA_DDL], ids=["tables.sql", "beta_ddl.sql"])
def test_name_ddl_declares_plain_type_name_key(path: Path) -> None:
    body = _name_ddl(path)
    assert re.search(r"^\s*KEY idx_type_name \(type, name\)", body, re.M), body
    assert re.search(r"^\s*UNIQUE KEY idx_name \(name\)", body, re.M), body
    assert len(re.findall(r"UNIQUE KEY", body)) == 1, "idx_name is the only unique name key"


def test_ensure_adds_the_key_after_1163() -> None:
    src = MIGRATE.read_text(encoding="utf-8")
    assert "ALTER TABLE name ADD KEY idx_type_name (type, name)" in src
    steps = src[src.index("def _ensure_steps("):]
    assert steps.index("apply_1163(cn)") < steps.index("_ensure_name_type_idx(cn)") < steps.index("apply_1200(cn)")
    design = DESIGN.read_text(encoding="utf-8")
    assert "idx_type_name" in design and "card 1234" in design.lower()


def _show_index(cn) -> list[tuple]:
    cur = cn.cursor(dictionary=True)
    try:
        cur.execute("SHOW INDEX FROM name")
        rows = cur.fetchall()
    finally:
        cur.close()
    return sorted((r["Key_name"], int(r["Non_unique"]), int(r["Seq_in_index"]), r["Column_name"]) for r in rows)


def _mysql_up() -> None:
    try:
        from tests.beta_book import admin_conn

        cn, _ = admin_conn()
        cn.close()
    except Exception as exc:  # no MySQL here
        pytest.skip(f"no MySQL for the card 1234 index tests: {exc}")


@pytest.fixture(scope="module")
def fresh_index():
    _mysql_up()
    from tests.beta_book import drop_db, make_fresh_book

    cn, db = make_fresh_book("mill_n1234_fresh")
    try:
        return _show_index(cn)
    finally:
        drop_db(cn, db)


@pytest.mark.sql
@pytest.mark.fresh_schema
def test_fresh_install_has_the_name_keys(fresh_index) -> None:
    assert fresh_index == WANT


@pytest.mark.sql
@pytest.mark.fresh_schema
def test_upgraded_main_book_matches_fresh(fresh_index) -> None:
    from agent_coord.install import migrate
    from tests.beta_book import drop_db, make_main_book

    cn, db = make_main_book("mill_n1234_main")
    try:
        applied = [str(a) for a in migrate.ensure(cn)["applied"]]
        assert "name.idx_type_name" in applied, applied
        assert _show_index(cn) == fresh_index
        assert migrate._ensure_name_type_idx(cn) == []
    finally:
        drop_db(cn, db)


@pytest.mark.sql
@pytest.mark.fresh_schema
def test_upgraded_0815_book_matches_fresh(cn, fresh_index) -> None:
    """A tip book without idx_type_name (what 0.8.15 installed) gets it from ensure, once."""
    from agent_coord.install import migrate

    cur = cn.cursor()
    cur.execute("ALTER TABLE name DROP INDEX idx_type_name")
    cur.close()
    cn.commit()
    applied = [str(a) for a in migrate.ensure(cn)["applied"]]
    assert "name.idx_type_name" in applied, applied
    assert _show_index(cn) == fresh_index
    again = [str(a) for a in migrate.ensure(cn)["applied"]]
    assert "name.idx_type_name" not in again, again
    # Card 1234 item 1: on a card 1163 book apply_080 is a no-op, so migrate_080.sql's idx_id_type
    # step never runs and the keys stay as tables.sql has them.
    assert migrate.apply_080(cn) == []
    assert _show_index(cn) == fresh_index


@pytest.mark.sql
@pytest.mark.fresh_schema
def test_type_filtered_read_uses_idx_type_name(cn) -> None:
    cur = cn.cursor()
    rows = [(t, f"n1234-{t}-{i:03d}") for t in ("label", "roster", "tree", "res") for i in range(60)]
    cur.executemany("INSERT INTO name (type, name) VALUES (%s, %s)", rows)
    cn.commit()
    cur.execute("ANALYZE TABLE name")
    cur.fetchall()
    cur.close()
    cur = cn.cursor(dictionary=True)
    try:
        cur.execute("EXPLAIN SELECT id, name FROM name WHERE type = 'label' ORDER BY name")
        plan = cur.fetchall()
        cur.execute("SELECT name FROM name WHERE type = 'label' AND name LIKE 'n1234-%' ORDER BY name")
        got = [r["name"] for r in cur.fetchall()]
    finally:
        cur.close()
    assert [p["key"] for p in plan] == ["idx_type_name"], plan
    assert "filesort" not in str(plan[0].get("Extra") or "").lower(), plan
    assert got == sorted(n for t, n in rows if t == "label")
