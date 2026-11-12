"""Card text no longer changes through a retired note command (card 1125). Regression row F45."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from agent_coord.server.api.mill import rpc

DETAIL = "Steps:\n1. connect desk old-pilot\n2. read the inbox"


@pytest.fixture
def card(monkeypatch):
    state = {"body": json.dumps({"slug": "c333", "doing": "", "detail": DETAIL}), "writes": 0}

    monkeypatch.setattr(
        "agent_coord.server.records.todo.find",
        lambda cn, p, n: {"id": 333, "body": state["body"], "creator": "asker-desk", "assigned": "w1"},
    )

    def upd(cn, tid, desk, body=None, **kw):
        if body is not None:
            state["body"] = body
            state["writes"] += 1
        return [{"id": tid}]

    monkeypatch.setattr("agent_coord.server.records.todo.update", upd)
    monkeypatch.setattr(rpc, "_poke", lambda *a, **k: None)
    return state


def _detail(state):
    return json.loads(state["body"])["detail"]


def test_progress_still_writes_and_leaves_the_detail(card):
    r = rpc._card_fields(MagicMock(), dict(need="c333", progress="9/12"), "cold-test", "asker-desk")
    assert r["progress"] == "9/12"
    assert _detail(card) == DETAIL
    assert card["writes"] == 1


def test_cli_has_no_supersedes_flag():
    from agent_coord.__main__ import _build_parser

    with pytest.raises(SystemExit):
        _build_parser().parse_args(["todo", "cold-test", "c333", "--supersedes", "old"])
