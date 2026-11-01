"""score_tick office KPIs are owned by the office: roster Office, no desk (beta 0.8.0; main used the Admin roster)."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.sql

from agent_coord.server.records import score as rec_score
from agent_coord.server.records.db import conn_kwargs as _conn_kwargs
from agent_coord.server.records.db import scalar
from tests.server.records.conftest import seed_names

def _office_admin(cn) -> tuple[int, int]:
    return (
        scalar(cn, "SELECT id FROM name WHERE type='roster' AND name='Office'"),
        scalar(cn, "SELECT id FROM name WHERE type='roster' AND name='Admin'"),
    )

def _admin_rows(cn, kpi: str) -> list[tuple]:
    cn.commit()  # end this connection's snapshot; publish writes on its own connection
    cur = cn.cursor()
    try:
        cur.execute(
            "SELECT s.id, s.value, s.target FROM score s"
            " JOIN name a ON a.id = s.roster_id AND a.type='roster' AND a.name='Office'"
            " WHERE s.desk_id IS NULL AND s.kpi = %s",
            (kpi,),
        )
        return [tuple(r) for r in cur.fetchall()]
    finally:
        cur.close()

def test_admin_is_a_roster_and_old_upsert_refuses(cn):
    from agent_coord.helpers.errors import CoordError  # noqa: F401  (import path check)

    assert scalar(cn, "SELECT COUNT(*) FROM name WHERE name='Admin' AND type='desk'") == 0
    with pytest.raises(Exception, match="no such desk"):
        rec_score.upsert(cn, "Office", "Admin", "mill-wall.ticks", "1", "0", "")

def test_publish_writes_office_rows_with_no_desk(cn):
    from agent_coord.client.tokens import token_hash
    from agent_coord.server import glance, score_tick
    from agent_coord.server.records import join as rec_join

    seed_names(cn, ("sa_live", "desk"), ("Office", "roster"))
    # 0.8.0: score.desk_id FKs to seat; a desk needs a seat before a desk-owned score.
    rec_join.upsert(cn, "Office", "sa_live", "", token_hash("seat-sa_live"), None)
    cn.commit()
    counts = {score_tick.KPI_TICKS: 5, score_tick.KPI_API_N: 77, "desks": {"sa_live": {score_tick.KPI_TICKS: 2}}}
    out = score_tick.publish(dict(counts))
    assert out["ok"] is True and "fallback" not in out, out
    assert [r[1] for r in _admin_rows(cn, score_tick.KPI_TICKS)] == ["5"]
    assert [r[1] for r in _admin_rows(cn, score_tick.KPI_API_N)] == ["77"]
    live = scalar(
        cn,
        "SELECT s.value FROM score s JOIN name d ON d.id=s.desk_id AND d.type='desk' AND d.name='sa_live'"
        " WHERE s.kpi=%s",
        (score_tick.KPI_TICKS,),
    )
    assert live == "2"
    seen = glance._office_scores(cn)
    assert score_tick.KPI_API_N in seen

def test_second_publish_updates_the_same_row(cn):
    from agent_coord.server import score_tick

    score_tick.publish({score_tick.KPI_TICKS: 1})
    first = _admin_rows(cn, score_tick.KPI_TICKS)
    score_tick.publish({score_tick.KPI_TICKS: 9})
    second = _admin_rows(cn, score_tick.KPI_TICKS)
    assert len(first) == len(second) == 1  # the tables.sql seed row, not a duplicate
    assert first[0][0] == second[0][0] and second[0][1] == "9"

def test_admin_upsert_adds_no_watcher_and_an_activity(cn):
    office, _admin = _office_admin(cn)
    sid = int(rec_score.admin_upsert(cn, "mill-wall.err_n", "3", "0", "n")[0]["id"])
    assert scalar(cn, "SELECT COUNT(*) FROM watcher WHERE type='score' AND id=%s", (sid,)) == 0
    assert scalar(cn, "SELECT COUNT(*) FROM activity WHERE type='score' AND id=%s AND desk_id IS NULL", (sid,)) == 1
    assert scalar(cn, "SELECT roster_id FROM score WHERE id=%s", (sid,)) == office

def test_soft_deleted_office_score_revives(cn):
    sid = int(rec_score.admin_upsert(cn, "todo.open", "1", "", "n")[0]["id"])
    cur = cn.cursor()
    cur.execute("UPDATE activity SET deleted = CURRENT_TIMESTAMP(6) WHERE type='score' AND id=%s", (sid,))
    cur.close()
    cn.commit()
    again = int(rec_score.admin_upsert(cn, "todo.open", "2", "", "n")[0]["id"])
    assert again == sid
    assert scalar(cn, "SELECT deleted FROM activity WHERE type='score' AND id=%s", (sid,)) is None

def test_empty_kpi_refused(cn):
    with pytest.raises(Exception, match="kpi required"):
        rec_score.admin_upsert(cn, "", "1", "", "")

def test_office_rows_do_not_need_the_admin_roster(cn):
    # Beta 0.8.0: an office score has no owner name, so a retired Admin roster does not stop it.
    from agent_coord.server import score_tick

    cur = cn.cursor()
    cur.execute("UPDATE name SET deleted = CURRENT_TIMESTAMP(6) WHERE type='roster' AND name='Admin'")
    cur.close()
    cn.commit()
    rec_score.admin_upsert(cn, "mill-wall.ticks", "1", "0", "")
    out = score_tick.publish({score_tick.KPI_TICKS: 4})
    assert out["ok"] is True and "fallback" not in out, out
    assert [r[1] for r in _admin_rows(cn, score_tick.KPI_TICKS)] == ["4"]

def test_gone_desk_in_logs_is_skipped_office_still_publishes(cn):
    from agent_coord.server import score_tick

    seed_names(cn, ("sa_ok", "desk"))
    out = score_tick.publish(
        {
            score_tick.KPI_ERR_N: 2,
            "desks": {"sa_gone": {score_tick.KPI_TICKS: 1}, "sa_ok": {score_tick.KPI_TICKS: 4}},
        }
    )
    assert out["ok"] is True and "fallback" not in out
    assert [s["desk"] for s in out.get("skipped", [])] == ["sa_gone"]
    assert [r[1] for r in _admin_rows(cn, score_tick.KPI_ERR_N)] == ["2"]
    assert any(r.get("desk") == "sa_ok" for r in out["rows"])

def test_score_add_is_owned_by_the_office(cn):
    from agent_coord.server import score_tick

    out = score_tick.score_add("todo.open")
    assert out["ok"] is True, out
    assert len(_admin_rows(cn, "todo.open")) == 1
