"""0.7.6 score fixes on a real book (Gardener's live test of 0.7.5).

F36 score-one-name (#305): an upgrade retires or adopts the 0.7.4 per-desk rows
  of a name, and a read never returns an empty legacy row.
F37 score-define (#306): --target/--better/--unit without a VALUE set them, no point.
F39 score-at (#308): --at orders points by time; a backfill never becomes latest.
F40 score-retire (#302): retire score ROSTER NAME, by a recording desk or Admin.

Card 1021: desk _h_score is read-only; writes and retire go through records.*.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.sql


def _seat(cn, *desks: str) -> None:
    """0.8.0: score.desk_id FKs to seat; mint a seat for each desk name."""
    from agent_coord.client.tokens import token_hash
    from agent_coord.server.records import join as rec_join

    for d in desks:
        rec_join.upsert(cn, "Office", d, "", token_hash("seat-" + d), None)
    cn.commit()


from agent_coord.helpers.errors import CoordError
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


def _add(cn, roster, desk, kpi, value, **kw):
    rows = rec_score.point_add(cn, roster, desk, kpi, float(value), **kw)
    cn.commit()
    return rows


def _define(cn, roster, desk, kpi, **kw):
    rows = rec_score.define(cn, roster, desk, kpi, **kw)
    cn.commit()
    return rows


def _retire(cn, roster, desk, kpi, *, admin: bool = False):
    rows = rec_score.retire(cn, roster, desk, kpi, admin=admin)
    cn.commit()
    return rows


# F36


def test_empty_legacy_row_never_reads_before_the_first_point(cn) -> None:
    seed_names(cn, ("s76a", "roster"), ("g76", "desk"))
    _seat(cn, "g76")
    rec_score.upsert(cn, "s76a", "g76", "probe", "", "", "")  # the 0.7.4 shape: empty, desk-owned
    cn.commit()
    with pytest.raises(CoordError, match="no score probe on s76a"):
        rpc._h_score(_Book(cn), {"name": "probe"}, "s76a", "g76")
    _add(cn, "s76a", "g76", "probe", 6)
    got = rpc._h_score(_Book(cn), {"name": "probe"}, "s76a", "g76")
    assert got["latest"] == 6 and got["owner"] == "s76a"


# F37


def test_set_target_without_a_point(cn) -> None:
    seed_names(cn, ("s76c", "roster"), ("tc", "desk"))
    _seat(cn, "tc")
    _define(cn, "s76c", "tc", "ms.read", target="50", better="down", unit="ms")
    got = rpc._h_score(_Book(cn), {"name": "ms.read"}, "s76c", "tc")
    assert got["target"] == "50" and got["better"] == "down" and got["unit"] == "ms" and got["trend"] == "new"
    assert _q(cn, "SELECT COUNT(*) FROM score_point sp JOIN score s ON s.id = sp.score_id"
                  " WHERE s.kpi = 'ms.read'")[0][0] == 0
    _add(cn, "s76c", "tc", "ms.read", 80)
    _define(cn, "s76c", "tc", "ms.read", target="40")
    got = rpc._h_score(_Book(cn), {"name": "ms.read"}, "s76c", "tc")
    assert got["target"] == "40" and got["latest"] == 80 and got["gap"] == -40 and got["unit"] == "ms"
    assert _q(cn, "SELECT COUNT(*) FROM score_point sp JOIN score s ON s.id = sp.score_id"
                  " WHERE s.kpi = 'ms.read'")[0][0] == 1
    with pytest.raises(CoordError, match=r"desks only read scores"):
        rpc._h_score(_Book(cn), {"name": "ms.read", "target": "30", "note": "x"}, "s76c", "tc")
    with pytest.raises(CoordError, match=r"desks only read scores"):
        rpc._h_score(_Book(cn), {"name": "ms.read", "target": "soon"}, "s76c", "tc")


# F39


def test_at_orders_points_and_backfill_is_not_latest(cn) -> None:
    seed_names(cn, ("s76d", "roster"), ("td", "desk"))
    _seat(cn, "td")
    b = _Book(cn)
    _add(cn, "s76d", "td", "k", 10, better="down")
    _add(cn, "s76d", "td", "k", 30, at="2d")
    _add(cn, "s76d", "td", "k", 20, at="1d")
    got = rpc._h_score(b, {"name": "k"}, "s76d", "td")
    assert [p["v"] for p in got["points"]] == [10, 20, 30]
    assert got["latest"] == 10 and got["trend"] == "improving"
    _add(cn, "s76d", "td", "k", 5, at="2026-01-02T03:04")
    got = rpc._h_score(b, {"name": "k"}, "s76d", "td")
    assert [p["v"] for p in got["points"]] == [10, 20, 30, 5] and got["points"][-1]["at"] == "01-02 03:04"
    assert got["latest"] == 10


@pytest.mark.parametrize("at", ["tomorrow", "2099-01-01", "5w", "2026-13-40", "1d; DROP"])
def test_bad_at_stores_nothing(cn, at) -> None:
    seed_names(cn, ("s76e", "roster"), ("te", "desk"))
    _seat(cn, "te")
    before = _q(cn, "SELECT COUNT(*) FROM score_point")[0][0]
    with pytest.raises(Exception):
        rec_score.point_add(cn, "s76e", "te", "k", 1.0, at=at)
    assert _q(cn, "SELECT COUNT(*) FROM score_point")[0][0] == before
    with pytest.raises(CoordError, match=r"desks only read scores"):
        rpc._h_score(_Book(cn), {"name": "k", "value": "1", "at": at}, "s76e", "te")


def test_at_needs_a_value(cn) -> None:
    seed_names(cn, ("s76e", "roster"), ("te", "desk"))
    _seat(cn, "te")
    with pytest.raises(CoordError, match=r"desks only read scores"):
        rpc._h_score(_Book(cn), {"name": "k", "at": "1d"}, "s76e", "te")


# F40


def test_retire_by_recorder_only_and_points_kept(cn) -> None:
    seed_names(cn, ("s76f", "roster"), ("rf", "desk"), ("other", "desk"))
    _seat(cn, "rf", "other")
    sid = int(_add(cn, "s76f", "rf", "probe", 1)[0]["id"])
    with pytest.raises(Exception, match="only a desk that recorded on probe|only a desk"):
        _retire(cn, "s76f", "other", "probe")
    out = _retire(cn, "s76f", "rf", "probe")
    assert (out[0] or {}).get("id") == sid
    with pytest.raises(CoordError, match="no score probe on s76f"):
        rpc._h_score(_Book(cn), {"name": "probe"}, "s76f", "rf")
    assert rpc._h_score(_Book(cn), {}, "s76f", "rf")["scores"] == []
    assert _q(cn, "SELECT COUNT(*) FROM score_point WHERE score_id = %s", (sid,))[0][0] == 1
    with pytest.raises(Exception, match="no such score|no score"):
        _retire(cn, "s76f", "rf", "probe")
    # A new point on the name revives the same score.
    again = _add(cn, "s76f", "rf", "probe", 2)
    assert int(again[0]["id"]) == sid
    assert [p["v"] for p in rpc._h_score(_Book(cn), {"name": "probe"}, "s76f", "rf")["points"]] == [2, 1]
    with pytest.raises(CoordError, match=r"desks only read scores"):
        rpc._h_score(_Book(cn), {"name": "probe", "retire": True}, "s76f", "rf")


def test_retire_by_admin_and_legacy_owner(cn) -> None:
    seed_names(cn, ("s76g", "roster"), ("Admin", "roster"), ("ad", "desk"), ("own", "desk"), ("rec", "desk"))
    _seat(cn, "ad", "own", "rec")
    from agent_coord.server.records import member as rec_member

    rec_member.put_admin(cn, "ad")
    cn.commit()
    _add(cn, "s76g", "rec", "a", 1)
    rec_score.upsert(cn, "s76g", "own", "legacy", "7", "", "")
    cn.commit()
    assert (_retire(cn, "s76g", "own", "legacy")[0] or {}).get("id")
    assert (_retire(cn, "s76g", "ad", "a", admin=True)[0] or {}).get("id")
    with pytest.raises(CoordError, match=r"desks only read scores"):
        rpc._h_score(_Book(cn), {"name": "a", "retire": True}, "s76g", "ad")


def test_retire_refuses_value_or_at(cn) -> None:
    seed_names(cn, ("s76h", "roster"), ("rh", "desk"))
    _seat(cn, "rh")
    with pytest.raises(CoordError, match=r"desks only read scores"):
        rpc._h_score(_Book(cn), {"name": "k", "value": "1", "retire": True}, "s76h", "rh")
