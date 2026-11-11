"""Card 986: shared vs fresh DB naming and group markers (no MySQL)."""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from tests import sql_book


def test_shared_db_name_uses_xdist_worker(monkeypatch):
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw1")
    assert sql_book.shared_db_name() == "mill_sql_shared_gw1"


def test_fresh_db_name_unique_per_nodeid(monkeypatch):
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw0")
    a = sql_book.fresh_db_name("mill_parity", nodeid="mod::test_a")
    b = sql_book.fresh_db_name("mill_parity", nodeid="mod::test_b")
    assert a != b
    assert a.startswith("mill_parity_gw0_")
    assert len(a) <= 64


def test_fresh_db_name_stable_for_same_node(monkeypatch):
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw2")
    a = sql_book.fresh_db_name("mill_x", nodeid="n1")
    b = sql_book.fresh_db_name("mill_x", nodeid="n1")
    assert a == b


# Tables in tables.sql that reset_data must not truncate (reference data kept across modules). Empty today: every
# table holds test data, and transition_edge is truncated then reseeded. A new table goes in DATA_TABLES or here.
NOT_DATA_TABLES: frozenset[str] = frozenset()


def test_data_tables_cover_tip_pack_tables():
    """Every CREATE TABLE in tables.sql is in DATA_TABLES or named in NOT_DATA_TABLES, so none is left uncleared."""
    tables_sql = Path(__file__).resolve().parents[1] / "agent_coord" / "server" / "sql" / "tables.sql"
    created = set(re.findall(r"CREATE TABLE(?: IF NOT EXISTS)?\s+`?(\w+)`?", tables_sql.read_text(encoding="utf-8"),
                             flags=re.IGNORECASE))
    assert {"name", "activity", "activity_history", "todo", "mail", "seat"} <= created  # the parse found tables
    data = set(sql_book.DATA_TABLES)
    assert len(data) == len(sql_book.DATA_TABLES), "DATA_TABLES lists a table twice"
    assert not data & NOT_DATA_TABLES, "a table is both data and not data"
    assert sorted(created - data - NOT_DATA_TABLES) == [], "add each new table to DATA_TABLES or NOT_DATA_TABLES"
    assert sorted((data | NOT_DATA_TABLES) - created) == [], "DATA_TABLES names a table tables.sql no longer creates"
