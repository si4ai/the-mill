"""#102: mill note sends text/@file/--note/--eta/--started; host writes progress.

#254: --n/--of/--pct are gone; the positional token (9/12, 75%) is progress.
"""
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
    base = dict(
        cmd="note", project="the-mill", need="cold-ab-note-pct-noop", text="",
        note="", eta="", started=False,
    )
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture
def no_owner(monkeypatch):
    monkeypatch.setattr("agent_coord.client.tokens.resolve_desk_owner", lambda _x: "builder")


def test_client_sends_text_eta_started(no_owner):
    b = body_from_args(_args(text="9/12", eta="2h", started=True))
    assert b["verb"] == "note"
    assert b["text"] == "9/12"
    assert not ({"pct", "n", "of"} & set(b))
    assert b["eta"] == "2h"
    assert b["started"] is True


def test_client_reads_at_file(no_owner, tmp_path):
    f = tmp_path / "note.txt"
    f.write_text("diary from a file\nline two\n", encoding="utf-8")
    b = body_from_args(_args(text=f"@{f}"))
    assert b["text"] == "diary from a file\nline two"
    b2 = body_from_args(_args(note=f"@{f}"))
    assert b2["note"].startswith("diary from a file")


def test_client_missing_at_file_errors(no_owner, tmp_path):
    with pytest.raises(CoordError):
        body_from_args(_args(text=f"@{tmp_path / 'nope.txt'}"))


def test_client_plain_note_unchanged(no_owner):
    b = body_from_args(_args(note="just a note"))
    assert b["note"] == "just a note"
    for k in ("text", "pct", "n", "of", "eta", "started"):
        assert k not in b


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
    st = _Store({"slug": "n102", "detail": "seed"})
    monkeypatch.setattr(rec_todo, "find", lambda cn, p, n: {"id": 102, "body": st.body})

    def upd(cn, tid, desk, body=""):
        st.body = body
        st.updates += 1
        return [{"id": tid}]

    monkeypatch.setattr(rec_todo, "update", upd)
    monkeypatch.setattr(rpc, "_poke", lambda *a, **k: setattr(st, "pokes", st.pokes + 1))
    return st


def _note(body):
    return rpc._h_note(MagicMock(), dict(body, need="n102"), "the-mill", "builder")


def test_pct_writes_progress(store):
    r = _note({"text": "50%"})
    assert r["progress"] == "50%"
    assert r["changed"] is True
    assert json.loads(store.body)["progress"] == "50%"
    assert json.loads(store.body)["detail"] == "seed"
    assert store.pokes == 1


def test_n_of_writes_progress(store):
    assert _note({"text": "9/12"})["progress"] == "9/12"


def test_254_server_ignores_removed_n_of_pct(store):
    with pytest.raises(CoordError, match="nothing to write"):
        _note({"pct": 50, "n": 9, "of": 12})
    assert store.updates == 0 and store.pokes == 0


def test_text_progress_token_is_progress_not_diary(store):
    r = _note({"text": "3/4"})
    assert r["progress"] == "3/4"
    assert r["detail"] == "seed"


def test_text_from_file_appends_diary(store):
    r = _note({"text": "long diary line from @file"})
    assert r["detail"] == "seed\nlong diary line from @file"
    assert "progress" not in r  # #330: never-set progress is left out
    assert store.updates == 1


def test_note_and_text_both_land(store):
    r = _note({"note": "flag note", "text": "90%"})
    assert r["detail"] == "seed\nflag note"
    assert r["progress"] == "90%"


def test_eta_and_started_stamped(store):
    r = _note({"eta": "2h", "started": True})
    body = json.loads(store.body)
    assert body["eta_at"] and body["started_at"]
    assert r["eta_at"] == body["eta_at"]


def test_bad_eta_refused(store):
    with pytest.raises(CoordError):
        _note({"eta": "soonish"})
    assert store.updates == 0


def test_empty_note_refused_not_ok(store):
    with pytest.raises(CoordError):
        _note({})
    assert store.updates == 0 and store.pokes == 0


def test_same_progress_twice_no_write_no_poke(store):
    _note({"text": "50%"})
    assert (store.updates, store.pokes) == (1, 1)
    r = _note({"text": "50%"})
    assert r["changed"] is False
    assert r["progress"] == "50%"
    assert (store.updates, store.pokes) == (1, 1)
