"""A note does not replace or append card text (card 1125). Regression row F62.

The CLI has no --replace flag and no --supersedes flag. Card text is
mill replace-body. A raw replace=true or a note line writes nothing.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from agent_coord.helpers import bounds
from agent_coord.helpers.errors import CoordError
from agent_coord.server.api.mill import rpc

DETAIL = "Steps:\n1. first"


@pytest.fixture
def card(monkeypatch):
    state = {"body": json.dumps({"slug": "c539", "doing": "", "detail": DETAIL}), "writes": 0}
    monkeypatch.setattr(
        "agent_coord.server.records.todo.find",
        lambda cn, p, n: {"id": 539, "body": state["body"], "creator": "asker-desk", "assigned": "w1"},
    )

    def upd(cn, tid, desk, body=None, **kw):
        if body is not None:
            state["body"] = body
            state["writes"] += 1
        return [{"id": tid}]

    monkeypatch.setattr("agent_coord.server.records.todo.update", upd)
    monkeypatch.setattr(rpc, "_poke", lambda *a, **k: None)
    return state


def _note(body):
    return rpc._h_note(MagicMock(), dict(need="c539", **body), "cold-test", "asker-desk")


@pytest.mark.parametrize("extra", [{}, {"supersedes": "1. first"}, {"replace": False}])
def test_replace_is_refused_and_nothing_is_written(card, extra):
    with pytest.raises(CoordError, match="mill replace-body"):
        _note({"note": "only-this", "replace": True, **extra})
    assert card["writes"] == 0
    assert json.loads(card["body"])["detail"] == DETAIL


def test_a_note_line_is_refused(card):
    with pytest.raises(CoordError, match="mill replace-body"):
        _note({"note": "later", "replace": False})
    assert card["writes"] == 0
    assert json.loads(card["body"])["detail"] == DETAIL


def test_cli_never_sends_replace(monkeypatch):
    from agent_coord.__main__ import _build_parser
    from agent_coord.client import outbound

    monkeypatch.setattr("agent_coord.client.tokens.resolve_desk_owner", lambda _x="": "asker-desk")
    a = _build_parser().parse_args(["todo", "cold-test", "c539", "--eta", "2h"])
    a.replace = True  # no such flag; a stray attribute must not reach the wall
    assert "replace" not in outbound.body_from_args(a)
    with pytest.raises(SystemExit):
        _build_parser().parse_args(["todo", "cold-test", "c539", "--eta", "2h", "--replace"])


def test_dead_note_helpers_are_gone():
    assert not hasattr(bounds, "append_note_detail")
    assert not hasattr(bounds, "NOTE_MAX")
