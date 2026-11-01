# -*- coding: utf-8 -*-
"""Card 975: mill rooms --digest client shaping and live /ws flag pass-through."""
from __future__ import annotations

from unittest.mock import MagicMock

from agent_coord.client import rooms_rows
from agent_coord.server.api.mill import rpc


def test_digest_client_short_keys():
    rows = [
        {
            "tree": "a",
            "root_id": 1,
            "size": 3,
            "breadth": 2,
            "created": "2026-01-01 00:00:00",
            "last_at": "2026-01-02 00:00:00",
            "starter": "desk-a",
            "root": "hello",
            "tags": [],
            "depth": 9,
            "members": ["desk-a"],
        }
    ]
    shaped = rooms_rows.digest_short(rows)
    assert shaped == [
        {
            "tree": "a",
            "root_id": 1,
            "size": 3,
            "breadth": 2,
            "created": "2026-01-01 00:00:00",
            "last_at": "2026-01-02 00:00:00",
            "starter": "desk-a",
            "root": "hello",
            "tags": [],
        }
    ]


def test_rooms_rows_applies_skips_digest():
    class A:
        cmd = "rooms"
        full = False
        raw = False
        digest = True

    assert rooms_rows.applies(A()) is False


def test_dispatch_ws_rooms_digest_without_require_live_ws_patch(monkeypatch) -> None:
    """Digest rides the same live /ws path as plain rooms (card 979)."""
    seen: list[object] = []

    def fake_list(cn, **kwargs):  # noqa: ANN001
        seen.append(kwargs)
        return []

    monkeypatch.setattr(
        "agent_coord.server.records.tree.list_mail_rooms", fake_list
    )
    book = MagicMock()
    book._cn = object()
    out = rpc.dispatch_ws(
        book, "desk-a", "rooms", {"project": "the-mill", "digest": True}
    )
    assert isinstance(out, dict)
    assert out.get("digest") is True
    assert seen and seen[0].get("digest") is True


def test_list_mail_rooms_digest_shapes_without_members_walk(monkeypatch):
    """Unit: digest builds tags=[] and never calls the members helper."""
    from agent_coord.server.records import tree as rec_tree

    class _Cur:
        column_names = (
            "tree",
            "root_id",
            "size",
            "depth",
            "breadth",
            "last_at",
            "created",
            "starter",
            "root_line",
        )

        def execute(self, sql, params=None):  # noqa: ANN001
            self.sql = sql

        def fetchall(self):
            return [
                (
                    "demo-room",
                    41,
                    3,
                    1,
                    2,
                    "2026-01-02 00:00:00",
                    "2026-01-01 00:00:00",
                    "desk-a",
                    "first line of opener",
                )
            ]

        def close(self):
            return None

    class _Cn:
        def cursor(self):
            return _Cur()

    calls = {"n": 0}

    def boom(cn, root_id):  # noqa: ANN001
        calls["n"] += 1
        return ["desk-a"]

    monkeypatch.setattr(rec_tree, "_room_member_names_by_root", boom)
    rows = rec_tree.list_mail_rooms(_Cn(), digest=True)
    assert calls["n"] == 0
    assert rows == [
        {
            "tree": "demo-room",
            "root_id": 41,
            "size": 3,
            "breadth": 2,
            "last_at": "2026-01-02 00:00:00",
            "created": "2026-01-01 00:00:00",
            "starter": "desk-a",
            "root": "first line of opener",
            "tags": [],
        }
    ]


def test_list_mail_rooms_digest_cuts_long_first_line(monkeypatch):
    from agent_coord.server.records import tree as rec_tree

    long_line = "y" * (rec_tree.ROOM_ROOT_LINE_CAP + 25)

    class _Cur:
        column_names = (
            "tree",
            "root_id",
            "size",
            "depth",
            "breadth",
            "last_at",
            "created",
            "starter",
            "root_line",
        )

        def execute(self, sql, params=None):  # noqa: ANN001
            return None

        def fetchall(self):
            return [
                (
                    "cut-room",
                    7,
                    1,
                    0,
                    1,
                    "2026-01-01 00:00:00",
                    "2026-01-01 00:00:00",
                    "desk-b",
                    long_line,
                )
            ]

        def close(self):
            return None

    class _Cn:
        def cursor(self):
            return _Cur()

    monkeypatch.setattr(
        rec_tree, "_room_member_names_by_root", lambda cn, root_id: ["desk-b"]
    )
    rows = rec_tree.list_mail_rooms(_Cn(), digest=True)
    assert len(rows[0]["root"]) == rec_tree.ROOM_ROOT_LINE_CAP
    assert rows[0]["root"] == "y" * rec_tree.ROOM_ROOT_LINE_CAP
    assert rows[0]["tags"] == []
