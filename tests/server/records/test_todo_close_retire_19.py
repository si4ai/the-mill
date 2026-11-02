"""Close and retire cards with the commands we have (#19). Row F103.

Board triage found shipped cards whose asker is gone and stale cards with no
way off the board. `mill pass ROSTER NEED --done` stays the close, now for the
asker or Admin, and NEED may be a comma list. `mill retire todo ROSTER NEED`
(asker or Admin) takes a card off every `mill todo` list, `--done` included;
`mill reclaim todo ROSTER NEED` brings it back with its old status. The card
row, its trail and its history are kept.
"""
from __future__ import annotations

import pytest

from agent_coord.helpers.errors import CoordError
from agent_coord.server.admin.guard import ADMIN_ROSTER_ID, is_role_admin
from agent_coord.server.api.mill import rpc
from agent_coord.server.records import todo as rec_todo
from tests.server.records.conftest import seed_names

pytestmark = pytest.mark.sql

R = "r19"
ASKER, VOL, OTHER, ADMIN = "a19", "v19", "o19", "adm19"


class _Book:
    def __init__(self, cn):
        self._cn = cn


def _sql(cn, stmt: str, args=()) -> None:
    cur = cn.cursor()
    try:
        cur.execute(stmt, args)
        cn.commit()
    finally:
        cur.close()


@pytest.fixture(scope="module")
def book(cn):
    seed_names(cn, (R, "roster"), (ASKER, "desk"), (VOL, "desk"), (OTHER, "desk"), (ADMIN, "desk"))
    _sql(cn, "INSERT IGNORE INTO member (name_id, desk_id)"
             " SELECT %s, id FROM name WHERE type = 'desk' AND name = %s", (ADMIN_ROSTER_ID, ADMIN))
    assert is_role_admin(cn, ADMIN) is True
    assert is_role_admin(cn, OTHER) is False
    return _Book(cn)


def _card(book, need, status="open"):
    rpc._h_open(book, {"need": need}, R, ASKER)
    if status in ("claimed", "shipped", "done"):
        rpc._h_claim(book, {"need": need}, R, VOL)
    if status in ("shipped", "done"):
        rpc._h_pass(book, {"need": need}, R, VOL)
    if status == "done":
        rpc._h_pass(book, {"need": need, "step": "done"}, R, ASKER)
    return rec_todo.find(book._cn, R, need)


def _listed(book, need, *, done=False):
    rows = rpc._h_todo(book, {"done": done} if done else {}, R, ASKER)
    if isinstance(rows, dict):
        rows = rows.get("rows") or rows.get("result") or []
    return any(str(r.get("need_id")) == need for r in rows)


def _status(book, need):
    return rec_todo.find(book._cn, R, need)["status"]


def test_admin_closes_a_shipped_card_someone_else_asked_for(book):
    _card(book, "c19-admin", "shipped")
    out = rpc._h_pass(book, {"need": "c19-admin", "step": "done"}, R, ADMIN)
    assert out["status"] == "done"


def test_a_non_asker_non_admin_close_is_refused_and_names_the_asker(book):
    _card(book, "c19-other", "shipped")
    with pytest.raises(CoordError) as e:
        rpc._h_pass(book, {"need": "c19-other", "step": "done"}, R, OTHER)
    msg = str(e.value)
    assert msg.startswith("who-may: pass shipped->done is the asker")
    assert ASKER in msg and "Admin" in msg
    assert _status(book, "c19-other") == "shipped"


def test_close_takes_a_comma_list_and_one_bad_card_does_not_stop_the_rest(book):
    _card(book, "c19-l1", "shipped")
    _card(book, "c19-l2", "shipped")
    out = rpc._h_pass(book, {"need": "c19-l1,c19-nope,c19-l2", "step": "done"}, R, ASKER)
    rows = out["results"]
    assert [r["need"] for r in rows] == ["c19-l1", "c19-nope", "c19-l2"]
    assert [r["ok"] for r in rows] == [True, False, True]
    assert "no such need" in rows[1]["error"]
    assert out["refused"] == 1
    assert _status(book, "c19-l1") == "done" and _status(book, "c19-l2") == "done"


def test_the_asker_retires_and_reclaims_a_card(book):
    hit = _card(book, "c19-stale", "shipped")
    assert _listed(book, "c19-stale")
    out = rpc._h_retire(book, {"name_type": "todo", "need": "c19-stale"}, R, ASKER)
    assert out["ok"] is True and out["op"] == "retired"
    assert not _listed(book, "c19-stale")
    assert not _listed(book, "c19-stale", done=True)
    assert rec_todo.find(book._cn, R, "c19-stale") is None
    # Trail and history are kept: the card row is still in the book.
    assert rec_todo.get(book._cn, int(hit["id"]))
    back = rpc._h_reclaim(book, {"name_type": "todo", "need": "c19-stale"}, R, ASKER)
    assert back["ok"] is True and back["op"] == "reclaimed"
    assert back["status"] == "shipped"
    assert _listed(book, "c19-stale")
    assert _status(book, "c19-stale") == "shipped"


def test_a_retired_done_card_leaves_todo_done_too(book):
    _card(book, "c19-done", "done")
    assert _listed(book, "c19-done", done=True)
    rpc._h_retire(book, {"name_type": "todo", "need": "c19-done"}, R, ADMIN)
    assert not _listed(book, "c19-done", done=True)
    rpc._h_reclaim(book, {"name_type": "todo", "need": "c19-done"}, R, ADMIN)
    assert _status(book, "c19-done") == "done"


def test_another_desk_cannot_retire_or_reclaim(book):
    _card(book, "c19-keep")
    with pytest.raises(CoordError) as e:
        rpc._h_retire(book, {"name_type": "todo", "need": "c19-keep"}, R, OTHER)
    assert str(e.value) == f"who-may: retire todo is the asker ({ASKER}) or Admin"
    assert _listed(book, "c19-keep")
    rpc._h_retire(book, {"name_type": "todo", "need": "c19-keep"}, R, ASKER)
    with pytest.raises(CoordError) as e:
        rpc._h_reclaim(book, {"name_type": "todo", "need": "c19-keep"}, R, OTHER)
    assert str(e.value) == f"who-may: reclaim todo is the asker ({ASKER}) or Admin"
    assert not _listed(book, "c19-keep")


def test_retire_takes_a_comma_list_and_one_bad_card_does_not_stop_the_rest(book):
    _card(book, "c19-r1")
    _card(book, "c19-r2")
    out = rpc._h_retire(book, {"name_type": "todo", "need": "c19-r1,c19-gone,c19-r2"}, R, ASKER)
    assert [r["ok"] for r in out["results"]] == [True, False, True]
    assert out["refused"] == 1
    assert not _listed(book, "c19-r1") and not _listed(book, "c19-r2")
    out = rpc._h_reclaim(book, {"name_type": "todo", "need": "c19-r1,c19-gone,c19-r2"}, R, ASKER)
    assert [r["ok"] for r in out["results"]] == [True, False, True]
    assert _listed(book, "c19-r1") and _listed(book, "c19-r2")


def test_a_retired_card_takes_no_other_command(book):
    _card(book, "c19-quiet")
    rpc._h_retire(book, {"name_type": "todo", "need": "c19-quiet"}, R, ASKER)
    with pytest.raises(CoordError, match="no such need"):
        rpc._h_claim(book, {"need": "c19-quiet"}, R, VOL)
    with pytest.raises(CoordError, match="no such need"):
        rpc._h_retire(book, {"name_type": "todo", "need": "c19-quiet"}, R, ASKER)
    # reclaim of a live card must say "is not retired" (self-contained; do not
    # borrow c19-admin from another test in this module).
    _card(book, "c19-live")
    with pytest.raises(CoordError, match="is not retired"):
        rpc._h_reclaim(book, {"name_type": "todo", "need": "c19-live"}, R, ASKER)
