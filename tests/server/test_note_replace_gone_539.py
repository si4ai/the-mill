"""The CLI has no note command and no --replace / --supersedes flag (card 1125, 1177). Regression row F62.

Card text is mill replace-body. mill note fails like any unknown command.
"""
from __future__ import annotations

import pytest

from agent_coord.helpers import bounds
from agent_coord.server.api.mill import rpc
from agent_coord.client.outbound import COMMANDS


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


def test_note_command_is_gone():
    """mill note is an unknown command: not in COMMANDS and not a server handler."""
    assert "note" not in COMMANDS
    assert "note" not in rpc.HANDLERS
    from agent_coord.__main__ import _build_parser

    with pytest.raises(SystemExit):
        _build_parser().parse_args(["note", "cold-test", "c539", "--note", "later"])
