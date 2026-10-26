"""0.7.6 score fixes on a real book (Gardener's live test of 0.7.5).

F36 score-one-name (#305): an upgrade retires or adopts the 0.7.4 per-desk rows
  of a name, and a read never returns an empty legacy row.
F37 score-define (#306): --target/--better/--unit without a VALUE set them, no point.
F39 score-at (#308): --at orders points by time; a backfill never becomes latest.
F40 score-retire (#302): retire score ROSTER NAME, by a recording desk or Admin.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.sql

from agent_coord.helpers.errors import CoordError
from agent_coord.install import migrate
from agent_coord.server.api.mill import rpc
from agent_coord.server.records import score as rec_score
from tests.server.records.conftest import seed_names
from tests.server.records.test_room_reply import _Book


def _q(cn, sql: str, args=()):
    cur = cn.cursor()
    cur.execute(sql, args)
    rows = cur.fetchall()
    cur.close()
    return rows


def _live(cn, roster: str, kpi: str) -> list[tuple]:
    return _q(
        cn,
        "SELECT s.id, s.desk_id IS NULL FROM score s JOIN name r ON r.id = s.roster_id"
        " JOIN activity a ON a.type = 'score' AND a.id = s.id AND a.deleted IS NULL"
        " WHERE r.name = %s AND s.kpi = %s ORDER BY s.id",
        (roster, kpi),
    )


# F36


def test_empty_legacy_row_never_reads_before_the_first_point(cn) -> None:
    seed_names(cn, ("s76a", "roster"), ("g76", "desk"))
    rec_score.upsert(cn, "s76a", "g76", "probe", "", "", "")  # the 0.7.4 shape: empty, desk-owned
    with pytest.raises(CoordError, match="no score probe on s76a"):
        rpc._h_score(_Book(cn), {"name": "probe"}, "s76a", "g76")
    rpc._h_score(_Book(cn), {"name": "probe", "value": "6"}, "s76a", "g76")
    got = rpc._h_score(_Book(cn), {"name": "probe"}, "s76a", "g76")
    assert got["latest"] == 6 and got["owner"] == "s76a"


def test_upgrade_leaves_one_score_per_name(cn) -> None:
    seed_names(cn, ("s76b", "roster"), ("Office", "roster"), ("ga", "desk"), ("gb", "desk"), ("gc", "desk"))
    # 1: empty legacy beside the 0.7.5 definition -> retired.
    rec_score.upsert(cn, "s76b", "ga", "dup", "", "", "")
    rpc._h_score(_Book(cn), {"name": "dup", "value": "3"}, "s76b", "ga")
    # 2: three legacy desk rows with values, no definition -> newest adopted, others retired.
    for d, v in (("ga", "2"), ("gb", "5"), ("gc", "4")):
        rec_score.upsert(cn, "s76b", d, "agent_kpi", v, "", "")
    # 3: an empty legacy row alone -> retired.
    rec_score.upsert(cn, "s76b", "gb", "empty", "", "", "")
    # 4: Office per-desk host rows are system KPIs -> untouched.
    rec_score.upsert(cn, "Office", "ga", "mill-desk.x", "0", "", "")
    rec_score.upsert(cn, "Office", "gb", "mill-desk.x", "0", "", "")
    first = migrate._ensure_score_one_name(cn)
    # Other tests in this module leave legacy rows too; the states below are what count.
    assert any(x.startswith("score.one_name(adopt ") for x in first)
    assert any(x.startswith("score.one_name(retire ") for x in first)
    assert [r[1] for r in _live(cn, "s76b", "dup")] == [1]
    kpi = _live(cn, "s76b", "agent_kpi")
    assert len(kpi) == 1 and kpi[0][1] == 1
    assert rpc._h_score(_Book(cn), {"name": "agent_kpi"}, "s76b", "ga")["latest"] == 4
    assert _live(cn, "s76b", "empty") == []
    assert len(_live(cn, "Office", "mill-desk.x")) == 2
    assert migrate._ensure_score_one_name(cn) == []  # a second run changes nothing
    names = sorted(s["score"] for s in rpc._h_score(_Book(cn), {}, "s76b", "ga")["scores"])
    assert names == ["agent_kpi", "dup"]


# F37


def test_set_target_without_a_point(cn) -> None:
    seed_names(cn, ("s76c", "roster"), ("tc", "desk"))
    got = rpc._h_score(_Book(cn), {"name": "ms.read", "target": "50", "better": "down", "unit": "ms"}, "s76c", "tc")
    assert got["target"] == "50" and got["better"] == "down" and got["unit"] == "ms" and got["trend"] == "new"
    assert _q(cn, "SELECT COUNT(*) FROM score_point sp JOIN score s ON s.id = sp.score_id"
                  " WHERE s.kpi = 'ms.read'")[0][0] == 0
    rpc._h_score(_Book(cn), {"name": "ms.read", "value": "80"}, "s76c", "tc")
    got = rpc._h_score(_Book(cn), {"name": "ms.read", "target": "40"}, "s76c", "tc")
    assert got["target"] == "40" and got["latest"] == 80 and got["gap"] == -40 and got["unit"] == "ms"
    assert _q(cn, "SELECT COUNT(*) FROM score_point sp JOIN score s ON s.id = sp.score_id"
                  " WHERE s.kpi = 'ms.read'")[0][0] == 1
    with pytest.raises(CoordError, match="--note goes with a VALUE"):
        rpc._h_score(_Book(cn), {"name": "ms.read", "target": "30", "note": "x"}, "s76c", "tc")
    with pytest.raises(CoordError, match="--target must be a number"):
        rpc._h_score(_Book(cn), {"name": "ms.read", "target": "soon"}, "s76c", "tc")


# F39


def test_at_orders_points_and_backfill_is_not_latest(cn) -> None:
    seed_names(cn, ("s76d", "roster"), ("td", "desk"))
    b = _Book(cn)
    rpc._h_score(b, {"name": "k", "value": "10", "better": "down"}, "s76d", "td")
    rpc._h_score(b, {"name": "k", "value": "30", "at": "2d"}, "s76d", "td")
    rpc._h_score(b, {"name": "k", "value": "20", "at": "1d"}, "s76d", "td")
    got = rpc._h_score(b, {"name": "k"}, "s76d", "td")
    assert [p["v"] for p in got["points"]] == [10, 20, 30]
    assert got["latest"] == 10 and got["trend"] == "improving"
    rpc._h_score(b, {"name": "k", "value": "5", "at": "2026-01-02T03:04"}, "s76d", "td")
    got = rpc._h_score(b, {"name": "k"}, "s76d", "td")
    assert [p["v"] for p in got["points"]] == [10, 20, 30, 5] and got["points"][-1]["at"] == "01-02 03:04"
    assert got["latest"] == 10


@pytest.mark.parametrize("at", ["tomorrow", "2099-01-01", "5w", "2026-13-40", "1d; DROP"])
def test_bad_at_stores_nothing(cn, at) -> None:
    seed_names(cn, ("s76e", "roster"), ("te", "desk"))
    before = _q(cn, "SELECT COUNT(*) FROM score_point")[0][0]
    with pytest.raises(Exception, match="--at"):
        rpc._h_score(_Book(cn), {"name": "k", "value": "1", "at": at}, "s76e", "te")
    assert _q(cn, "SELECT COUNT(*) FROM score_point")[0][0] == before


def test_at_needs_a_value(cn) -> None:
    seed_names(cn, ("s76e", "roster"), ("te", "desk"))
    with pytest.raises(CoordError, match="--at needs a VALUE"):
        rpc._h_score(_Book(cn), {"name": "k", "at": "1d"}, "s76e", "te")


# F40


def test_retire_by_recorder_only_and_points_kept(cn) -> None:
    seed_names(cn, ("s76f", "roster"), ("rf", "desk"), ("other", "desk"))
    sid = rpc._h_score(_Book(cn), {"name": "probe", "value": "1"}, "s76f", "rf")["id"]
    with pytest.raises(CoordError, match="only a desk that recorded on probe"):
        rpc._h_score(_Book(cn), {"name": "probe", "retire": True}, "s76f", "other")
    out = rpc._h_score(_Book(cn), {"name": "probe", "retire": True}, "s76f", "rf")
    assert out == {"score": "probe", "id": sid, "retired": True}
    with pytest.raises(CoordError, match="no score probe on s76f"):
        rpc._h_score(_Book(cn), {"name": "probe"}, "s76f", "rf")
    assert rpc._h_score(_Book(cn), {}, "s76f", "rf")["scores"] == []
    assert _q(cn, "SELECT COUNT(*) FROM score_point WHERE score_id = %s", (sid,))[0][0] == 1
    with pytest.raises(CoordError, match="no score probe on s76f; nothing retired"):
        rpc._h_score(_Book(cn), {"name": "probe", "retire": True}, "s76f", "rf")
    # A new point on the name revives the same score.
    again = rpc._h_score(_Book(cn), {"name": "probe", "value": "2"}, "s76f", "rf")
    assert again["id"] == sid and [p["v"] for p in rpc._h_score(_Book(cn), {"name": "probe"}, "s76f", "rf")["points"]] == [2, 1]


def test_retire_by_admin_and_legacy_owner(cn) -> None:
    seed_names(cn, ("s76g", "roster"), ("Admin", "roster"), ("ad", "desk"), ("own", "desk"), ("rec", "desk"))
    from agent_coord.server.records import member as rec_member

    rec_member.put_admin(cn, "ad")
    rpc._h_score(_Book(cn), {"name": "a", "value": "1"}, "s76g", "rec")
    rec_score.upsert(cn, "s76g", "own", "legacy", "7", "", "")
    assert rpc._h_score(_Book(cn), {"name": "legacy", "retire": True}, "s76g", "own")["retired"] is True
    assert rpc._h_score(_Book(cn), {"name": "a", "retire": True}, "s76g", "ad")["retired"] is True


def test_retire_refuses_value_or_at(cn) -> None:
    seed_names(cn, ("s76h", "roster"), ("rh", "desk"))
    with pytest.raises(CoordError, match="retire takes no VALUE"):
        rpc._h_score(_Book(cn), {"name": "k", "value": "1", "retire": True}, "s76h", "rh")
