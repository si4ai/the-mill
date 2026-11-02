"""Attempt 2: core tables live in sql/tables.sql, not schema.sql."""
from __future__ import annotations

from agent_coord.install import migrate


def test_sql_dir_has_core_tables() -> None:
    tables = (migrate.sql_dir() / "tables.sql").read_text(encoding="utf-8")
    blob = tables.lower()
    for table in ("name", "activity", "mail", "mail_to", "member", "todo", "seat", "doing", "hold", "score", "tree", "watcher", "label", "wake", "transition"):
        needle = f"create table if not exists `{table}`" if table == "join" else f"create table if not exists {table}"
        assert needle in blob, table
    for gone in ("agent_msg", "agent_need", "agent_proc", "agent_issue", "agent_leftover"):
        assert f"create table {gone}" not in blob, gone
    assert "mill-wall.ticks" in tables
    assert "mill-desk.idle_verbs" in tables


def test_no_old_stupid() -> None:
    assert not (migrate.sql_dir() / "old_stupid.sql").exists()


def test_no_migrations_ladder() -> None:
    assert not (migrate.schema_path().parent / "migrations").exists()


def test_split_sql_strips_comments() -> None:
    parts = migrate._split_sql("SELECT 1;\n-- comment\nSELECT 2;\n")
    assert parts == ["SELECT 1", "SELECT 2"]

def test_mill_tree_move_parks_unsigned_safe() -> None:
    """lft/rgt are INT UNSIGNED; move must not negate."""
    sql = (migrate.sql_dir() / "sp_tree.sql").read_text(encoding="utf-8")
    start = sql.index("CREATE PROCEDURE mill_tree_move")
    end = sql.index("END //", start) + len("END //")
    body = sql[start:end]
    assert "0 - lft" not in body
    assert "0 - rgt" not in body
    assert "lft < 0" not in body
    assert "MAX(rgt)" in body
    assert "v_shift" in body

