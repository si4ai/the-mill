"""Card 1163 collision suffix and the type-trigger text. No database."""
from __future__ import annotations

from pathlib import Path

import pytest

from agent_coord.install.migrate import (
    NAME_RANK_1163,
    Migrate1163Refused,
    free_name_suffix,
    name_type_trigger_sql,
)

ROOT = Path(__file__).resolve().parents[2]


def test_rank_is_res_then_desk_roster_tree_label():
    assert NAME_RANK_1163 == ("res", "desk", "roster", "tree", "label")


def test_first_free_suffix_is_name_1():
    assert free_name_suffix("foo", lambda _c: False) == "foo-1"


def test_taken_suffix_is_skipped():
    taken = {"foo-1", "foo-2"}
    assert free_name_suffix("foo", taken.__contains__) == "foo-3"


def test_suffix_of_64_characters_is_kept():
    base = "n" * 62
    got = free_name_suffix(base, lambda _c: False)
    assert got == base + "-1"
    assert len(got) == 64


def test_suffix_past_64_is_refused():
    base = "n" * 63
    with pytest.raises(Migrate1163Refused, match="64"):
        free_name_suffix(base, lambda _c: False)


def test_both_ddl_files_carry_the_same_name_type_triggers():
    tables = (ROOT / "agent_coord/server/sql/tables.sql").read_text(encoding="utf-8")
    beta = (ROOT / "docs/requirements/beta/beta_ddl.sql").read_text(encoding="utf-8")
    got_tables = name_type_trigger_sql(tables)
    got_beta = name_type_trigger_sql(beta)
    assert [name for name, _stmt in got_tables] == [name for name, _stmt in got_beta]
    assert len(got_tables) == 24
    assert got_tables[0][0] == "seat_desk_type_ins"
    seen = set()
    for (name, stmt), (_other, beta_stmt) in zip(got_tables, got_beta):
        assert name not in seen
        seen.add(name)
        assert stmt == beta_stmt
        assert "CONTINUE HANDLER FOR NOT FOUND" in stmt
        assert "IS NOT NULL AND v_type <>" in stmt
        assert stmt.upper().startswith("CREATE TRIGGER")
