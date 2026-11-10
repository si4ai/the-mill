# -*- coding: utf-8 -*-
"""Card 1090: connect keeps hops in a local sqlite file and sends them in order."""
from __future__ import annotations

import pytest

from agent_coord.client.tw.outbox import Outbox, native_path, send_pending


def test_native_path_rejects_a_mount_and_a_share(tmp_path) -> None:
    from agent_coord.client.tw.outbox import _reject

    native_path(tmp_path / "desk.hops.sqlite")
    for text in (
        "/mnt/c/mill/desk.hops.sqlite",
        "//host/share/desk.hops.sqlite",
        "\\\\host\\share\\desk.hops.sqlite",
    ):
        with pytest.raises(OSError):
            _reject(text)


def test_send_pending_is_start_then_exit(tmp_path) -> None:
    box = Outbox(tmp_path / "desk.hops.sqlite")
    try:
        box.add({"watch_id": "tw-a", "kind": "start"})
        box.add({"watch_id": "tw-a", "kind": "exit", "exit_code": 0})
        sent: list[str] = []

        def ok(body):
            sent.append(body["kind"])
            return {"ok": True, "result": {"done": "noop"}}

        assert send_pending(box, ok) == "ok"
        assert send_pending(box, ok) == "ok"
        assert send_pending(box, ok) == "empty"
        assert sent == ["start", "exit"]
        assert box.peek() is None
    finally:
        box.close()


def test_busy_keeps_the_row(tmp_path) -> None:
    box = Outbox(tmp_path / "desk.hops.sqlite")
    try:
        box.add({"watch_id": "tw-a", "kind": "start"})

        def busy(_body):
            return {"ok": False, "code": "busy", "msg": "slow down"}

        assert send_pending(box, busy) == "busy"
        assert box.peek()["kind"] == "start"
    finally:
        box.close()


def test_cap_does_not_block_another_watch(tmp_path) -> None:
    box = Outbox(tmp_path / "desk.hops.sqlite")
    try:
        box.add({"watch_id": "tw-a", "kind": "start"})
        box.add({"watch_id": "tw-b", "kind": "exit", "exit_code": 0})
        sent: list[str] = []

        def call(body):
            sent.append(body["watch_id"])
            if body["watch_id"] == "tw-a":
                return {"ok": False, "code": "cap"}
            assert "id" not in body
            return {"ok": True}

        assert send_pending(box, call) == "ok"
        assert sent == ["tw-a", "tw-b"]
        assert box.peek()["watch_id"] == "tw-a"
        assert send_pending(box, call) == "cap"
        assert box.peek()["watch_id"] == "tw-a"
    finally:
        box.close()


def test_desk_and_card_round_trip_without_the_row_id(tmp_path) -> None:
    box = Outbox(tmp_path / "desk.hops.sqlite")
    try:
        box.add({"watch_id": "tw-a", "kind": "start", "desk": "builder", "card": 1090})
        sent: list[dict] = []

        def ok(body):
            sent.append(dict(body))
            return {"ok": True}

        assert send_pending(box, ok) == "ok"
        assert sent[0]["desk"] == "builder"
        assert sent[0]["card"] == 1090
        assert "id" not in sent[0]
    finally:
        box.close()
