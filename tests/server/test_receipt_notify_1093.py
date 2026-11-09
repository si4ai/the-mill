# -*- coding: utf-8 -*-
"""Card 1093 / #1098 item 4: --receipt on send/reply; unquietable until opened.

(a) send --receipt to 2 desks -> both mail_to.receipt=1
(b) reply-all --receipt room copy -> emit reason=addressed (wake_on=addressed posts)
(c) same reply without --receipt -> reason=room; stays queued (item 5: no POST)
(d) first open of a receipt letter -> one receipt item to the sender
(e) body_from_args receipt=True -> body["receipt"] is True; human_required still dropped
(f) unopened receipt room copy counts as waiting work (item 5 empty-skip hook)
(g) after mark: no more wakes/owed for it; exactly one receipt to the sender
(h) Wall chip clears once every receipt recipient has opened
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agent_coord.client.outbound import body_from_args
from agent_coord.server import mail_push, push, wake
from agent_coord.server.api.mill import rpc
from agent_coord.web.wall_logic.mail import mail_msg_human_required_open, mail_tos
from tests.server.test_desk_webhook_618 import _Queue, _Resp
from tests.server.webhook_fixtures import arm


def _body_file(text: str = "please confirm"):
    import tempfile

    fd, path = tempfile.mkstemp(suffix=".txt")
    with open(fd, "w", encoding="utf-8") as f:
        f.write(text)
    return path


# --- (e) body_from_args (no MySQL) ---


def test_e_body_from_args_receipt_true():
    args = SimpleNamespace(
        cmd="send",
        project="the-mill",
        src="builder",
        to_desk=["validator"],
        body_file=_body_file(),
        owner="builder",
        receipt=True,
        human_required=True,
    )
    body = body_from_args(args)
    assert body.get("receipt") is True
    assert "human_required" not in body


def test_e_body_from_args_receipt_default_absent():
    args = SimpleNamespace(
        cmd="send",
        project="the-mill",
        src="builder",
        to_desk=["validator"],
        body_file=_body_file(),
        owner="builder",
    )
    body = body_from_args(args)
    assert body.get("receipt") is not True


# --- (a) send --receipt stores receipt=1 on every dest (mocked insert) ---


def test_a_send_receipt_sets_every_dest(monkeypatch):
    inserted: dict = {}
    puts: list[dict] = []

    def fake_insert(cn, project, desk, dst, body, receipt=0, dst_kind="desk"):
        inserted["receipt"] = receipt
        inserted["dst"] = dst
        return [{"id": 1093, "created": "t"}]

    def fake_to_put(cn, mid, project, to, receipt=0, dst_kind="desk"):
        puts.append({"to": to, "receipt": receipt})

    class FakeBook:
        _cn = MagicMock()

    monkeypatch.setattr("agent_coord.server.records.mail.insert", fake_insert)
    monkeypatch.setattr("agent_coord.server.records.mail.to_put", fake_to_put)
    monkeypatch.setattr("agent_coord.server.records.name.get", lambda cn, name, kind="": 1)
    monkeypatch.setattr("agent_coord.server.records.name.ensure_roster", lambda *a, **k: 1)
    monkeypatch.setattr(
        "agent_coord.client.outbound.addressing.parse_mail_to",
        lambda dst, project_id="": [
            {"dst": "alice", "kind": "desk"},
            {"dst": "bob", "kind": "desk"},
        ],
    )
    monkeypatch.setattr("agent_coord.server.records.mail.dest_count", lambda *a, **k: 2)
    monkeypatch.setattr(
        "agent_coord.server.records.mail.to_list",
        lambda *a, **k: [
            {"desk": "alice", "roster": None, "receipt": 1, "opened": None},
            {"desk": "bob", "roster": None, "receipt": 1, "opened": None},
        ],
    )
    monkeypatch.setattr("agent_coord.server.records.mail.tree_crumbs", lambda *a, **k: {})
    monkeypatch.setattr("agent_coord.server.mail_push.push_mail", lambda *a, **k: None)

    out = rpc._h_send(
        FakeBook(),
        {"src": "builder", "dst": "alice,bob", "body": "need ack", "receipt": True},
        "the-mill",
        "builder",
    )
    assert inserted["receipt"] == 1
    assert puts and all(p["receipt"] == 1 for p in puts)
    assert all(t["receipt"] == 1 for t in out["mail_tos"])
    note = str(out.get("note") or "")
    assert "receipt:" in note
    assert "woken" in note or "receipt when" in note


# --- (b)/(c) push_mail reason + wake_on=addressed ---


@pytest.fixture
def desk_wake(monkeypatch):
    arm(monkeypatch)
    q = _Queue()
    q.install(monkeypatch)
    state = {"wake_on": "addressed"}
    monkeypatch.setattr(
        "agent_coord.server.records.join.wake_state",
        lambda cn, d: {"armed": True, "host": "h", "wake_on": state["wake_on"]},
    )
    monkeypatch.setattr(push.HUB, "rooms", {})
    lines: list[str] = []
    monkeypatch.setattr(push, "_bc_log", lines.append)
    posts: list[dict] = []

    def fake(req, timeout=0):
        posts.append(json.loads(req.data.decode("utf-8")))
        return _Resp()

    with patch("agent_coord.server.wake._open", fake):
        yield SimpleNamespace(q=q, state=state, lines=lines, posts=posts)


def _push_room_letter(*, receipt: int, room_only: set[str]):
    letter = {"id": 10930, "desk": "boss", "sender_roster": "crew", "body": "text"}
    dests = [{"desk": "away", "receipt": receipt, "opened": None}]
    with patch("agent_coord.server.records.mail.letter_row", return_value=letter), patch(
        "agent_coord.server.records.mail.to_list", return_value=dests
    ), patch(
        "agent_coord.server.records.mail.tree_crumbs", return_value={"tree": "build-room"}
    ):
        mail_push.push_mail(MagicMock(), 10930, room_only=set(room_only))



def test_b_reply_forwards_receipt_into_send(monkeypatch):
    """reply --receipt reaches _h_send as body receipt=True."""
    captured: dict = {}

    def fake_send(c, b, project, owner, *, room_only=None):
        captured["body"] = dict(b)
        captured["room_only"] = set(room_only or ())
        return {"id": 99, "mail_tos": []}

    class FakeBook:
        _cn = MagicMock()

    monkeypatch.setattr(rpc, "_h_send", fake_send)
    parent = {"id": 42, "desk": "boss", "sender_roster": "crew", "body": "parent"}
    monkeypatch.setattr(
        "agent_coord.server.records.mail.letter_row",
        lambda cn, mid: parent,
    )
    monkeypatch.setattr(
        "agent_coord.server.records.mail.get",
        lambda cn, mid: [parent],
    )
    monkeypatch.setattr(
        "agent_coord.server.records.mail.to_list",
        lambda cn, mid: [
            {"desk": "boss", "roster": None, "receipt": 0},
            {"desk": "away", "roster": None, "receipt": 0},
        ],
    )
    monkeypatch.setattr("agent_coord.server.records.name.get", lambda cn, name, kind="": 1)
    monkeypatch.setattr("agent_coord.server.records.tree.on_tree", lambda *a, **k: True)
    monkeypatch.setattr(
        "agent_coord.server.records.mail.room_participants",
        lambda cn, mid: {"boss", "away", "extra"},
    )
    monkeypatch.setattr("agent_coord.server.records.opened.insert", lambda *a, **k: [])

    # owner=away replies; named = parent from + explicit? reply-all default.
    rpc._h_reply(
        FakeBook(),
        {"mail_id": 42, "body": "ack", "receipt": True, "project": "unit"},
        "unit",
        "away",
    )
    assert captured["body"].get("receipt") is True
    # room_only should include desks not named (extra is room-only).
    assert "extra" in captured["room_only"]


def test_b_receipt_room_copy_wakes_addressed_desk(desk_wake):
    """(b) receipt=1 room copy -> reason=addressed; wake_on=addressed posts."""
    _push_room_letter(receipt=1, room_only={"away"})
    assert len(desk_wake.posts) == 1
    assert desk_wake.posts[0]["wake"]["reason"] == "addressed"
    # Stored wake has no wake_reason=room (addressed path leaves it off).
    assert desk_wake.q.rows
    assert desk_wake.q.rows[0].get("wake_reason") != "room"
    assert not any("reason=room-only" in ln for ln in desk_wake.lines)


def test_c_room_copy_without_receipt_stays_quiet(desk_wake):
    """(c) receipt=0 room copy -> reason=room; item 5: queued, no POST/owed."""
    _push_room_letter(receipt=0, room_only={"away"})
    assert desk_wake.posts == []
    assert [ln for ln in desk_wake.lines if ln.startswith("webhook ")] == []
    assert desk_wake.q.rows and desk_wake.q.rows[0].get("outcome") == "queued"
    assert desk_wake.q.rows[0].get("wake_reason") == "room"


# --- (f) empty-wake hook: unopened receipt is waiting work ---


def test_f_unopened_receipt_counts_as_waiting_work():
    """(f) item 5 empty-skip must not treat an unopened receipt as empty."""
    assert mail_push.counts_as_waiting(pending=0, unread=False, unopened_receipt=True) is True
    assert mail_push.counts_as_waiting(pending=0, unread=False, unopened_receipt=False) is False
    assert mail_push.counts_as_waiting(pending=1, unread=False, unopened_receipt=False) is True
    assert mail_push.counts_as_waiting(pending=0, unread=True, unopened_receipt=False) is True


def test_f_wake_reason_receipt_overrides_room():
    assert mail_push.wake_reason_for_dest({"desk": "away", "receipt": 1}, {"away"}) == "addressed"
    assert mail_push.wake_reason_for_dest({"desk": "away", "receipt": 0}, {"away"}) == "room"
    assert mail_push.wake_reason_for_dest({"desk": "named", "receipt": 0}, {"away"}) == "addressed"


# --- (h) Wall chip clears once opened ---


def test_h_wall_chip_clears_once_opened():
    hot = {
        "id": 1,
        "sender": {"deskId": "a", "roster": None},
        "mail_tos": [{"deskId": "b", "roster": None, "receipt": 1}],
    }
    assert mail_msg_human_required_open(hot) is True
    cleared = {
        "id": 1,
        "sender": {"deskId": "a", "roster": None},
        "mail_tos": [{"deskId": "b", "roster": None, "receipt": 1, "opened": "2026-11-09T12:00:00"}],
    }
    # mail_tos adapter must pass opened through so the chip can clear.
    assert mail_tos(cleared)[0].get("opened")
    assert mail_msg_human_required_open(cleared) is False
    # Mixed: still open while any receipt dest is unopened.
    mixed = {
        "id": 2,
        "sender": {"deskId": "a", "roster": None},
        "mail_tos": [
            {"deskId": "b", "roster": None, "receipt": 1, "opened": "2026-11-09T12:00:00"},
            {"deskId": "c", "roster": None, "receipt": 1, "opened": None},
        ],
    }
    assert mail_msg_human_required_open(mixed) is True
    both = {
        "id": 3,
        "sender": {"deskId": "a", "roster": None},
        "mail_tos": [
            {"deskId": "b", "roster": None, "receipt": 1, "opened": "t1"},
            {"deskId": "c", "roster": None, "receipt": 1, "opened": "t2"},
        ],
    }
    assert mail_msg_human_required_open(both) is False


# --- SQL: (a) store, (d) receipt to sender, (f) has_unopened_receipt, (g) after mark ---


@pytest.mark.sql
def test_a_sql_send_receipt_two_desks(cn):
    from tests.server.records.conftest import seed_names

    seed_names(cn, ("unit", "roster"), ("alice", "desk"), ("bob", "desk"), ("carol", "desk"))

    class Book:
        _cn = cn

    out = rpc._h_send(
        Book(),
        {"src": "alice", "dst": "bob,carol", "body": "receipt please", "receipt": True, "project": "unit"},
        "unit",
        "alice",
    )
    mid = int(out["id"])
    from agent_coord.server.records import mail as rec_mail

    rows = rec_mail.to_list(cn, mid)
    assert {r["desk"]: int(r.get("receipt") or 0) for r in rows} == {"bob": 1, "carol": 1}


@pytest.mark.sql
def test_d_g_first_open_one_receipt_then_quiet(cn, monkeypatch):
    """(d)+(g): first mark sends one receipt to sender; then no unopened receipt waiting."""
    from agent_coord.server.records import mail as rec_mail
    from agent_coord.server.records import opened as rec_opened
    from tests.server.records.conftest import seed_names

    seed_names(cn, ("unit", "roster"), ("sender", "desk"), ("reader", "desk"))

    class Book:
        _cn = cn

    receipts: list[dict] = []

    def capture_emit(cn0, desk, kind, payload, *, reason="addressed", room=None):
        if kind == "receipt":
            receipts.append({"desk": desk, "payload": payload})
        return "missed"

    monkeypatch.setattr(push, "emit", capture_emit)

    out = rpc._h_send(
        Book(),
        {"src": "sender", "dst": "reader", "body": "open me", "receipt": True, "project": "unit"},
        "unit",
        "sender",
    )
    mid = int(out["id"])
    assert mail_push.has_unopened_receipt(cn, "reader") is True
    assert mail_push.counts_as_waiting(
        pending=0, unread=False, unopened_receipt=mail_push.has_unopened_receipt(cn, "reader")
    )

    # First open -> exactly one receipt to sender.
    rec_opened.insert(cn, mid, "reader")
    assert len(receipts) == 1
    assert receipts[0]["desk"] == "sender"
    assert receipts[0]["payload"].get("kind") == "receipt"

    # Second open is a no-op for receipts.
    rec_opened.insert(cn, mid, "reader")
    assert len(receipts) == 1

    assert mail_push.has_unopened_receipt(cn, "reader") is False
    rows = rec_mail.to_list(cn, mid)
    mine = next(r for r in rows if r["desk"] == "reader")
    assert mine.get("opened") is not None
    assert int(mine.get("receipt") or 0) == 1


@pytest.mark.sql
def test_f_sql_unopened_receipt_is_waiting(cn):
    from tests.server.records.conftest import seed_names

    seed_names(cn, ("unit", "roster"), ("s", "desk"), ("r", "desk"))

    class Book:
        _cn = cn

    out = rpc._h_send(
        Book(),
        {"src": "s", "dst": "r", "body": "need open", "receipt": True, "project": "unit"},
        "unit",
        "s",
    )
    assert int(out["id"]) > 0
    assert mail_push.has_unopened_receipt(cn, "r") is True
    # A plain letter (no receipt) does not count.
    out2 = rpc._h_send(
        Book(),
        {"src": "s", "dst": "r", "body": "ordinary", "project": "unit"},
        "unit",
        "s",
    )
    assert int(out2["id"]) > 0
    # Still True because the first receipt letter remains unopened.
    assert mail_push.has_unopened_receipt(cn, "r") is True
