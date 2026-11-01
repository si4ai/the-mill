# -*- coding: utf-8 -*-
"""Card 979: mill rooms works on dispatch_ws without patching _require_live_ws."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agent_coord.client.session_errors import SESSION_WS_RPC_ONLY
from agent_coord.helpers.errors import CoordError
from agent_coord.server.api.mill import rpc


def test_dispatch_ws_rooms_without_require_live_ws_patch(monkeypatch) -> None:
    """Live /ws path must serve rooms; the HTTP cut must not sit inside _h_rooms.

    intentionally does not monkeypatch _require_live_ws. list_mail_rooms is
    stubbed so this stays off MySQL; the bug is raised before that call.
    """
    seen: list[object] = []

    def fake_list(cn, **kwargs):  # noqa: ANN001
        seen.append(kwargs)
        return []

    monkeypatch.setattr(
        "agent_coord.server.records.tree.list_mail_rooms", fake_list
    )
    book = MagicMock()
    book._cn = object()
    try:
        out = rpc.dispatch_ws(book, "desk-a", "rooms", {"project": "the-mill"})
    except CoordError as e:
        assert str(e) != SESSION_WS_RPC_ONLY, (
            "_h_rooms must not call _require_live_ws; HTTP cut is at dispatch only"
        )
        raise
    assert isinstance(out, dict)
    assert out.get("rooms") == []
    assert seen, "list_mail_rooms should run on the /ws path"
