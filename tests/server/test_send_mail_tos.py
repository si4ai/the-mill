"""Throwaway: mill send body + mail_tos[{deskId, roster?}] lean MAIL shape."""
from __future__ import annotations

from unittest.mock import MagicMock, patch


from agent_coord.server.api.mill import rpc
from agent_coord.server.book import Book
from agent_coord.server.records import mail as rec_mail


def _book():
    c = MagicMock(spec=Book)
    c._cn = MagicMock()
    return c


def test_h_send_mail_tos_per_dest_roster():
    """API mail_tos: per-dest role / project / none; lean public response."""
    c = _book()
    body = {
        "src": "alice",
        "project": "the-mill",
        "body": "hello tos",
        "mail_tos": [
            {"deskId": "bob", "roster": "builder"},
            {"deskId": "carol", "roster": "unit"},
            {"deskId": "dave"},
        ],
    }
    dest_rows = [
        {"desk": "bob", "roster": None, "receipt": 0, "opened": None},
        {"desk": "carol", "roster": None, "receipt": 0, "opened": None},
        {"desk": "dave", "roster": None, "receipt": 0, "opened": None},
    ]

    def fake_get(cn, name, kind=""):
        return {"bob": 2, "carol": 3, "dave": 4, "alice": 1}.get(str(name))

    with patch("agent_coord.server.records.name.get", side_effect=fake_get), patch(
        "agent_coord.server.records.name.ensure_roster", return_value=10
    ), patch(
        "agent_coord.server.records.mail.insert", return_value=[{"id": 55, "created": "2026-01-01 00:00:00"}]
    ), patch(
        "agent_coord.server.records.mail.to_put"
    ) as mock_put, patch(
        "agent_coord.server.records.mail.dest_count", return_value=3
    ), patch(
        "agent_coord.server.records.mail.to_list", return_value=dest_rows
    ), patch(
        "agent_coord.server.records.mail.tree_crumbs",
        return_value={},
    ), patch(
        "agent_coord.server.push.fanout", lambda *a, **k: None
    ):
        out = rpc._h_send(c, body, "the-mill", "alice")

    assert out["id"] == 55
    assert out["sender"] == {"deskId": "alice", "roster": "the-mill"}  # SP stamps project
    assert out["body"] == "hello tos"
    assert out.get("room") is not True  # Host lock: multi-To alone = flat mail
    assert "src" not in out and "dst" not in out and "copies" not in out
    assert "roster" not in out
    tos = out["mail_tos"]
    assert tos == [
        {"deskId": "bob", "receipt": 0},
        {"deskId": "carol", "receipt": 0},
        {"deskId": "dave", "receipt": 0},
    ]
    # first dest via insert; remaining via to_put
    assert mock_put.call_count == 2


def test_h_send_dst_plus_default_roster():
    """CLI idiom: --roster = sender tag + dest default when omit."""
    c = _book()
    body = {"src": "alice", "dst": "bob", "body": "role queue", "roster": "builder"}
    sender_aff: list = []
    dest_rows = [
        {"desk": "bob", "roster": None, "receipt": 0, "opened": None},
    ]
    with patch(
        "agent_coord.client.outbound.addressing.parse_mail_to",
        return_value=[{"kind": "desk", "dst": "bob"}],
    ), patch("agent_coord.server.records.name.get", return_value=2), patch(
        "agent_coord.server.records.name.ensure_roster", return_value=10
    ), patch(
        "agent_coord.server.records.mail.insert",
        side_effect=lambda cn, roster, *a, **k: (sender_aff.append(roster), [{"id": 7, "created": "t"}])[1],
    ), patch(
        "agent_coord.server.records.mail.dest_count", return_value=1
    ), patch(
        "agent_coord.server.records.mail.to_list", return_value=dest_rows
    ), patch(
        "agent_coord.server.records.mail.tree_crumbs", return_value={}
    ), patch(
        "agent_coord.server.push.fanout", lambda *a, **k: None
    ):
        out = rpc._h_send(c, body, "the-mill", "alice")

    assert out.get("room") is not True
    assert out["sender"] == {"deskId": "alice", "roster": "builder"}
    assert out["mail_tos"] == [{"deskId": "bob", "receipt": 0}]
    assert sender_aff == ["builder"]


def test_h_send_one_dest_no_room_lean():
    c = _book()
    dest_rows = [{"desk": "bob", "roster": None, "receipt": 0, "opened": None}]
    with patch(
        "agent_coord.client.outbound.addressing.parse_mail_to",
        return_value=[{"kind": "desk", "dst": "bob"}],
    ), patch("agent_coord.server.records.name.get", return_value=2), patch(
        "agent_coord.server.records.name.ensure_roster"
    ), patch(
        "agent_coord.server.records.mail.insert", return_value=[{"id": 3, "created": "t"}]
    ), patch(
        "agent_coord.server.records.mail.dest_count", return_value=1
    ), patch(
        "agent_coord.server.records.mail.to_list", return_value=dest_rows
    ), patch(
        "agent_coord.server.records.mail.tree_crumbs", return_value={}
    ), patch(
        "agent_coord.server.push.fanout", lambda *a, **k: None
    ):
        out = rpc._h_send(
            c, {"src": "alice", "project": "the-mill", "dst": "bob", "body": "plain"}, "the-mill", "alice"
        )
    assert "room" not in out or out.get("room") is not True
    assert set(out.keys()) >= {"id", "created", "sender", "body", "mail_tos"}
    assert out["sender"] == {"deskId": "alice", "roster": "the-mill"}  # SP stamps project
    assert "roster" not in out["mail_tos"][0]


def test_public_mail_tos_shape_stable():
    rows = [
        {"desk": "a", "roster": "builder", "receipt": 1, "opened": "x"},
    ]
    tos = rec_mail.public_mail_tos(rows)
    assert tos == [{"deskId": "a", "receipt": 1}]
