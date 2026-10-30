"""0.7.0 roster migration helpers still run in ensure() (apply_roster_070).

Kept after 0.8.0: a fresh book needs nothing, and the old project/role types
are refused. The collision and full-legacy migrate cases target a 0.6-shaped
book 0.8.0 no longer builds; they are not restored.
"""
from __future__ import annotations

import pytest

from agent_coord.install.migrate import apply_roster_070, roster_070_needed

pytestmark = pytest.mark.sql


def _q(cn, sql, args=()):
    cur = cn.cursor()
    try:
        cur.execute(sql, args)
        return cur.fetchall() if cur.with_rows else []
    finally:
        cur.close()


def test_fresh_book_needs_nothing(cn):
    assert roster_070_needed(cn) is False
    assert apply_roster_070(cn) == []


def test_old_types_refused_after_migrate(cn):
    with pytest.raises(Exception):
        _q(cn, "SELECT MILL_NAME_PUT('project', 'nope-070')")
    assert _q(cn, "SELECT MILL_NAME_GET('roster', 'never-minted-070')") == [(None,)]
    assert _q(cn, "SELECT COUNT(*) FROM name WHERE name = 'never-minted-070'") == [(0,)]
