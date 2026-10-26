"""#288 step 1 on a real book: mill_score_point_add and mill_score_points.

Two desks on one roster add to one roster-owned series. A refused value stores
nothing. The read is newest first and honours the limit. Old per-desk rows still
read. A soft-deleted score drops out of the list. Regression row F31.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.sql

from agent_coord.server.api.mill import rpc
from agent_coord.server.records import score as rec_score
from tests.server.records.conftest import seed_names
from tests.server.records.test_room_reply import _Book


def _count(cn, sql: str) -> int:
    cur = cn.cursor()
    cur.execute(sql)
    n = int(cur.fetchone()[0])
    cur.close()
    return n


def test_two_desks_one_series_and_read(cn) -> None:
    seed_names(cn, ("sp288", "roster"), ("spa", "desk"), ("spb", "desk"))
    book = _Book(cn)
    out = rpc._h_score(book, {"name": "tokens.loop", "value": "900", "target": "500", "better": "down",
                              "unit": "tokens", "note": "baseline"}, "sp288", "spa")
    assert out["latest"] == 900 and out["trend"] == "new" and out["gap"] == -400
    for i, v in enumerate((880, 700, 650, 640, 630)):
        rpc._h_score(book, {"name": "tokens.loop", "value": str(v)}, "sp288", "spb" if i % 2 else "spa")
    assert _count(cn, "SELECT COUNT(*) FROM score s JOIN name n ON n.id = s.roster_id"
                      " WHERE n.name = 'sp288' AND s.kpi = 'tokens.loop'") == 1
    assert _count(cn, "SELECT COUNT(*) FROM score s JOIN name n ON n.id = s.roster_id"
                      " WHERE n.name = 'sp288' AND s.desk_id IS NULL") == 1  # beta 0.8.0: the roster's row has no desk
    got = rpc._h_score(book, {"name": "tokens.loop", "limit": 4}, "sp288", "spa")
    assert [p["v"] for p in got["points"]] == [630, 640, 650, 700]
    assert got["better"] == "down" and got["unit"] == "tokens" and got["target"] == "500"
    assert got["trend"] == "improving" and got["gap"] == -130
    assert got["points"][0]["desk"] == "spa" and got["points"][1]["desk"] == "spb"


def test_refused_value_stores_nothing(cn) -> None:
    seed_names(cn, ("sp288r", "roster"), ("spr", "desk"))
    before = _count(cn, "SELECT COUNT(*) FROM score_point")
    with pytest.raises(Exception, match="must be a number"):
        rpc._h_score(_Book(cn), {"name": "x", "value": "fast"}, "sp288r", "spr")
    with pytest.raises(Exception, match="up or down"):
        rec_score.point_add(cn, "sp288r", "spr", "x", 1.0, better="side")
    assert _count(cn, "SELECT COUNT(*) FROM score_point") == before
    assert _count(cn, "SELECT COUNT(*) FROM score WHERE kpi = 'x'") == 0


def test_old_desk_row_still_reads_and_list_skips_deleted(cn) -> None:
    seed_names(cn, ("sp288o", "roster"), ("spo", "desk"))
    rec_score.upsert(cn, "sp288o", "spo", "legacy", "17", "20", "old row")
    one = rpc._h_score(_Book(cn), {"name": "legacy"}, "sp288o", "spo")
    assert one["latest"] == 17 and one["gap"] == 3 and one["points"] == [] and one["owner"] == "spo"
    rpc._h_score(_Book(cn), {"name": "fresh", "value": "1"}, "sp288o", "spo")
    names = sorted(s["score"] for s in rpc._h_score(_Book(cn), {}, "sp288o", "spo")["scores"])
    assert names == ["fresh", "legacy"]
    rec_score.delete(cn, int(one["id"]), "spo")
    names = [s["score"] for s in rpc._h_score(_Book(cn), {}, "sp288o", "spo")["scores"]]
    assert names == ["fresh"]


def test_probe_delete_maker_is_the_first_recording_desk(cn) -> None:
    from agent_coord.helpers.errors import CoordError
    from agent_coord.server import probe_delete

    seed_names(cn, ("t-288abcde", "roster"), ("spm", "desk"), ("spn", "desk"))
    sid = int(rpc._h_score(_Book(cn), {"name": "k", "value": "1"}, "t-288abcde", "spm")["id"])
    rpc._h_score(_Book(cn), {"name": "k", "value": "2"}, "t-288abcde", "spn")
    assert probe_delete.check(cn, "score", sid, "spm")["id"] == sid
    with pytest.raises(CoordError, match="not made by this desk"):
        probe_delete.check(cn, "score", sid, "spn")
