# -*- coding: utf-8 -*-
"""Card 1321: a tw start carries the lease of the wake that started the run."""
from __future__ import annotations

import sys

import pytest

from agent_coord.client.tw.link import Session, serve
from agent_coord.client.tw.outbox import Outbox, _post_body
from agent_coord.client.tw.proc import run_argv
from agent_coord.client.tw.protocol import lease_token
from tests.client.test_tw_cmd_1303 import _home, _within


def _hops(monkeypatch, exit_delay: float = 0.0) -> list[dict]:
    """Office replies, recorded. exit_delay holds the exit post, as a slow office would."""
    import time

    hops: list[dict] = []

    def fake_http(body):
        if body.get("kind") == "exit" and exit_delay:
            time.sleep(exit_delay)
        hops.append(dict(body))
        return {"ok": True, "result": {"ok": True}}

    monkeypatch.setattr("agent_coord.client.http.mill_http_call", fake_http)
    return hops


def _events(hops: list[dict]) -> list[dict]:
    return [item for item in hops if item.get("verb") == "tw.event"]


@pytest.mark.parametrize("exit_delay", [0.0, 0.3])
def test_woken_run_start_carries_the_lease_and_the_end_does_not(tmp_path, monkeypatch, exit_delay) -> None:
    _home(monkeypatch, tmp_path)
    monkeypatch.setenv("MILL_LEASE", "abc123def456")
    hops = _hops(monkeypatch, exit_delay)
    link = serve("tw-wake")
    try:
        assert run_argv("tw-wake", [sys.executable, "-c", "pass"]) == 0
        # run_argv returns once the exit hop is queued; the sender posts it later.
        assert link.drain() == "empty"
        events = _events(hops)
        assert [e["kind"] for e in events] == ["start", "exit"]
        assert events[0]["wake_lease"] == "abc123def456"
        assert "wake_lease" not in events[1]
    finally:
        link.close()


@pytest.mark.parametrize("env", [None, "", "   "])
def test_manual_run_start_carries_no_lease(tmp_path, monkeypatch, env) -> None:
    _home(monkeypatch, tmp_path)
    if env is None:
        monkeypatch.delenv("MILL_LEASE", raising=False)
    else:
        monkeypatch.setenv("MILL_LEASE", env)
    hops = _hops(monkeypatch)
    link = serve("tw-hand")
    try:
        assert run_argv("tw-hand", [sys.executable, "-c", "pass"]) == 0
        assert link.drain() == "empty"
        events = _events(hops)
        assert [e["kind"] for e in events] == ["start", "exit"]
        assert all("wake_lease" not in e and "lease" not in e for e in events)
    finally:
        link.close()


def test_link_keeps_a_good_lease_on_start_only_and_drops_a_bad_one(tmp_path, monkeypatch) -> None:
    _home(monkeypatch, tmp_path)
    hops = _hops(monkeypatch)
    link = serve("tw-lease")
    session = Session(link)
    try:
        for wid, kind, lease in (("w-good", "start", "abc123def456"), ("w-bad", "start", "a b\nc"),
                                 ("w-good", "exit", "abc123def456")):
            body = {"type": "event", "watch_id": wid, "kind": kind, "wake_lease": lease}
            if kind == "exit":
                body["exit_code"] = 0
            _within(lambda b=body: session.request(b))
        assert link.drain() == "empty"
        events = _events(hops)
        assert events[0]["wake_lease"] == "abc123def456"
        assert "wake_lease" not in events[1]
        assert "wake_lease" not in events[2]
    finally:
        session.close()
        link.close()


def test_a_queued_start_keeps_its_lease(tmp_path) -> None:
    box = Outbox(tmp_path / "hops.sqlite")
    try:
        box.add({"watch_id": "w1", "kind": "start", "wake_lease": "abc123def456"})
        box.add({"watch_id": "w2", "kind": "start"})
        first = box.peek()
        assert _post_body(first)["wake_lease"] == "abc123def456"
        box.drop(first["id"])
        assert "wake_lease" not in _post_body(box.peek())
    finally:
        box.close()


def test_an_old_hop_file_gains_the_lease_column(tmp_path) -> None:
    import sqlite3

    path = tmp_path / "old.sqlite"
    db = sqlite3.connect(str(path))
    db.execute("CREATE TABLE hop (id INTEGER PRIMARY KEY, watch_id TEXT NOT NULL, kind TEXT NOT NULL,"
               " cause TEXT, exit_code INTEGER, wake INTEGER, counts TEXT, desk TEXT, card INTEGER,"
               " ts_ms INTEGER)")
    db.execute("INSERT INTO hop (watch_id, kind) VALUES ('w0', 'start')")
    db.commit()
    db.close()
    box = Outbox(path)
    try:
        assert "wake_lease" not in _post_body(box.peek())
    finally:
        box.close()


@pytest.mark.parametrize("raw,want", [
    ("abc123def456", "abc123def456"),
    ("  abc123def456\n", "abc123def456"),
    ("live-token-1", "live-token-1"),
    ("", None), (None, None), (7, None), ("a b", None), ("x" * 65, None), ("tok=1", None),
])
def test_lease_token_shape(raw, want) -> None:
    assert lease_token(raw) == want
