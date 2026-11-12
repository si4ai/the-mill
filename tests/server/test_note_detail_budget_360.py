"""A card-field write names the room left; over-budget refusals point at replace-body (#360).

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


def test_progress_reply_names_the_room_left(monkeypatch):
    stored = _card(monkeypatch, "first line")
    rec = rpc._card_fields(MagicMock(), {"need": "budget", "progress": "9/12"}, "the-mill", "builder")
    assert rec["detail_left"] == rec_todo.budget_left(json.loads(stored["body"]))


def test_a_progress_write_that_already_has_the_token_still_names_the_room_left(monkeypatch):
    stored = _card(monkeypatch, "kept")
    rec = rpc._card_fields(MagicMock(), {"need": "budget", "eta": "", "started": False, "progress": "9/12"},
                      "the-mill", "builder")
    assert rec["detail_left"] <= BODY_MAX - len(json.dumps({"slug": "budget", "doing": "", "detail": "kept"}))
    assert stored["n"] in (0, 1)


def test_over_budget_helper_is_empty_when_it_fits():
    small = {"slug": "s", "doing": "", "detail": "a"}
    assert rec_todo.over_budget(small, dict(small, detail="ab")) == ""


def test_over_budget_note_names_replace_body_and_claim_names_msg():
    """D9: each path's refusal is pinned, so flipping command == 'note' fails."""
    before = {"slug": "s", "doing": "", "detail": "a"}
    after = {"slug": "s", "doing": "", "detail": "a" * BODY_MAX}
    note_msg = rec_todo.over_budget(before, after, "note")
    claim_msg = rec_todo.over_budget(before, after, "claim")
    assert rec_todo.over_budget(before, after) == note_msg
    assert "mill replace-body todo ID TEXT" in note_msg
    assert "--msg" in claim_msg
    assert "replace-body" not in claim_msg
    assert note_msg and claim_msg
