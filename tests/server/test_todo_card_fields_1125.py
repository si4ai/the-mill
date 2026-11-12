"""Card 1125: mill todo ROSTER NEED --eta / --started / --progress / --done-when sets the card's own fields."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from agent_coord.client.outbound import body_from_args
from agent_coord.helpers.errors import CoordError
from agent_coord.server.api.mill import rpc
from agent_coord.server.records import todo as rec_todo


def _args(**kw):
    base = dict(cmd="todo", project="the-mill", need="c1125", eta="", started=False, progress="", done_when=None)
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture
def no_owner(monkeypatch):
    monkeypatch.setattr("agent_coord.client.tokens.resolve_desk_owner", lambda _x: "builder")


def test_client_sends_eta_and_started(no_owner):
    b = body_from_args(_args(eta="2h", started=True))
    assert b["verb"] == "todo"
    assert b["eta"] == "2h"
    assert b["started"] is True
    assert "done_when" not in b


def test_client_plain_peek_sends_no_card_fields(no_owner):
    b = body_from_args(_args())
    assert not ({"eta", "started", "progress", "done_when"} & set(b))


def test_client_sends_progress(no_owner):
    b = body_from_args(_args(progress=" 9/12 "))
    assert b["progress"] == "9/12"
    assert not ({"eta", "started", "done_when"} & set(b))


def test_client_done_when_goes_alone_with_progress(no_owner):
    with pytest.raises(CoordError, match="--done-when goes alone"):
        body_from_args(_args(progress="9/12", done_when="tests pass"))


def test_client_doing_rides_progress(no_owner):
    b = body_from_args(_args(progress="75%", doing="sweeping docs"))
    assert b["progress"] == "75%"


def test_client_card_fields_need_roster_and_need(no_owner):
    with pytest.raises(CoordError, match="need ROSTER NEED"):
        body_from_args(_args(need="", eta="2h"))


def test_client_card_fields_refuse_list_flags(no_owner):
    with pytest.raises(CoordError, match="drop the list flags"):
        body_from_args(_args(eta="2h", mine=True))


def test_client_doing_needs_a_card_field(no_owner):
    with pytest.raises(CoordError, match="--doing goes with"):
        body_from_args(_args(doing="reading"))


@pytest.mark.parametrize(
    "s,ok",
    [("9/12", True), ("75%", True), ("done", True), ("git abc1234", True),
     ("shipped the fix", False), ("", False), ("1" * 70, False)],
)
def test_progress_token(s, ok):
    assert rec_todo.is_progress_token(s) is ok


class _Store:
    def __init__(self, payload):
        self.body = json.dumps(payload)
        self.updates = 0
        self.pokes = 0


@pytest.fixture
def store(monkeypatch):
    st = _Store({"slug": "n1125", "detail": "seed"})
    monkeypatch.setattr(rec_todo, "find", lambda cn, p, n: {"id": 1125, "body": st.body})

    def upd(cn, tid, desk, body=""):
        st.body = body
        st.updates += 1
        return [{"id": tid}]

    monkeypatch.setattr(rec_todo, "update", upd)
    monkeypatch.setattr(rpc, "_poke", lambda *a, **k: setattr(st, "pokes", st.pokes + 1))
    return st


def _todo(body):
    return rpc._h_todo(MagicMock(), dict(body, need="n1125"), "the-mill", "builder")


def test_eta_and_started_stamped(store):
    r = _todo({"eta": "2h", "started": True})
    body = json.loads(store.body)
    assert body["eta_at"] and body["started_at"]
    assert r["eta_at"] == body["eta_at"]
    assert body["detail"] == "seed"
    assert store.pokes == 1


def test_only_card_fields_reach_the_card(store):
    _todo({"eta": "2h", "text": "50%", "note": "diary", "detail": "x"})
    body = json.loads(store.body)
    assert body["detail"] == "seed" and "progress" not in body


def test_bad_eta_refused(store):
    with pytest.raises(CoordError, match="todo:"):
        _todo({"eta": "soonish"})
    assert store.updates == 0


def test_card_fields_need_a_need(store):
    with pytest.raises(CoordError, match="need ROSTER NEED"):
        rpc._h_todo(MagicMock(), {"eta": "2h"}, "the-mill", "builder")


def test_server_doing_on_a_board_read_is_refused():
    with pytest.raises(CoordError, match="--doing goes with"):
        rpc._doing_text("todo", {"doing": "reading the board"})


def test_same_eta_twice_no_second_poke(store, monkeypatch):
    from datetime import datetime

    monkeypatch.setattr(rec_todo, "parse_eta", lambda raw, now=None: datetime(2026, 1, 1, 12, 0, 0))
    _todo({"eta": "2h"})
    assert (store.updates, store.pokes) == (1, 1)
    r = _todo({"eta": "2h"})
    assert r["changed"] is False
    assert (store.updates, store.pokes) == (1, 1)


def test_progress_token_stored(store):
    r = _todo({"progress": "9/12"})
    body = json.loads(store.body)
    assert body["progress"] == rec_todo.format_progress("9/12")
    assert body["detail"] == "seed"
    assert r["changed"] is True
    assert (store.updates, store.pokes) == (1, 1)


def test_progress_routes_without_eta(store):
    # A progress-only call is a card write, not a board read; --doing may ride it.
    assert rpc._doing_text("todo", {"doing": "sweeping", "progress": "done"}) == "sweeping"
    _todo({"progress": "done"})
    assert json.loads(store.body)["progress"]


@pytest.mark.parametrize("text", ["waiting on legal", "1" * 70])
def test_progress_non_token_refused_nothing_changed(store, text):
    seed = store.body
    with pytest.raises(CoordError, match="mill replace-body todo ID TEXT"):
        _todo({"progress": text})
    assert (store.updates, store.pokes) == (0, 0)
    assert store.body == seed


def test_progress_with_done_when_refused(store):
    seed = store.body
    with pytest.raises(CoordError, match="--done-when goes alone"):
        _todo({"progress": "9/12", "done_when": "tests pass"})
    assert (store.updates, store.pokes) == (0, 0)
    assert store.body == seed


def test_nothing_to_write_names_progress(store):
    with pytest.raises(CoordError, match="--progress"):
        rpc._h_note(MagicMock(), {"need": "n1125"}, "the-mill", "builder")
