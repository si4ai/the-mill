"""F22: todo filters done, status and id in SQL; several rosters in one read."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.sql

from agent_coord.helpers.errors import CoordError
from agent_coord.server import table_ver
from agent_coord.server.api.mill import rpc
from agent_coord.server.records import todo as rec_todo
from tests.server.records.conftest import seed_names


class _Book:
    def __init__(self, cn):
        self._cn = cn


@pytest.fixture(scope="module")
def board(cn):
    seed_names(cn, ("tq_a", "roster"), ("tq_b", "roster"), ("tq_empty", "roster"), ("t-0a1b2c3d", "roster"), ("tq_d", "desk"))
    ids = {}
    for roster in ("tq_a", "tq_b", "t-0a1b2c3d"):
        for i, st in enumerate(("open", "claimed", "done", "shipped", "done")):
            row = rec_todo.insert(cn, roster, "tq_d", "open", rec_todo.pack({"slug": f"{roster}-c{i}", "detail": f"card {i}"}))
            tid = int(row[0]["id"])
            if st != "open":
                rec_todo.update(cn, tid, "tq_d", status=st)
            ids[(roster, i)] = tid
    return ids


def _cards(cn, body, project):
    try:
        return rpc._h_todo(_Book(cn), dict(body), project, "tq_d")
    except CoordError as e:
        return {"error": str(e)}


def _legacy_page(cn, project, status, hide_done, card_id):
    rows = rec_todo.select(cn, project, status)
    return [
        r for r in rows
        if not (hide_done and r.get("status") == "done") and not (card_id and int(r["id"]) != card_id)
    ]


@pytest.mark.parametrize("status", ["", "open", "claimed", "done"])
@pytest.mark.parametrize("hide_done", [False, True])
@pytest.mark.parametrize("project", ["tq_a", "", "tq_empty", "nope"])
def test_page_equals_select_then_filter(cn, board, status, hide_done, project):
    for card_id in (0, board[("tq_a", 2)], 99999999):
        got = rec_todo.page(cn, project, status, hide_done=hide_done, card_id=card_id)
        assert got == _legacy_page(cn, project, status, hide_done, card_id)


@pytest.mark.parametrize(
    "body",
    [{}, {"done": True}, {"status": "claimed"}, {"status": "done"}, {"fixtures": True}, {"fixtures": True, "done": True}],
)
def test_many_rosters_equal_one_call_per_roster(cn, board, body):
    rosters = ["tq_b", "t-0a1b2c3d", "tq_a", "tq_empty", "nope"]
    per = []
    for r in rosters:
        got = _cards(cn, body, r)
        if isinstance(got, list):
            per.extend(got)
    many = rpc._h_todo(_Book(cn), {**body, "rosters": rosters}, rosters[0], "tq_d")
    assert many == {"cards": per, "rosters": len(rosters)}


def test_numeric_peek_shows_a_done_card_and_misses_keep_their_hint(cn, board):
    done = board[("tq_a", 2)]
    got = _cards(cn, {"need": str(done)}, "tq_a")
    assert [c["id"] for c in got] == [done] and got[0]["status"] == "done"
    other = board[("tq_b", 0)]
    assert _cards(cn, {"need": str(other)}, "tq_a") == {"error": f"todo: no card {other} in tq_a. find it: mill todo --all --find {other}"}
    fx = board[("t-0a1b2c3d", 0)]
    assert _cards(cn, {"need": str(fx)}, "t-0a1b2c3d") == {"error": f"todo: no card {fx} in t-0a1b2c3d; pass --fixtures. find it: mill todo --all --find {fx}"}
    assert _cards(cn, {"need": str(done), "status": "open"}, "tq_a") == {"error": f"todo: no card {done} in tq_a; pass --done. find it: mill todo --all --find {done}"}


def test_board_hides_done_and_unknown_project_refuses(cn, board):
    ids = [c["id"] for c in _cards(cn, {}, "tq_a")]
    assert board[("tq_a", 2)] not in ids and board[("tq_a", 0)] in ids
    assert _cards(cn, {}, "tq_empty") == []
    assert _cards(cn, {}, "nope") == {"error": "todo: unknown roster nope. list them: mill member"}


def test_too_many_rosters_refused(cn, board):
    with pytest.raises(CoordError, match="at most"):
        rpc._h_todo(_Book(cn), {"rosters": [f"r{i}" for i in range(201)]}, "tq_a", "tq_d")


def test_page_is_a_read_for_the_pane_cache():
    assert table_ver.tables_for_proc("mill_todo_page") == ()


def test_card_zero_is_not_the_whole_board(cn, board):
    assert _cards(cn, {"need": "0"}, "tq_a") == {"error": "todo: no card 0 in tq_a. find it: mill todo --all --find 0"}
    assert _cards(cn, {"need": "000"}, "tq_a") == {"error": "todo: no card 0 in tq_a. find it: mill todo --all --find 0"}
    lead = board[("tq_a", 0)]
    assert [c["id"] for c in _cards(cn, {"need": "00%d" % lead}, "tq_a")] == [lead]
