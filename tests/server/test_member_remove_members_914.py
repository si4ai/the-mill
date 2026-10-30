# -*- coding: utf-8 -*-
"""#914: mill remove roster reply names the member count (not bare n)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from agent_coord.server.api.mill import rpc


def test_member_remove_reply_names_members_not_bare_n():
    book = SimpleNamespace(_cn=object())
    with patch("agent_coord.server.records.member.delete", return_value=[{"desk": "builder", "op": "removed", "n": 31}]), patch(
        "agent_coord.server.admin.guard.is_admin_roster", return_value=False
    ), patch(
        "agent_coord.server.admin.guard.require_admin_if_limited", return_value=None
    ):
        rows = rpc._h_member(
            book,
            {"verb": "member-remove", "group": "the-mill", "desk": "builder"},
            "the-mill",
            "builder",
        )
    assert isinstance(rows, list) and len(rows) == 1
    row = rows[0]
    assert row.get("op") == "removed"
    assert row.get("members") == 31
    assert "n" not in row
    assert row.get("desk") == "builder"
    assert row.get("roster") == "the-mill"
