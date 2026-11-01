"""Card 986: shared vs fresh DB naming and group markers (no MySQL)."""
from __future__ import annotations

import os

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


def test_data_tables_cover_tip_pack_tables():
    # name and activity must reset; invite tables too.
    for t in ("name", "activity", "todo", "mail", "seat", "doing"):
        assert t in sql_book.DATA_TABLES
