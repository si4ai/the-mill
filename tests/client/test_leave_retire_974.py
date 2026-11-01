# -*- coding: utf-8 -*-
"""Card 974: desk self-retire on live /ws; remove roster without --yes exits non-zero."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agent_coord.__main__ import _build_parser, main
from agent_coord.client import outbound
from agent_coord.client.language import translate
from agent_coord.server.api.mill import rpc
from agent_coord.server.book import Book


def test_remove_roster_without_yes_exits_nonzero(monkeypatch, capsys) -> None:
    """Cold measure (b): no tty and no --yes must exit 1, not 0."""
    monkeypatch.setattr("agent_coord.client.language._tty", lambda: False)
    rc = main(["remove", "roster", "the-mill"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "add --yes" in err


def test_self_retire_supplies_seat_hash_when_book_has_no_http_token(monkeypatch) -> None:
    """Cold measure (a): live /ws Book has no c._tokens; self-retire still needs by_hash."""
    c = MagicMock(spec=Book)
    c._cn = MagicMock()
    c._tokens = {}
    monkeypatch.setattr(
        "agent_coord.server.records.join.token_hash_for_desk",
        lambda cn, desk: "seat-hash-974",
    )
    monkeypatch.setattr("agent_coord.server.records.hold.find", lambda *a, **k: [])

    with patch(
        "agent_coord.server.records.name.retire", return_value=[{"ok": 1}]
    ) as ret, patch(
        "agent_coord.server.api.mill.rpc._poke_freed_holds", lambda *a, **k: None
    ):
        out = rpc._h_retire(
            c, {"slug": "cold-desk", "name_type": "desk"}, "the-mill", "cold-desk"
        )
    assert out == [{"ok": 1}]
    assert ret.call_args.kwargs["by_hash"] == "seat-hash-974"


def test_self_retire_body_skips_admin_path_when_owner_empty(monkeypatch) -> None:
    """No sitting connect must not force yes=True (that hit require_admin as Admin required)."""
    monkeypatch.setattr("agent_coord.client.tokens.resolve_desk_owner", lambda x="": "")
    p = _build_parser()
    args = translate(p.parse_args("retire desk cold-desk --yes".split()))
    body = outbound.body_from_args(args)
    assert body.get("slug") == "cold-desk"
    assert not body.get("yes")
