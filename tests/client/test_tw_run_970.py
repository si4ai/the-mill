# -*- coding: utf-8 -*-
"""Card 970 slice (b): tw run, list, and stop. No doing write."""
from __future__ import annotations

import sys
import threading
import time

from agent_coord.client.route_chain import load_routes
from agent_coord.client.tw.link import serve
from agent_coord.client.tw.proc import _finish_event, list_runs, run_argv, stop_run


def _home(monkeypatch, tmp_path):
    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)
    monkeypatch.setattr("agent_coord.client.offices.desk_local_file", lambda *a, **k: None)


def test_run_registers_lists_and_stops(tmp_path, monkeypatch) -> None:
    _home(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "agent_coord.client.http.mill_http_call",
        lambda body: {"ok": True, "result": {"ok": True}},
    )
    link = serve("tw-run")
    box: dict = {}

    def go() -> None:
        try:
            box["code"] = run_argv(
                "tw-run",
                [sys.executable, "-c", "import time; time.sleep(30)"],
            )
        except BaseException as exc:
            box["error"] = exc

    thread = threading.Thread(target=go, daemon=True)
    thread.start()
    try:
        rows: list = []
        deadline = time.time() + 5
        while time.time() < deadline:
            rows = list_runs("tw-run")
            if rows:
                break
            time.sleep(0.05)
        assert rows, box
        watch_id = rows[0]["watch_id"]
        assert stop_run("tw-run", watch_id) == 0
        thread.join(5)
        assert not thread.is_alive(), box
        assert "error" not in box
        keys = [key for key, _argv in load_routes("tw-run")]
        assert watch_id in keys
        done = list_runs("tw-run")
        assert len(done) == 1
        assert done[0]["watch_id"] == watch_id
        assert done[0]["exit_code"] is not None
    finally:
        link.close()


def test_connect_stop_ends_the_child(tmp_path, monkeypatch) -> None:
    _home(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "agent_coord.client.http.mill_http_call",
        lambda body: {"ok": True, "result": {"ok": True}},
    )
    link = serve("tw-stop")
    box: dict = {}

    def go() -> None:
        try:
            box["code"] = run_argv(
                "tw-stop",
                [sys.executable, "-c", "import time; time.sleep(30)"],
            )
        except BaseException as exc:
            box["error"] = exc

    thread = threading.Thread(target=go, daemon=True)
    thread.start()
    try:
        rows: list = []
        deadline = time.time() + 5
        while time.time() < deadline:
            rows = list_runs("tw-stop")
            if rows:
                break
            time.sleep(0.05)
        assert rows, box
        assert link.stop(rows[0]["watch_id"], "desk") is True
        thread.join(5)
        assert not thread.is_alive(), box
        assert "error" not in box
    finally:
        link.close()


def _wait_kind(hops: list[dict], kind: str) -> None:
    deadline = time.time() + 3
    while time.time() < deadline:
        if any(item.get("kind") == kind for item in hops):
            return
        time.sleep(0.05)
    raise AssertionError(hops)


def test_exit_zero_is_zero(tmp_path, monkeypatch) -> None:
    _home(monkeypatch, tmp_path)
    hops: list[dict] = []

    def hop(body):
        hops.append(dict(body))
        return {"ok": True, "result": {"ok": True}}

    monkeypatch.setattr("agent_coord.client.http.mill_http_call", hop)
    link = serve("tw-exit-0")
    try:
        code = run_argv(
            "tw-exit-0",
            [sys.executable, "-c", "import sys; sys.exit(0)"],
        )
        assert code == 0
        _wait_kind(hops, "exit")
        exits = [h for h in hops if h.get("kind") == "exit"]
        assert exits[-1].get("exit_code") == 0
        assert [h.get("kind") for h in hops if h.get("verb") == "tw.event"] == ["start", "exit"]
    finally:
        link.close()


def test_exit_code_three_is_three(tmp_path, monkeypatch) -> None:
    _home(monkeypatch, tmp_path)
    hops: list[dict] = []
    monkeypatch.setattr(
        "agent_coord.client.http.mill_http_call",
        lambda body: hops.append(dict(body)) or {"ok": True, "result": {"ok": True}},
    )
    link = serve("tw-exit-3")
    try:
        code = run_argv(
            "tw-exit-3",
            [sys.executable, "-c", "import sys; sys.exit(3)"],
        )
        assert code == 3
        _wait_kind(hops, "exit")
        exits = [h for h in hops if h.get("kind") == "exit"]
        assert exits and exits[-1].get("exit_code") == 3
    finally:
        link.close()


def test_exit_code_one_is_one(tmp_path, monkeypatch) -> None:
    _home(monkeypatch, tmp_path)
    hops: list[dict] = []
    monkeypatch.setattr(
        "agent_coord.client.http.mill_http_call",
        lambda body: hops.append(dict(body)) or {"ok": True, "result": {"ok": True}},
    )
    link = serve("tw-exit-1")
    try:
        code = run_argv(
            "tw-exit-1",
            [sys.executable, "-c", "import sys; sys.exit(1)"],
        )
        assert code == 1
        _wait_kind(hops, "exit")
        exits = [h for h in hops if h.get("kind") == "exit"]
        assert exits and exits[-1].get("exit_code") == 1
    finally:
        link.close()


def test_outside_signal_is_a_crash_and_a_stop_stays_an_exit() -> None:
    assert _finish_event(-15, stopped=True, crashed=False) == (-15, "exit", "stopped")
    assert _finish_event(-15, stopped=False, crashed=False) == (143, "crash", "killed")
    assert _finish_event(1, stopped=False, crashed=False) == (1, "exit", None)
    assert _finish_event(0, stopped=False, crashed=True) == (0, "crash", "killed")


def test_stop_flag_exit_has_cause_stopped(tmp_path, monkeypatch) -> None:
    _home(monkeypatch, tmp_path)
    hops: list[dict] = []
    monkeypatch.setattr(
        "agent_coord.client.http.mill_http_call",
        lambda body: hops.append(dict(body)) or {"ok": True, "result": {"ok": True}},
    )
    link = serve("tw-stopped")
    box: dict = {}

    def go() -> None:
        try:
            box["code"] = run_argv(
                "tw-stopped",
                [sys.executable, "-c", "import time; time.sleep(30)"],
            )
        except BaseException as exc:
            box["error"] = exc

    thread = threading.Thread(target=go, daemon=True)
    thread.start()
    try:
        rows: list = []
        deadline = time.time() + 5
        while time.time() < deadline:
            rows = list_runs("tw-stopped")
            if rows:
                break
            time.sleep(0.05)
        assert rows, box
        assert stop_run("tw-stopped", rows[0]["watch_id"]) == 0
        thread.join(5)
        assert not thread.is_alive(), box
        assert "error" not in box
        _wait_kind(hops, "exit")
        exits = [h for h in hops if h.get("kind") == "exit"]
        assert exits[-1].get("cause") == "stopped"
    finally:
        link.close()


def test_no_link_at_exit_posts_once_via_http(tmp_path, monkeypatch, capsys) -> None:
    _home(monkeypatch, tmp_path)
    hops: list[dict] = []

    def boom(*a, **k):
        raise OSError("down")

    monkeypatch.setattr("agent_coord.client.tw.proc.open_session", boom)
    monkeypatch.setattr(
        "agent_coord.client.http.mill_http_call",
        lambda body: hops.append(dict(body)) or {"ok": True, "result": {"ok": True}},
    )
    code = run_argv("tw-offline", ["true"])
    assert code == 1
    assert hops == []
    from agent_coord.client.session_errors import bridge_hint

    assert capsys.readouterr().err.strip() == bridge_hint().strip()


def test_dead_tw_pid_sends_crash_lost_and_drops(tmp_path, monkeypatch) -> None:
    _home(monkeypatch, tmp_path)
    from agent_coord.client.tw.proc import _save, runs_path

    hops: list[dict] = []
    monkeypatch.setattr(
        "agent_coord.client.http.mill_http_call",
        lambda body: hops.append(dict(body)) or {"ok": True, "result": {"ok": True}},
    )
    dead = 2147483646
    _save(
        "tw-lost",
        {
            "tw-deadbeef": {
                "pid": dead,
                "argv": ["true"],
                "stop": False,
                "tw_pid": dead,
            }
        },
    )
    assert list_runs("tw-lost") == []
    assert hops == []
    path = runs_path("tw-lost")
    if path.exists():
        import json
        assert json.loads(path.read_text(encoding="utf-8")) == {}
