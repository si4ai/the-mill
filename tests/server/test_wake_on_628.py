"""#628 'wake only the bots that need it' is a desk choice, not receiver logic.
mill join DESK --webhook-... --wake-on addressed|all (default all) is stored on
the join row. With addressed, a room-only item does not POST; it waits in the
queue for the desk's next connect, and the wall logs one line
`wake=skipped reason=room-only` (#625 format). Row F74 (wake-on)."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agent_coord.helpers.errors import CoordError
from agent_coord.server import mail_push, push, wake
from tests.server.test_desk_webhook_618 import _args, _hint, _Queue, _Resp
from tests.server.webhook_fixtures import HOOK_KEY, HOOK_URL, arm


@pytest.fixture
def desk(monkeypatch):
    arm(monkeypatch)
    q = _Queue()
    q.install(monkeypatch)
    state = {"wake_on": "addressed"}
    monkeypatch.setattr("agent_coord.server.records.join.wake_state",
                        lambda cn, d: {"armed": True, "host": "h", "wake_on": state["wake_on"]})
    monkeypatch.setattr(push.HUB, "rooms", {})
    lines: list[str] = []
    monkeypatch.setattr(push, "_bc_log", lines.append)
    posts: list[dict] = []

    def fake(req, timeout=0):
        posts.append(json.loads(req.data.decode("utf-8")))
        return _Resp()

    with patch("agent_coord.server.wake._open", fake):
        yield SimpleNamespace(q=q, state=state, lines=lines, posts=posts)


def _letter(room_only):
    letter = {"id": 6280, "desk": "boss", "sender_roster": "crew", "body": "text"}
    with patch("agent_coord.server.records.mail.letter_row", return_value=letter), patch(
        "agent_coord.server.records.mail.to_list", return_value=[{"desk": "away"}]
    ), patch("agent_coord.server.records.mail.tree_crumbs", return_value={"tree": "build-room"}):
        mail_push.push_mail(MagicMock(), 6280, room_only=set(room_only))


def test_addressed_desk_skips_a_room_only_letter_and_it_still_queues(desk):
    _letter({"away"})
    assert desk.posts == []
    assert [ln for ln in desk.lines if ln.startswith("webhook ")] == [
        "webhook desk=away kind=mail id=6280 wake=skipped reason=room-only"
    ]
    assert [r["id"] for r in desk.q.rows] == [6280] and desk.q.rows[0]["outcome"] == "missed"


def test_addressed_desk_still_wakes_for_a_named_letter_and_a_hint(desk):
    _letter(())
    assert len(desk.posts) == 1 and desk.posts[0]["wake"]["reason"] == "addressed"
    wake._GATE.clear()
    _hint(MagicMock(), 6281)
    assert len(desk.posts) == 2


def test_a_skipped_room_item_takes_no_window(desk):
    _letter({"away"})
    _letter(())
    assert len(desk.posts) == 1


def test_wake_on_all_wakes_for_room_letters(desk):
    desk.state["wake_on"] = "all"
    _letter({"away"})
    assert len(desk.posts) == 1 and desk.posts[0]["wake"]["reason"] == "room"


class _Join:
    def __init__(self):
        self.row = None
        self.on = "addressed"  # card 836: the default
        self.calls: list[str] = []

    def install(self, monkeypatch):
        from agent_coord.server.records import join as rec_join

        monkeypatch.setattr(rec_join, "wake_target", lambda cn, d: self.row)
        monkeypatch.setattr(rec_join, "wake_state", lambda cn, d: {"armed": bool(self.row), "host": "h", "wake_on": self.on})

        def arm_(cn, d, url, key, wake_on="addressed"):
            self.calls.append("arm")
            self.row, self.on = (url, key), wake_on

        monkeypatch.setattr(rec_join, "wake_arm", arm_)


def _deliver(delivery):
    from agent_coord.server.api.mill.rpc import _join_delivery

    return _join_delivery(SimpleNamespace(_cn=MagicMock()), "away", delivery)


def test_join_stores_wake_on_and_a_change_alone_sends_no_test_post(monkeypatch):
    arm(monkeypatch)
    j = _Join()
    j.install(monkeypatch)
    posts: list[int] = []
    with patch("agent_coord.server.wake._open", lambda req, timeout=0: posts.append(1) or _Resp()):
        got = _deliver({"mode": "webhook", "url": HOOK_URL, "key": HOOK_KEY, "wake_on": "all"})
        assert got["wake_on"] == "all" and j.on == "all" and len(posts) == 1
        got = _deliver({"mode": "webhook", "url": HOOK_URL, "key": HOOK_KEY})
        # Card 836: no --wake-on means addressed.
        assert got == {"webhook": "armed", "host": got["host"], "test": "unchanged", "wake_on": "addressed"}
        assert j.on == "addressed" and len(posts) == 1  # last join wins, no second test POST
        got = _deliver({"mode": "webhook", "url": HOOK_URL, "key": HOOK_KEY})
        assert j.calls == ["arm", "arm"]  # same values again: nothing written


def test_join_refuses_an_unknown_wake_on(monkeypatch):
    arm(monkeypatch)
    _Join().install(monkeypatch)
    with pytest.raises(CoordError) as ei:
        _deliver({"mode": "webhook", "url": HOOK_URL, "key": HOOK_KEY, "wake_on": "room"})
    assert "--wake-on is addressed or all" in str(ei.value)


def test_cli_sends_wake_on_only_with_the_webhook_options(tmp_path):
    from agent_coord.client.wake_cli import delivery_body

    kf = tmp_path / "key"
    kf.write_text(HOOK_KEY + "\n", encoding="utf-8")
    uf = tmp_path / "url"
    uf.write_text(HOOK_URL + "\n", encoding="utf-8")
    got = delivery_body(_args(webhook_url_file=str(uf), webhook_key_file=str(kf), wake_on="addressed"))
    assert got == {"mode": "webhook", "url": HOOK_URL, "key": HOOK_KEY, "wake_on": "addressed"}
    for bad in (_args(wake_on="addressed"), _args(websocket=True, wake_on="all")):
        with pytest.raises(CoordError) as ei:
            delivery_body(bad)
        assert "--wake-on goes with --webhook-url-file and --webhook-key-file" in str(ei.value)


def test_the_sync_line_says_when_a_desk_wakes_on_addressed_only(monkeypatch):
    monkeypatch.setattr("agent_coord.server.records.join.wake_state",
                        lambda cn, d: {"armed": True, "host": "h", "wake_on": "addressed"})
    assert push.wake_line(MagicMock(), "away") == "webhook armed (host h, wake on addressed)"
    monkeypatch.setattr("agent_coord.server.records.join.wake_state",
                        lambda cn, d: {"armed": True, "host": "h", "wake_on": "all"})
    assert push.wake_line(MagicMock(), "away") == "webhook armed (host h)"
