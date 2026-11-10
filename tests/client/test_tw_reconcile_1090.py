# -*- coding: utf-8 -*-
"""Card 1090: connect records a lost crash for a ghost tw run."""
from __future__ import annotations

import os

from agent_coord.client.tw.link import serve
from agent_coord.client.tw.outbox import Outbox, outbox_path
from agent_coord.client.tw.proc import _image_name, _load, _save, list_runs


def _home(monkeypatch, tmp_path):
    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)
    monkeypatch.setattr("agent_coord.client.offices.desk_local_file", lambda *a, **k: None)


def _sitting(monkeypatch) -> None:
    monkeypatch.setattr(
        "agent_coord.client.seat.status.look",
        lambda *args, **kwargs: type("_s", (), {"kind": "sitting"})(),
    )


def _row(**extra):
    row = {
        "pid": 2147483646,
        "argv": ["tool"],
        "stop": False,
        "tw_pid": 2147483646,
        "start": "2026-11-10T06:40:00Z",
        "log": "run.log",
    }
    row.update(extra)
    return row


def test_image_of_this_process_is_not_tw() -> None:
    name = _image_name(os.getpid()).lower()
    assert name
    assert name not in {"tw", "tw.exe"}


def test_list_keeps_a_started_ghost(tmp_path, monkeypatch) -> None:
    _home(monkeypatch, tmp_path)
    _save("tw-keep", {"tw-ghost": _row()})
    assert list_runs("tw-keep") == []
    assert "tw-ghost" in _load("tw-keep")


def test_dead_wrapper_is_a_lost_crash_after_drain(tmp_path, monkeypatch) -> None:
    _home(monkeypatch, tmp_path)
    _sitting(monkeypatch)
    hops: list[dict] = []

    def ok(body):
        hops.append(dict(body))
        return {"ok": True, "result": {"ok": True}}

    monkeypatch.setattr("agent_coord.client.http.mill_http_call", ok)
    box = Outbox(outbox_path("tw-ghost"))
    box.add({"watch_id": "tw-old", "kind": "start", "ts_ms": 5})
    box.close()
    _save("tw-ghost", {"tw-ghost": _row(), "tw-live": _row(pid=os.getpid(), tw_pid=os.getpid())})
    monkeypatch.setattr("agent_coord.client.tw.proc._still_tw", lambda pid: pid == os.getpid())
    link = serve("tw-ghost")
    try:
        assert link.drain() == "empty"
        events = [item for item in hops if item.get("verb") == "tw.event"]
        assert [item["kind"] for item in events] == ["start", "crash"]
        assert [item for item in hops if item.get("verb") == "tw.reconcile"] == [
            {"verb": "tw.reconcile", "live": ["tw-live"]}
        ]
        crash = events[1]
        assert crash["cause"] == "lost"
        assert crash["watch_id"] == "tw-ghost"
        assert crash["exit_code"] == 1
        assert isinstance(crash["ts_ms"], int) and crash["ts_ms"] >= 0
        assert "reconciled" not in crash
        assert crash.get("verb") == "tw.event"
        row = _load("tw-ghost")["tw-ghost"]
        assert row["reconciled"] is True
        assert row["cause"] == "lost"
        assert row["ts_ms"] == crash["ts_ms"]
        assert row["state"] == "finished"
        assert link._live_watch_ids == ["tw-live"]
        live = _load("tw-ghost")["tw-live"]
        assert live.get("reconciled") is not True
        assert live.get("state") != "finished"
    finally:
        link.close()


def test_reused_pid_is_not_the_wrapper(tmp_path, monkeypatch) -> None:
    _home(monkeypatch, tmp_path)
    _sitting(monkeypatch)
    hops: list[dict] = []
    monkeypatch.setattr(
        "agent_coord.client.http.mill_http_call",
        lambda body: hops.append(dict(body)) or {"ok": True, "result": {"ok": True}},
    )
    _save("tw-reuse", {"tw-reuse": _row(pid=os.getpid(), tw_pid=os.getpid())})
    link = serve("tw-reuse")
    try:
        assert link.drain() == "empty"
        events = [item for item in hops if item.get("verb") == "tw.event"]
        assert [item["kind"] for item in events] == ["crash"]
        assert [item for item in hops if item.get("verb") == "tw.reconcile"] == [
            {"verb": "tw.reconcile", "live": []}
        ]
        assert _load("tw-reuse")["tw-reuse"]["reconciled"] is True
        assert link._live_watch_ids == []
    finally:
        link.close()


def test_a_row_without_start_is_not_reconciled(tmp_path, monkeypatch) -> None:
    _home(monkeypatch, tmp_path)
    _sitting(monkeypatch)
    hops: list[dict] = []
    monkeypatch.setattr(
        "agent_coord.client.http.mill_http_call",
        lambda body: hops.append(dict(body)) or {"ok": True, "result": {"ok": True}},
    )
    _save(
        "tw-plain",
        {
            "tw-plain": {
                "pid": 2147483646,
                "argv": ["tool"],
                "stop": False,
                "tw_pid": 2147483646,
            }
        },
    )
    link = serve("tw-plain")
    try:
        assert link.drain() == "empty"
        assert hops == [{"verb": "tw.reconcile", "live": []}]
        assert "desk" not in hops[0]
        assert "wake" not in hops[0]
        assert _load("tw-plain")["tw-plain"].get("reconciled") is not True
    finally:
        link.close()


def test_too_many_live_ids_are_not_sent(tmp_path, monkeypatch) -> None:
    _home(monkeypatch, tmp_path)
    _sitting(monkeypatch)
    hops: list[dict] = []
    monkeypatch.setattr(
        "agent_coord.client.http.mill_http_call",
        lambda body: hops.append(dict(body)) or {"ok": True, "result": {"ok": True}},
    )
    live = ["tw-%d" % i for i in range(257)]
    monkeypatch.setattr(
        "agent_coord.client.tw.proc.reconcile_ghosts",
        lambda desk, box: list(live),
    )
    link = serve("tw-cap")
    try:
        assert link.drain() == "empty"
        assert hops == []
        assert link._live_watch_ids == live
    finally:
        link.close()
