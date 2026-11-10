# -*- coding: utf-8 -*-
"""Card 970 slice (b): tw run, list, and stop. No doing write."""
from __future__ import annotations

import sys
import threading
import time

from agent_coord.client.route_chain import load_routes
from agent_coord.client.tw.link import serve
from agent_coord.client.tw.proc import list_runs, run_argv, stop_run


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


def test_pipeline_sleep_then_true_exits_zero(tmp_path, monkeypatch) -> None:
    """Card 1098: a non-last stage tw kills after the last exits does not fail the run."""
    _home(monkeypatch, tmp_path)
    hops: list[dict] = []

    def hop(body):
        hops.append(dict(body))
        return {"ok": True, "result": {"ok": True}}

    monkeypatch.setattr("agent_coord.client.http.mill_http_call", hop)
    link = serve("tw-pipe-ok")
    try:
        code = run_argv(
            "tw-pipe-ok",
            [],
            steps=[["sleep", "5"], ["true"]],
        )
        assert code == 0
        exits = [h for h in hops if h.get("kind") == "exit"]
        assert exits, hops
        assert exits[-1].get("exit_code") == 0
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
        code = run_argv("tw-exit-3", ["sh", "-c", "exit 3"])
        assert code == 3
        exits = [h for h in hops if h.get("kind") == "exit"]
        assert exits and exits[-1].get("exit_code") == 3
    finally:
        link.close()


def test_pipeline_false_then_true_keeps_pipefail(tmp_path, monkeypatch) -> None:
    _home(monkeypatch, tmp_path)
    hops: list[dict] = []
    monkeypatch.setattr(
        "agent_coord.client.http.mill_http_call",
        lambda body: hops.append(dict(body)) or {"ok": True, "result": {"ok": True}},
    )
    link = serve("tw-pipefail")
    try:
        code = run_argv("tw-pipefail", [], steps=[["false"], ["true"]])
        assert code == 1
        exits = [h for h in hops if h.get("kind") == "exit"]
        assert exits and exits[-1].get("exit_code") == 1
    finally:
        link.close()


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
        exits = [h for h in hops if h.get("kind") == "exit"]
        assert exits, hops
        assert exits[-1].get("cause") == "stopped"
    finally:
        link.close()


def test_no_link_at_exit_posts_once_via_http(tmp_path, monkeypatch) -> None:
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
    assert code == 0
    exits = [h for h in hops if h.get("verb") == "tw.event" and h.get("kind") == "exit"]
    assert len(exits) == 1
    assert exits[0].get("exit_code") == 0
    assert exits[0].get("watch_id")


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
    crashes = [h for h in hops if h.get("verb") == "tw.event" and h.get("kind") == "crash"]
    assert len(crashes) == 1
    assert crashes[0].get("cause") == "lost"
    assert crashes[0].get("watch_id") == "tw-deadbeef"
    path = runs_path("tw-lost")
    if path.exists():
        import json
        assert json.loads(path.read_text(encoding="utf-8")) == {}
