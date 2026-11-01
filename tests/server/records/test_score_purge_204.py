"""#204: the 30-day evidence purge is not a side effect of one score write."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.sql

from agent_coord.install import migrate
from agent_coord.server.records.db import call
from agent_coord.server.records.db import conn_kwargs as _conn_kwargs
from tests.server.records.conftest import seed_names

NOW = "2026-10-02 12:00:00"

def _score_id(cn, desk: str) -> int:
    cur = cn.cursor()
    cur.execute(
        "SELECT s.id FROM score s JOIN name d ON d.id = s.desk_id "
        "WHERE d.name=%s AND s.kpi='system'",
        (desk,),
    )
    row = cur.fetchone()
    cur.close()
    assert row is not None
    return int(row[0])

def _has(cn, desk: str, stamp: str) -> bool:
    cur = cn.cursor()
    cur.execute(
        "SELECT 1 FROM score_evidence e JOIN score s ON s.id = e.score_id "
        "JOIN name d ON d.id = s.desk_id "
        "WHERE d.name=%s AND s.kpi='system' AND e.`timestamp`=%s",
        (desk, stamp),
    )
    row = cur.fetchone()
    cur.close()
    return row is not None

def _insert_day(cn, desk: str, stamp: str) -> None:
    cur = cn.cursor()
    cur.execute(
        "INSERT INTO score_evidence (score_id, `timestamp`, value, taken) "
        "VALUES (%s, %s, JSON_OBJECT('n', 1), DATE(%s))",
        (_score_id(cn, desk), stamp, stamp),
    )
    cn.commit()
    cur.close()

def test_write_does_not_purge_and_purge_covers_an_idle_desk(cn) -> None:
    seed_names(cn, ("sp204_a", "desk"), ("sp204_b", "desk"))
    call(cn, "mill_score_event", ["sp204_a", "inbox", 5, 1, 1, NOW])
    _insert_day(cn, "sp204_a", "2026-08-01 00:00:00")
    _insert_day(cn, "sp204_a", "2026-09-01 00:00:00")
    _insert_day(cn, "sp204_a", "2026-09-02 00:00:00")
    call(cn, "mill_score_event", ["sp204_a", "inbox", 5, 1, 1, NOW])
    call(cn, "mill_score_event", ["sp204_b", "inbox", 5, 1, 1, NOW])
    assert _has(cn, "sp204_a", "2026-08-01 00:00:00")
    assert _has(cn, "sp204_a", "2026-09-01 00:00:00")
    assert _has(cn, "sp204_a", "2026-09-02 00:00:00")
    assert _has(cn, "sp204_a", "2026-10-02 00:00:00")
    assert _has(cn, "sp204_a", "1970-01-01 12:00:00")
    call(cn, "mill_score_evidence_purge", [NOW])
    assert not _has(cn, "sp204_a", "2026-08-01 00:00:00")
    assert not _has(cn, "sp204_a", "2026-09-01 00:00:00")
    assert _has(cn, "sp204_a", "2026-09-02 00:00:00")
    assert _has(cn, "sp204_a", "2026-10-02 00:00:00")
    assert _has(cn, "sp204_a", "1970-01-01 12:00:00")
    assert _has(cn, "sp204_b", "2026-10-02 00:00:00")

def test_ensure_installs_the_purge(cn) -> None:
    cur = cn.cursor()
    cur.execute("DROP PROCEDURE IF EXISTS mill_score_evidence_purge")
    cur.execute(
        "CREATE PROCEDURE mill_score_evidence_purge(IN p_now DATETIME(6)) BEGIN SELECT 1 AS n; END"
    )
    cn.commit()
    cur.close()
    migrate.ensure(cn)
    cur = cn.cursor()
    cur.execute(
        "SELECT ROUTINE_DEFINITION FROM information_schema.ROUTINES "
        "WHERE ROUTINE_SCHEMA = DATABASE() AND ROUTINE_NAME = 'mill_score_evidence_purge'"
    )
    body = str(cur.fetchone()[0] or "")
    cur.close()
    assert "1970-01-02" in body
