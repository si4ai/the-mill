# -*- coding: utf-8 -*-
"""Card 1090 step 4: no sit runs nothing, and connect drains its hop file."""
from __future__ import annotations

import sys
import threading
import time

from agent_coord.client.tw.link import Session, serve
from agent_coord.client.tw.outbox import Outbox, outbox_path
from agent_coord.client.tw.proc import list_runs, query_status, run_argv


def _home(monkeypatch, tmp_path):
    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)
    monkeypatch.setattr("agent_coord.client.offices.desk_local_file", lambda *a, **k: None)


def _down(*_a, **_k):
    raise OSError("down")


def _wait(pred, seconds: float = 3) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if pred():
            return
        time.sleep(0.05)
    raise AssertionError("timed out")


def test_no_sit_runs_nothing(tmp_path, monkeypatch, capsys) -> None:
    _home(monkeypatch, tmp_path)
    monkeypatch.setattr("agent_coord.client.tw.proc.open_session", _down)
    monkeypatch.setattr("agent_coord.client.http.mill_http_call", _down)
    marker = tmp_path / "ran.txt"
    code = run_argv(
        "tw-spool",
        [sys.executable, "-c", "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('x')", str(marker)],
    )
    assert code == 1
    assert not marker.exists()
    from agent_coord.client.session_errors import bridge_hint

    assert capsys.readouterr().err.strip() == bridge_hint().strip()


def test_no_sit_does_not_post(tmp_path, monkeypatch) -> None:
    _home(monkeypatch, tmp_path)
    hops: list[dict] = []

    def ok(body):
        hops.append(dict(body))
        return {"ok": True}

    monkeypatch.setattr("agent_coord.client.tw.proc.open_session", _down)
    monkeypatch.setattr("agent_coord.client.http.mill_http_call", ok)
    code = run_argv("tw-order", [sys.executable, "-c", "import sys; sys.exit(0)"])
    assert code == 1
    assert hops == []


def test_connect_drains_leftovers_in_order(tmp_path, monkeypatch) -> None:
    _home(monkeypatch, tmp_path)
    hops: list[dict] = []

    def ok(body):
        hops.append(dict(body))
        return {"ok": True, "result": {"done": "noop"}}

    monkeypatch.setattr("agent_coord.client.http.mill_http_call", ok)
    box = Outbox(outbox_path("tw-replay"))
    box.add({"watch_id": "tw-a", "kind": "start"})
    box.add({"watch_id": "tw-a", "kind": "exit", "exit_code": 0})
    box.close()
    link = serve("tw-replay")
    try:
        assert link.drain() == "empty"
        events = [item for item in hops if item.get("verb") == "tw.event"]
        assert [item["kind"] for item in events] == ["start", "exit"]
        assert [item for item in hops if item.get("verb") == "tw.reconcile"] == [
            {"verb": "tw.reconcile", "live": []}
        ]
        assert "id" not in hops[0]
        assert hops[0].get("counts") is None
        assert link._outbox is not None and link._outbox.peek() is None
    finally:
        link.close()
    hops.clear()
    again = serve("tw-replay")
    try:
        assert again.drain() == "empty"
        assert hops == [{"verb": "tw.reconcile", "live": []}]
    finally:
        again.close()


def test_list_does_not_send(tmp_path, monkeypatch) -> None:
    _home(monkeypatch, tmp_path)
    hops: list[dict] = []
    monkeypatch.setattr(
        "agent_coord.client.http.mill_http_call",
        lambda body: hops.append(dict(body)) or {"ok": True},
    )
    box = Outbox(outbox_path("tw-pass"))
    box.add({"watch_id": "tw-d", "kind": "start"})
    box.close()
    assert list_runs("tw-pass") == []
    query_status("tw-pass")
    assert hops == []


def test_transport_error_keeps_the_row_and_the_sit(tmp_path, monkeypatch) -> None:
    _home(monkeypatch, tmp_path)
    monkeypatch.setattr("agent_coord.client.http.mill_http_call", _down)
    box = Outbox(outbox_path("tw-down"))
    box.add({"watch_id": "tw-c", "kind": "start"})
    box.close()
    link = serve("tw-down")
    try:
        assert link.drain() == "down"
        assert link._outbox is not None
        assert link._outbox.peek()["kind"] == "start"
        session = Session(link)
        try:
            got = session.request({"type": "register", "key": "tw:still", "argv": ["tool"]})
            assert got["ok"] is True
        finally:
            session.close()
    finally:
        link.close()


def test_close_keeps_unsent_rows(tmp_path, monkeypatch) -> None:
    _home(monkeypatch, tmp_path)
    hops: list[dict] = []
    monkeypatch.setattr("agent_coord.client.http.mill_http_call", _down)
    box = Outbox(outbox_path("tw-sit"))
    box.add({"watch_id": "tw-b", "kind": "start"})
    box.add({"watch_id": "tw-b", "kind": "exit", "exit_code": 0})
    box.close()
    link = serve("tw-sit")
    link.close()
    assert hops == []
    left = Outbox(outbox_path("tw-sit"))
    try:
        assert left.peek()["kind"] == "start"
    finally:
        left.close()


def test_peer_drop_posts_a_crash(tmp_path, monkeypatch) -> None:
    _home(monkeypatch, tmp_path)
    hops: list[dict] = []

    def ok(body):
        hops.append(dict(body))
        return {"ok": True}

    monkeypatch.setattr("agent_coord.client.http.mill_http_call", ok)
    link = serve("tw-crash")
    session = Session(link)
    try:
        got = session.request({"type": "event", "watch_id": "w1", "kind": "start"})
        assert got["ok"] is True
        assert link.drain() == "empty"
        session.close()
        session = None

        def crashed() -> bool:
            link.drain()
            return any(item.get("kind") == "crash" and item.get("cause") == "lost" for item in hops)

        _wait(crashed)
    finally:
        if session is not None:
            session.close()
        link.close()


def test_mid_run_loss_prints_once_and_keeps_the_child(tmp_path, monkeypatch, capsys) -> None:
    _home(monkeypatch, tmp_path)
    hops: list[dict] = []

    def ok(body):
        hops.append(dict(body))
        return {"ok": True}

    monkeypatch.setattr("agent_coord.client.http.mill_http_call", ok)
    link = serve("tw-mid")
    box: dict = {}

    def go() -> None:
        try:
            box["code"] = run_argv(
                "tw-mid",
                [sys.executable, "-c", "import time; time.sleep(30)"],
            )
        except BaseException as exc:
            box["error"] = exc

    thread = threading.Thread(target=go, daemon=True)
    thread.start()
    try:
        _wait(lambda: any(item.get("kind") == "start" for item in hops) and bool(list_runs("tw-mid")))
        link.close()
        link = None
        from agent_coord.client.session_errors import bridge_hint
        from agent_coord.client.tw.proc import stop_run

        time.sleep(0.3)
        assert thread.is_alive(), box
        rows = list_runs("tw-mid")
        assert rows
        assert [item.get("kind") for item in hops if item.get("verb") == "tw.event"] == ["start"]
        assert stop_run("tw-mid", rows[0]["watch_id"]) == 0
        thread.join(5)
        assert not thread.is_alive(), box
        assert "error" not in box
        err = capsys.readouterr().err
        assert err.count(bridge_hint().strip()) == 1
        assert [item.get("kind") for item in hops if item.get("verb") == "tw.event"] == ["start"]
    finally:
        if thread.is_alive():
            rows = list_runs("tw-mid")
            if rows:
                from agent_coord.client.tw.proc import stop_run

                stop_run("tw-mid", rows[0]["watch_id"])
            thread.join(2)
        if link is not None:
            link.close()
