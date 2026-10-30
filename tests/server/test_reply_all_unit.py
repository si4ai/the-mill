# -*- coding: utf-8 -*-
"""Throwaway unit: reply default = reply-all (sender U mail_tos), no live SQL."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agent_coord.helpers.errors import CoordError

from agent_coord.server.api.mill import rpc
from agent_coord.server.book import Book


@pytest.fixture(autouse=True)
def _reader(monkeypatch):
    # Read access (#sec S-3) is covered in records/test_sec_mail_participant.py.
    monkeypatch.setattr("agent_coord.server.api.mill.rpc._mail_reader", lambda *a, **k: True)


def _book():
    c = MagicMock(spec=Book)
    c._cn = MagicMock()
    return c


def test_reply_default_reply_all_excludes_self():
    """Parent sender a + mail_tos b,c; reply as b => dest {a,c}."""
    c = _book()
    parent = {
        "id": 10,
        "desk": "a",
        "sender_roster": "builder",
        "body": "root",
    }
    parent_tos = [
        {"desk": "b", "roster": None, "receipt": 0},
        {"desk": "c", "roster": "unit", "receipt": 0},
    ]
    sent = {
        "id": 11,
        "sender": {"deskId": "b", "roster": None},
        "mail_tos": [
            {"deskId": "a", "roster": "builder", "receipt": 0},
            {"deskId": "c", "roster": "unit", "receipt": 0},
        ],
        "body": "child",
    }

    def fake_get(cn, name, kind=""):
        return {"a": 1, "b": 2, "c": 3, "d": 4}.get(str(name))

    with patch("agent_coord.server.records.mail.letter_row", return_value=parent), patch(
        "agent_coord.server.records.mail.to_list", return_value=parent_tos
    ), patch(
        "agent_coord.server.records.tree.on_tree", return_value=True
    ), patch(
        "agent_coord.server.records.name.get", side_effect=fake_get
    ), patch.object(rpc, "_h_send", return_value=dict(sent)) as mock_send:
        rec = rpc._h_reply(
            c,
            {"mail_id": 10, "body": "child", "src": "b"},
            "unit",
            "b",
        )
    assert rec["replied_to"] == 10
    kwargs_body = mock_send.call_args[0][1]
    desks = {t["deskId"] for t in kwargs_body["mail_tos"]}
    assert desks == {"a", "c"}
    by = {t["deskId"]: t for t in kwargs_body["mail_tos"]}
    assert by["a"]["roster"] == "builder"
    assert by["c"]["roster"] == "unit"


def test_reply_to_desk_replaces_the_list():
    c = _book()
    parent = {"id": 10, "desk": "a", "sender_roster": None, "body": "root"}
    with patch("agent_coord.server.records.mail.letter_row", return_value=parent), patch(
        "agent_coord.server.records.mail.to_list", return_value=[]
    ), patch(
        "agent_coord.server.records.tree.on_tree", return_value=True
    ), patch(
        "agent_coord.server.records.name.get", return_value=99
    ), patch.object(rpc, "_h_send", return_value={"id": 12}) as mock_send:
        rpc._h_reply(c, {"mail_id": 10, "body": "x", "src": "b", "mail_tos": ["a", "d"]}, "unit", "b")
    desks = {t["deskId"] for t in mock_send.call_args[0][1]["mail_tos"]}
    assert desks == {"a", "d"}


@pytest.mark.parametrize("key", ["add_to", "remove_to"])
def test_reply_old_add_remove_keys_refused(key):
    """#265 hard break: recipients change with mill add|remove mail:ID WHO."""
    c = _book()
    with patch.object(rpc, "_h_send") as mock_send:
        with pytest.raises(CoordError, match="use mill add\\|remove mail:ID WHO"):
            rpc._h_reply(c, {"mail_id": 10, "body": "x", key: ["zed"]}, "unit", "b")
    mock_send.assert_not_called()


def test_reply_unknown_to_desk_refused_before_writes():
    c = _book()
    parent = {"id": 10, "desk": "a", "sender_roster": None, "body": "root"}
    with patch("agent_coord.server.records.mail.letter_row", return_value=parent), patch(
        "agent_coord.server.records.name.get", return_value=None
    ), patch("agent_coord.server.records.tree.create") as mk:
        with pytest.raises(CoordError, match="not in the name table"):
            rpc._h_reply(c, {"mail_id": 10, "body": "x", "mail_tos": ["x" * 70]}, "unit", "b")
    mk.assert_not_called()


def test_reply_all_skips_retired_desks_and_names_them():
    """#918: reply-all skips desks no longer in the name table; letter still sends."""
    c = _book()
    parent = {"id": 10, "desk": "a", "sender_roster": None, "body": "root"}
    parent_tos = [
        {"desk": "b", "roster": None, "receipt": 0},
        {"desk": "probe66-desk", "roster": None, "receipt": 0},
    ]
    live = {"a": 1, "b": 2}  # probe66-desk retired: missing

    def fake_get(cn, name, kind=""):
        if kind and kind != "desk":
            return None
        return live.get(str(name))

    with patch("agent_coord.server.records.mail.letter_row", return_value=parent), patch(
        "agent_coord.server.records.mail.to_list", return_value=parent_tos
    ), patch(
        "agent_coord.server.records.tree.on_tree", return_value=True
    ), patch(
        "agent_coord.server.records.mail.room_participants", return_value={"a", "b", "probe66-desk"}
    ), patch(
        "agent_coord.server.records.name.get", side_effect=fake_get
    ), patch(
        "agent_coord.server.records.opened.insert", return_value=None
    ), patch.object(rpc, "_h_send", return_value={"id": 11}) as mock_send:
        rec = rpc._h_reply(c, {"mail_id": 10, "body": "child", "src": "b"}, "unit", "b")
    desks = {t["deskId"] for t in mock_send.call_args[0][1]["mail_tos"]}
    assert desks == {"a"}
    assert rec.get("skipped") == ["probe66-desk"]


def test_reply_to_desk_retired_still_refused():
    """#918: an explicit --to-desk that does not exist is still refused whole."""
    c = _book()
    parent = {"id": 10, "desk": "a", "sender_roster": None, "body": "root"}
    with patch("agent_coord.server.records.mail.letter_row", return_value=parent), patch(
        "agent_coord.server.records.name.get", return_value=None
    ), patch.object(rpc, "_h_send") as mock_send:
        with pytest.raises(CoordError, match="not in the name table"):
            rpc._h_reply(
                c,
                {"mail_id": 10, "body": "x", "src": "b", "mail_tos": ["probe66-desk"]},
                "unit",
                "b",
            )
    mock_send.assert_not_called()
