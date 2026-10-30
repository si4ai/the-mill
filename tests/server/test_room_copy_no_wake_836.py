# -*- coding: utf-8 -*-
"""Card 836: a room copy wakes no one by default. Regression row F127 (room-copy-quiet).

Wakeup storms item 4, option B (the office human's choice, 2026-10-23). Reply-all
still reaches every room member; only the wake default changes: `mill join DESK
--webhook-...` without --wake-on arms `addressed`, so a letter a desk gets only as a
room member (wake.reason room) does not POST and waits for its next connect.
`--wake-on all` keeps room wakes.
"""
from __future__ import annotations

import inspect
from unittest.mock import MagicMock

from agent_coord.server import wake
from agent_coord.server.api.mill import rpc
from agent_coord.server.records import join as rec_join


def _arm(monkeypatch, delivery, stored="addressed"):
    armed: list[str] = []
    monkeypatch.setattr(wake, "check_url", lambda u: (u, "hooks.example.test"))
    monkeypatch.setattr(wake, "normalize_key", lambda k: k)
    monkeypatch.setattr(wake, "test_fire", lambda *a, **k: {"ok": True, "status": 200})
    monkeypatch.setattr(wake, "desk_roster", lambda cn, d: "")
    monkeypatch.setattr(rec_join, "wake_target", lambda cn, d: None)
    monkeypatch.setattr(rec_join, "wake_arm", lambda cn, d, u, k, wake_on: armed.append(wake_on))
    c = MagicMock()
    out = rpc._join_delivery(c, "away", dict(delivery, mode="webhook", url="https://hooks.example.test/x", key="k"))
    return out, armed


def test_a_join_without_wake_on_arms_addressed(monkeypatch) -> None:
    out, armed = _arm(monkeypatch, {})
    assert armed == ["addressed"] and out["wake_on"] == "addressed"


def test_wake_on_all_still_arms_all(monkeypatch) -> None:
    out, armed = _arm(monkeypatch, {"wake_on": "all"})
    assert armed == ["all"] and out["wake_on"] == "all"


def test_the_record_defaults_are_addressed(monkeypatch) -> None:
    assert inspect.signature(rec_join.wake_arm).parameters["wake_on"].default == "addressed"
    monkeypatch.setattr(rec_join, "call", lambda cn, sp, args: [{"armed": 1, "host": "h"}])
    assert rec_join.wake_state(MagicMock(), "away")["wake_on"] == "addressed"
