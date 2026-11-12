"""A card's notes share one budget; the refusal says what is left and where long text goes (#360).

Regression row F56 (note-detail-budget).
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from agent_coord.helpers.errors import CoordError
from agent_coord.server.api.mill import rpc
from agent_coord.server.records import todo as rec_todo
from agent_coord.server.records.todo import BODY_MAX


@pytest.fixture(autouse=True)
def _project_already_exists(monkeypatch):
    monkeypatch.setattr("agent_coord.server.records.name.get", lambda *a, **k: 1)


def _card(monkeypatch, detail: str) -> dict:
    stored = {"body": json.dumps({"slug": "budget", "doing": "", "detail": detail}), "n": 0}

    def fake_find(cn, project, need):
        return {"id": 9, "body": stored["body"], "asker": "builder", "volunteer": "builder"}

    def fake_update(cn, tid, desk, body=None, **k):
        stored["n"] += 1
        stored["body"] = body
        return [{"id": tid}]

    monkeypatch.setattr("agent_coord.server.records.todo.find", fake_find)
    monkeypatch.setattr("agent_coord.server.records.todo.update", fake_update)
    monkeypatch.setattr(rpc, "_poke", lambda *a, **k: None)
    return stored


def _note(text: str, **kw):
    return rpc._h_note(MagicMock(), dict({"need": "budget", "note": text}, **kw), "the-mill", "builder")


def test_a_text_note_is_refused_and_names_replace_body(monkeypatch):
    stored = _card(monkeypatch, "first line")
    before = stored["body"]
    with pytest.raises(CoordError, match="mill replace-body"):
        _note("second line")
    assert stored["body"] == before and stored["n"] == 0


def test_progress_reply_names_the_room_left(monkeypatch):
    stored = _card(monkeypatch, "first line")
    rec = rpc._h_note(MagicMock(), {"need": "budget", "text": "9/12"}, "the-mill", "builder")
    assert rec["detail_left"] == rec_todo.budget_left(json.loads(stored["body"]))


def test_a_note_that_changes_nothing_still_names_the_room_left(monkeypatch):
    stored = _card(monkeypatch, "kept")
    rec = rpc._h_note(MagicMock(), {"need": "budget", "eta": "", "started": False, "text": "9/12"},
                      "the-mill", "builder")
    assert rec["detail_left"] <= BODY_MAX - len(json.dumps({"slug": "budget", "doing": "", "detail": "kept"}))
    assert stored["n"] in (0, 1)


def test_over_the_budget_text_is_refused_before_the_column(monkeypatch):
    base = "d" * 3900
    stored = _card(monkeypatch, base)
    before = stored["body"]
    with pytest.raises(CoordError, match="mill replace-body"):
        _note("n" * 50)
    assert stored["body"] == before and stored["n"] == 0


def test_exactly_at_the_budget_is_kept(monkeypatch):
    stored = _card(monkeypatch, "")
    before = stored["body"]
    with pytest.raises(CoordError, match="mill replace-body"):
        _note("z" * 8)
    assert stored["body"] == before and stored["n"] == 0


def test_escaped_characters_count_as_stored(monkeypatch):
    stored = _card(monkeypatch, "")
    left = BODY_MAX - len(stored["body"])
    with pytest.raises(CoordError, match="mill replace-body"):
        _note("\u00e9" * (left // 6 + 1))  # a text note is refused before the column budget
    assert stored["n"] == 0


def test_over_budget_helper_is_empty_when_it_fits():
    small = {"slug": "s", "doing": "", "detail": "a"}
    assert rec_todo.over_budget(small, dict(small, detail="ab")) == ""
