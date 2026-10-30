"""mail-thread marks only through _mark_shown, for a desk with a name row (#195, card 843 F129)."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agent_coord.server.api.mill import rpc


def _patch(monkeypatch, inserted: list[int]) -> None:
    monkeypatch.setattr(
        "agent_coord.server.records.mail.get",
        lambda cn, mid: [{"id": int(mid)}],
    )
    class _Room:
        def __init__(self, cn, mid):
            self.mail_id = int(mid)
            self.nodes = [{"id": int(mid), "lft": 1, "rgt": 2}]
            self.tree_id = None

    monkeypatch.setattr("agent_coord.server.records.mail.RoomRead", _Room)
    monkeypatch.setattr(
        "agent_coord.server.records.mail.room_participant",
        lambda cn, mid, desk, room=None: desk == "grok-tui",
    )
    monkeypatch.setattr(
        "agent_coord.server.admin.guard.is_role_admin",
        lambda cn, owner: False,
    )
    monkeypatch.setattr(
        "agent_coord.server.records.name.get",
        lambda cn, name, kind="": None,
    )
    monkeypatch.setattr(
        "agent_coord.server.records.mail.public_mail_chain",
        lambda cn, mid, ids=None, room=None: {"chain": [{"id": int(mid), "body": "hi"}]},
    )

    def _insert(cn, mid, desk):
        inserted.append(int(mid))
        return [{"id": int(mid)}]

    monkeypatch.setattr("agent_coord.server.records.opened.insert", _insert)


def test_mail_thread_marks_returned_letters(monkeypatch):
    inserted: list[int] = []
    _patch(monkeypatch, inserted)
    out = rpc._h_mail_thread(MagicMock(), {"mail_id": 5}, "the-mill", "grok-tui")
    assert out["chain"][0]["id"] == 5
    assert inserted == []


def test_leftover_no_mark_key_does_not_open(monkeypatch):
    inserted: list[int] = []
    _patch(monkeypatch, inserted)
    rpc._h_mail_thread(
        MagicMock(),
        {"mail_id": 5, "no_mark": True},
        "the-mill",
        "grok-tui",
    )
    assert inserted == []


def test_scope_all_is_refused():
    from agent_coord.helpers.errors import CoordError

    with pytest.raises(CoordError, match="not a flag"):
        rpc._mail_thread_scope({"scope": "all"}, False, 0)


def test_mark_state_is_refused_before_lookup():
    from agent_coord.helpers.errors import CoordError

    with pytest.raises(CoordError, match="--state is not a flag"):
        rpc._h_mark(MagicMock(), {"ids": [1], "state": "handled"}, "the-mill", "desk")
