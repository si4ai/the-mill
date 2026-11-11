"""#627 the desk webhook POST body names its target and why: roster next to
desk, and wake.room (room name or null) and wake.reason (addressed or room),
from the routing the wall already does. A coalesced burst says addressed when
any waiting item is addressed. The body stays data-only: never the letter
text, the URL or the key. Row F73 (wake-route)."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from agent_coord.server import mail_push, push, wake
from agent_coord.server.api.mill import rpc
from agent_coord.server.book import Book
from tests.server.test_desk_webhook_618 import _hint, _Queue, _Resp
from tests.server.webhook_fixtures import HOOK_KEY, arm


@pytest.fixture
def posts(monkeypatch):
    arm(monkeypatch)
    q = _Queue()
    q.install(monkeypatch)
    monkeypatch.setattr(push.HUB, "rooms", {})
    monkeypatch.setattr(push, "_bc_log", lambda msg: None)
    monkeypatch.setattr(wake, "desk_roster", lambda cn, desk: "crew")
    got: list[dict] = []

    def fake(req, timeout=0):
        got.append(json.loads(req.data.decode("utf-8")))
        return _Resp()

    with patch("agent_coord.server.wake._open", fake):
        yield got, q


def test_the_body_names_roster_next_to_desk_and_why():
    body = wake.wake_body("away", {"kind": "mail", "id": 7, "idem": "mail:7:away"}, pending=1,
                          roster="crew", reason="room", room="build-room")
    keys = list(body)
    assert keys.index("roster") == keys.index("desk") + 1
    assert body["roster"] == "crew" and body["desk"] == "away"
    assert body["wake"]["reason"] == "room" and body["wake"]["room"] == "build-room"


def test_the_join_test_body_has_no_reason():
    body = wake.wake_body("away", {}, pending=0, test=True, roster="crew")
    assert body["roster"] == "crew"
    assert body["wake"]["reason"] is None and body["wake"]["room"] is None


def test_a_hint_wakes_as_addressed_with_no_room(posts):
    got, _ = posts
    _hint(MagicMock(), 6270)
    assert got[0]["desk"] == "away" and got[0]["roster"] == "crew"
    assert got[0]["wake"]["reason"] == "addressed" and got[0]["wake"]["room"] is None


def _letter(tos, room_only=(), tree="build-room"):
    letter = {"id": 6271, "desk": "boss", "sender_roster": "crew", "body": "secret letter text"}
    dests = [{"desk": d, "opened": None, "receipt": 0} for d in tos]
    with patch("agent_coord.server.records.mail.letter_row", return_value=letter), patch(
        "agent_coord.server.records.mail.to_list", return_value=dests
    ), patch("agent_coord.server.records.mail.tree_crumbs", return_value={"tree": tree} if tree else {}):
        mail_push.push_mail(MagicMock(), 6271, room_only=set(room_only))


def test_a_room_letter_says_room_for_members_and_addressed_for_the_named(posts):
    got, _ = posts
    _letter(["away"], room_only={"away"})
    # Card 1098 item 5: a room copy stays queued (no owed, no POST).
    assert got == []
    wake._GATE.clear()
    _letter(["away"], room_only=())
    assert got[-1]["wake"]["reason"] == "addressed" and got[-1]["wake"]["room"] == "build-room"
    for body in got:
        text = json.dumps(body)
        assert "secret letter text" not in text and HOOK_KEY not in text and "/automations/" not in text


def test_an_off_room_letter_has_room_null(posts):
    got, _ = posts
    _letter(["away"], tree="")
    assert got[-1]["wake"]["room"] is None and got[-1]["wake"]["reason"] == "addressed"


def test_a_minted_thread_tree_is_not_a_room_name(posts):
    got, _ = posts
    # Addressed letter still wakes; a minted thread tree is not a room name (#627).
    # Room copies no longer POST (card 1098 item 5), so this uses an addressed dest.
    _letter(["away"], tree="0a1b2c3d4e")
    assert got[-1]["wake"]["room"] is None and got[-1]["wake"]["reason"] == "addressed"


def test_a_burst_says_addressed_when_any_waiting_item_is_addressed(posts):
    got, q = posts
    _hint(MagicMock(), 6272)  # addressed, POSTs
    wake._GATE.clear()  # window over, the desk has not connected
    _letter(["away"], room_only={"away"})
    assert got[-1]["wake"]["reason"] == "addressed"


def test_a_burst_of_room_items_only_says_room(posts):
    got, q = posts
    _letter(["away"], room_only={"away"})
    wake._GATE.clear()
    _letter(["away"], room_only={"away"})
    # Card 1098 item 5: room copies stay queued; a room-only burst posts nothing.
    assert got == []


def _book():
    c = MagicMock(spec=Book)
    c._cn = MagicMock()
    return c


def test_reply_all_marks_room_members_and_keeps_the_parent_sender_addressed(monkeypatch):
    monkeypatch.setattr(rpc, "_mail_reader", lambda *a, **k: True)
    parent = {"id": 10, "desk": "a", "sender_roster": None, "body": "root"}
    tos = [{"desk": "b", "roster": None}, {"desk": "c", "roster": None}]
    with patch("agent_coord.server.records.mail.letter_row", return_value=parent), patch(
        "agent_coord.server.records.mail.to_list", return_value=tos
    ), patch("agent_coord.server.records.tree.on_tree", return_value=True), patch(
        "agent_coord.server.records.mail.room_participants", return_value={"a", "b", "c", "d"}
    ), patch("agent_coord.server.records.name.get", return_value=1), patch.object(
        rpc, "_h_send", return_value={"id": 11}
    ) as send:
        rpc._h_reply(_book(), {"mail_id": 10, "body": "x", "src": "b"}, "crew", "b")
    assert send.call_args.kwargs["room_only"] == {"c", "d"}


def test_reply_with_to_desk_is_addressed(monkeypatch):
    monkeypatch.setattr(rpc, "_mail_reader", lambda *a, **k: True)
    parent = {"id": 10, "desk": "a", "sender_roster": None, "body": "root"}
    with patch("agent_coord.server.records.mail.letter_row", return_value=parent), patch(
        "agent_coord.server.records.mail.to_list", return_value=[]
    ), patch("agent_coord.server.records.tree.on_tree", return_value=True), patch(
        "agent_coord.server.records.name.get", return_value=1
    ), patch.object(rpc, "_h_send", return_value={"id": 11}) as send:
        rpc._h_reply(_book(), {"mail_id": 10, "body": "x", "src": "b", "mail_tos": ["c", "d"]}, "crew", "b")
    assert send.call_args.kwargs["room_only"] == set()


def test_take_strips_the_wake_reason(monkeypatch):
    from agent_coord.server.records import push as rec_push

    row = {"kind": "mail", "outcome": "missed", "created": None,
           "payload": json.dumps({"kind": "mail", "id": 1, "wake_reason": "room"})}
    monkeypatch.setattr(rec_push, "call", lambda cn, proc, args: [row])
    items = rec_push.take(MagicMock(), "away")
    assert items[0]["id"] == 1 and "wake_reason" not in items[0]
