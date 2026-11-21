# -*- coding: utf-8 -*-
"""Card 1242 on a real book: wake_reach reads armed and the newest lease ring per desk."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from agent_coord.server import push, wake
from agent_coord.server.records import join as rec_join
from agent_coord.server.records import push as rec_push
from tests.server.test_desk_webhook_618 import _Resp
from tests.server.webhook_fixtures import HOOK_KEY, HOOK_URL, arm

pytestmark = pytest.mark.sql


def test_wake_reach_armed_and_last_ring(cn, monkeypatch):
    from tests.server.records.conftest import admin_desk

    arm(monkeypatch)
    monkeypatch.setattr(wake, "_EPOCH", {}, raising=False)
    monkeypatch.setattr(wake, "_NOTE", {}, raising=False)
    monkeypatch.setattr(push.HUB, "rooms", {})
    hook = admin_desk(cn, "r1242-hook")
    plain = admin_desk(cn, "r1242-plain")
    rec_join.wake_arm(cn, hook, HOOK_URL, HOOK_KEY)
    cn.commit()

    before = rec_join.wake_reach(cn, [hook, plain])
    assert before[hook] == {"armed": True, "last_wake": None}
    assert before[plain] == {"armed": False, "last_wake": None}

    frame = {"kind": "hint", "type": "todo", "id": 1}
    wid = rec_push.row_id(rec_push.put(cn, hook, "hint", frame, "missed"))
    with patch("agent_coord.server.wake._open", lambda req, timeout=0: _Resp()):
        assert wake.post_desk(cn, hook, frame, hint_id=1, wake_id=wid) == "sent"
    cn.commit()

    after = rec_join.wake_reach(cn, [hook, plain])
    assert after[hook]["armed"] is True
    assert isinstance(after[hook]["last_wake"], str) and after[hook]["last_wake"].endswith("Z")
    assert after[plain] == {"armed": False, "last_wake": None}
    assert rec_join.wake_reach(cn, []) == {}
