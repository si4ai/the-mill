# -*- coding: utf-8 -*-
"""Card 1130: --desk is the seat borrow on every desk command, connected filters by --who,
refusals say why and what to run, and todo --mine takes the borrowed desk."""
from __future__ import annotations

import pytest

from agent_coord.__main__ import _build_parser
from agent_coord.client import session_errors
from agent_coord.client import todo_rows
from agent_coord.client.language import translate
from agent_coord.client.outbound import body_from_args
from agent_coord.client.seat import command
from agent_coord.helpers.errors import CoordError


def test_connected_desk_is_the_seat_borrow(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))
    args = _build_parser().parse_args(["connected", "--desk", "builder"])
    assert args.sender_desk == "builder"
    body = body_from_args(translate(args))
    assert body["sender_desk"] == "builder"
    assert body.get("desk") in (None, "")


def test_connected_who_filters_one_desk(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))
    args = _build_parser().parse_args(["connected", "--who", "grok-tui", "--desk", "builder"])
    body = body_from_args(translate(args))
    assert body["desk"] == "grok-tui"
    assert body["sender_desk"] == "builder"


def test_refusal_says_why_and_the_next_command(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))
    monkeypatch.setattr(session_errors, "_typed", ["mail-thread", "5337"])
    with pytest.raises(CoordError) as ei:
        command({"verb": "mail-thread"})
    text = str(ei.value)
    assert "no sitting mill connect" in text
    assert "mill mail-thread 5337 --desk DESK" in text
    assert "mill connect DESK" in text


def test_refusal_names_the_typed_word_not_the_rpc(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))
    monkeypatch.setattr(session_errors, "_typed", ["connected", "--who", "grok-tui"])
    with pytest.raises(CoordError) as ei:
        command({"verb": "session"})
    text = str(ei.value)
    assert "mill connected --who grok-tui --desk DESK" in text
    assert "mill session" not in text


def test_refusal_keeps_the_office_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))
    monkeypatch.setattr(session_errors, "_typed", ["--office", "cloud", "inbox"])
    with pytest.raises(CoordError) as ei:
        command({"verb": "inbox"})
    assert "mill --office cloud inbox --desk DESK" in str(ei.value)


def test_run_parsed_remembers_the_typed_command(tmp_path, monkeypatch):
    from agent_coord import __main__ as cli

    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))
    monkeypatch.setattr(session_errors, "_typed", [])
    seen: dict = {}

    def fake_from_args(args):
        seen["typed"] = list(session_errors._typed)
        return 0

    monkeypatch.setattr("agent_coord.client.http.mill_http_from_args", fake_from_args)
    monkeypatch.setattr("agent_coord.client.http.mill_url", lambda: "https://wall.example")
    cli.main(["inbox", "--page", "2"])
    assert seen["typed"] == ["inbox", "--page", "2"]


def test_mine_uses_the_borrowed_desk(monkeypatch):
    monkeypatch.setattr("agent_coord.client.tokens.resolve_desk_owner", lambda *_a, **_k: "")
    assert todo_rows.sitting_desk({"verb": "todo", "sender_desk": "gardener"}) == "gardener"


def test_mine_without_sit_or_desk_names_both_ways(monkeypatch):
    monkeypatch.setattr("agent_coord.client.tokens.resolve_desk_owner", lambda *_a, **_k: "")
    with pytest.raises(CoordError) as ei:
        todo_rows.sitting_desk({"verb": "todo"})
    text = str(ei.value)
    assert "todo --mine --desk DESK" in text
