"""Card roster_id is NOT NULL: an insert that omits it fails.

apply_roster_070 / the NOT NULL punch still run in ensure(); this keeps the
insert-without guard. The throwaway A/B backfill case targeted a pre-0.8.0
nullable shape and is not restored.
"""
from __future__ import annotations

import pytest

from agent_coord.server.records.db import scalar
from tests.server.records.conftest import seed_names

pytestmark = pytest.mark.sql


def _exec(cn, sql: str, args=()) -> None:
    cur = cn.cursor()
    try:
        cur.execute(sql, args)
        cn.commit()
    finally:
        cur.close()


def test_insert_without_roster_id_fails(cn) -> None:
    """Alpha NOT NULL: omitting roster_id must fail (no DEFAULT 1 / Office)."""
    seed_names(cn, ("nn_desk", "desk"))
    desk = int(scalar(cn, "SELECT id FROM name WHERE type='desk' AND name='nn_desk'"))
    office = int(scalar(cn, "SELECT id FROM name WHERE type = 'roster' AND name='Office'"))
    _exec(cn, "SET FOREIGN_KEY_CHECKS=0")
    with pytest.raises(Exception) as ei:
        _exec(
            cn,
            "INSERT INTO mail (desk_id, body) VALUES (%s, 'missing-affil')",
            (desk,),
        )
    msg = str(ei.value).lower()
    assert "roster_id" in msg or "doesn't have a default" in msg or "cannot be null" in msg
    with pytest.raises(Exception):
        _exec(
            cn,
            "INSERT INTO todo (updated_id, creator_id, status, body) "
            "VALUES (%s, %s, 'open', 'missing-affil')",
            (desk, desk),
        )
    with pytest.raises(Exception):
        _exec(
            cn,
            "INSERT INTO score (desk_id, kpi, value, target, note) "
            "VALUES (%s, 'nn.kpi', '0', '', '')",
            (desk,),
        )
    # Explicit value still works (seed path shape).
    _exec(
        cn,
        "INSERT INTO score (desk_id, roster_id, kpi, value, target, note) "
        "VALUES (%s, %s, 'nn.kpi.ok', '0', '', '')",
        (desk, office),
    )
    _exec(cn, "SET FOREIGN_KEY_CHECKS=1")
