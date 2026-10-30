"""The roster named at connect is the seat's default sender roster (#337).

Regression row F48 (connect-roster-stamp). Since #241 a desk on several
non-Office rosters stamped Office unless --roster was passed, even after
mill connect ROSTER DESK. The connect bridge now sends that roster as
connect_roster on send and reply; the server checks the desk is on it.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agent_coord.helpers.errors import CoordError
from agent_coord.server.api.mill import rpc
from agent_coord.server.book import Book

TWO = [{"slot": "the-mill", "slot_type": "roster"}, {"slot": "grok-tui", "slot_type": "roster"}]
ONE = [{"slot": "grok-tui", "slot_type": "roster"}]


def _book():
    c = MagicMock(spec=Book)
    c._cn = MagicMock()
    return c


def _send(body, seats=TWO):
    dest_rows = [{"desk": "bob", "receipt": 0, "opened": None}]
    with patch(
        "agent_coord.client.outbound.addressing.parse_mail_to",
        return_value=[{"kind": "desk", "dst": "bob"}],
    ), patch("agent_coord.server.records.name.get", return_value=2), patch(
        "agent_coord.server.records.name.ensure_roster"
    ), patch(
        "agent_coord.server.records.mail.insert", return_value=[{"id": 3, "created": "t"}]
    ) as ins, patch(
        "agent_coord.server.records.mail.dest_count", return_value=1
    ), patch(
        "agent_coord.server.records.mail.to_list", return_value=dest_rows
    ), patch(
        "agent_coord.server.records.mail.tree_crumbs", return_value={}
    ), patch(
        "agent_coord.server.push.fanout", lambda *a, **k: None
    ), patch(
        "agent_coord.server.mail_push.push_mail", lambda *a, **k: None
    ), patch(
        "agent_coord.server.records.member.select", return_value=seats
    ):
        try:
            out = rpc._h_send(_book(), dict({"src": "alice", "dst": "bob", "body": "plain"}, **body), "the-mill", "alice")
        except CoordError as e:
            return e, ins, None
    return out, ins, None


def test_connect_roster_is_the_sender_roster():
    out, ins, setaff = _send({"connect_roster": "the-mill"})
    assert out["sender"] == {"deskId": "alice", "roster": "the-mill"}
    assert ins.call_args.args[1] == "the-mill"  # the letter's roster is the connect roster


def test_the_other_roster_on_the_seat_works_too():
    out, _ins, _setaff = _send({"connect_roster": "grok-tui"})
    assert out["sender"]["roster"] == "grok-tui"


def test_explicit_roster_wins_over_connect_roster():
    out, ins, _ = _send({"connect_roster": "the-mill", "roster": "grok-tui"})
    assert out["sender"]["roster"] == "grok-tui"
    assert ins.call_args.args[1] == "grok-tui"  # #867: the insert carries the sender roster


def test_connect_roster_the_desk_is_not_on_is_refused_and_nothing_sent():
    err, ins, _setaff = _send({"connect_roster": "cold-test"})
    assert isinstance(err, CoordError)
    msg = str(err)
    assert "cold-test" in msg and "alice" in msg and "--roster" in msg
    ins.assert_not_called()


def test_office_named_at_connect_stamps_office():
    out, _ins, _setaff = _send({"connect_roster": "Office"}, seats=ONE)
    assert out["sender"]["roster"] == "Office"


@pytest.mark.parametrize("cr", [None, "", "  "])
def test_no_connect_roster_keeps_the_seat_rule(cr):
    body = {} if cr is None else {"connect_roster": cr}
    out, _ins, _setaff = _send(body)
    assert out["sender"]["roster"] == "Office"  # two non-Office rosters: the #241 seat rule
    out, _ins, _setaff = _send(body, seats=ONE)
    assert out["sender"]["roster"] == "grok-tui"


def test_explicit_project_is_not_overridden():
    out, ins, _setaff = _send({"connect_roster": "grok-tui", "project": "the-mill"})
    assert ins.call_args.args[1] == "the-mill"


@pytest.mark.parametrize("roster", [None, "grok-tui"])
def test_reply_hands_connect_roster_to_send(monkeypatch, roster):
    seen = {}

    def fake_send(c, b, project, owner, **kw):
        seen.update(b)
        return {"ok": True}

    monkeypatch.setattr(rpc, "_h_send", fake_send)
    monkeypatch.setattr(rpc, "_mail_reader", lambda *a: True)
    monkeypatch.setattr(rpc, "_check_roster", lambda *a: None)
    monkeypatch.setattr(
        "agent_coord.server.records.mail.letter_row",
        lambda cn, mid: {"id": mid, "desk": "bob", "sender_roster": "the-mill"},
    )
    monkeypatch.setattr("agent_coord.server.records.mail.to_list", lambda cn, mid: [])
    monkeypatch.setattr("agent_coord.server.records.tree.on_tree", lambda *a: True)
    monkeypatch.setattr("agent_coord.server.records.mail.room_participants", lambda *a: set())
    monkeypatch.setattr("agent_coord.server.records.opened.insert", lambda *a: None)
    body = {"mail_id": 9, "body": "hi", "connect_roster": "the-mill"}
    if roster:
        body["roster"] = roster
    rpc._h_reply(_book(), body, "the-mill", "alice")
    assert seen["connect_roster"] == "the-mill"
    assert seen.get("roster") == roster
