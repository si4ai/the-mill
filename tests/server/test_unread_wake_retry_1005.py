# -*- coding: utf-8 -*-
"""Card 1005 / F-unread-wake-retry: failed wake for unread-only mail is retried.

After a short connect drains the push queue, ring_waiting / trailing can still
POST for mailbox unread. A failed POST must arm retry, and _queue_drained must
not stop the chain while unread remains. Does not change card 949/1006 wake
suppression rules.
"""
from __future__ import annotations

import json
import urllib.error

from agent_coord.server import push, wake
from tests.server.test_desk_webhook_618 import _Queue, _Resp
from tests.server.webhook_fixtures import arm


class _Opener:
    def __init__(self, codes: list[int]):
        self.codes = list(codes)
        self.posts: list = []

    def __call__(self, req, timeout=0):
        self.posts.append(req)
        code = self.codes.pop(0) if self.codes else 503
        if code < 200 or code > 299:
            raise urllib.error.HTTPError(req.full_url, code, "busy", {}, None)
        return _Resp()


def _unread_frame(n: int) -> dict:
    return {"kind": "mail", "id": n, "body": f"letter {n}", "sender": "s"}


def test_failed_unread_only_post_arms_retry(monkeypatch) -> None:
    """SPIN W30: push pending=0, unread remains, first POST fails -> retry armed."""
    lines: list[str] = []
    scheduled: list[tuple] = []
    monkeypatch.setattr(push, "_bc_log", lines.append)
    arm(monkeypatch)
    q = _Queue()
    q.install(monkeypatch)
    monkeypatch.setattr(push.HUB, "rooms", {})
    monkeypatch.setattr(wake, "_book", lambda: object())
    monkeypatch.setattr(wake, "_NOTE", {}, raising=False)
    monkeypatch.setattr(wake, "_schedule", lambda delay, fn, *args: scheduled.append((delay, fn, args)))
    monkeypatch.setattr(push, "unread_mail_frames", lambda cn, desk, **k: [_unread_frame(1005)])
    monkeypatch.setattr(
        "agent_coord.server.records.push.waiting", lambda cn, desk: None
    )
    # Push queue empty (short connect drained it); only mailbox unread remains.
    q.rows.clear()
    opener = _Opener([503, 200])
    monkeypatch.setattr(wake, "_open", opener)

    assert push.ring_waiting(object(), "away", "leave") == "error"
    assert len(opener.posts) == 1
    assert scheduled, "unread-only failed wake must arm a retry (card 1005)"
    delay, fn, args = scheduled.pop(0)
    fn(*args)
    assert len(opener.posts) == 2
    assert any("wake=sent" in ln and "reason=retry" in ln for ln in lines)


def test_queue_drained_false_while_unread_remains(monkeypatch) -> None:
    monkeypatch.setattr(wake, "_book", lambda: object())
    monkeypatch.setattr(
        "agent_coord.server.records.push.pending", lambda cn, desk: 0
    )
    monkeypatch.setattr(
        push, "unread_mail_frames", lambda cn, desk, **k: [_unread_frame(77)]
    )
    assert wake._queue_drained("away") is False


def test_queue_drained_true_when_push_and_unread_empty(monkeypatch) -> None:
    monkeypatch.setattr(wake, "_book", lambda: object())
    monkeypatch.setattr(
        "agent_coord.server.records.push.pending", lambda cn, desk: 0
    )
    monkeypatch.setattr(push, "unread_mail_frames", lambda cn, desk, **k: [])
    assert wake._queue_drained("away") is True
