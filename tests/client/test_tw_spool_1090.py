# -*- coding: utf-8 -*-
"""Card 1090 step 4: a durable spool replays start before exit."""
from __future__ import annotations

import json
import sys

from agent_coord.client.tw.proc import list_runs, run_argv
from agent_coord.client.tw.spool import append_hop, load_durable


def _home(monkeypatch, tmp_path):
    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)
    monkeypatch.setattr("agent_coord.client.offices.desk_local_file", lambda *a, **k: None)


def _down(*_a, **_k):
    raise OSError("down")


def test_no_sit_spools_start_then_exit(tmp_path, monkeypatch) -> None:
    _home(monkeypatch, tmp_path)
    monkeypatch.setattr("agent_coord.client.tw.proc.open_session", _down)
    monkeypatch.setattr("agent_coord.client.http.mill_http_call", _down)
    code = run_argv(
        "tw-spool",
        [sys.executable, "-c", "import sys; sys.exit(0)"],
    )
    assert code == 0
    kinds = [item["kind"] for item in load_durable("tw-spool")]
    assert kinds == ["start", "exit"]


def test_link_start_replays_once_in_order(tmp_path, monkeypatch) -> None:
    _home(monkeypatch, tmp_path)
    from agent_coord.client.tw.link import serve

    hops: list[dict] = []

    def ok(body):
        hops.append(dict(body))
        return {"ok": True, "result": {"done": "noop"}}

    monkeypatch.setattr("agent_coord.client.http.mill_http_call", ok)
    append_hop("tw-replay", {"watch_id": "tw-a", "kind": "start", "pid": 1})
    append_hop(
        "tw-replay",
        {"watch_id": "tw-a", "kind": "exit", "pid": 1, "exit_code": 0},
    )
    link = serve("tw-replay")
    try:
        assert [item["kind"] for item in hops] == ["start", "exit"]
        assert hops[0]["counts"]["replay"] == 1
        assert load_durable("tw-replay") == []
        hops.clear()
    finally:
        link.close()
    assert load_durable("tw-replay") == []
    again = serve("tw-replay")
    try:
        assert hops == []
    finally:
        again.close()


def test_http_fallback_sends_start_before_exit(tmp_path, monkeypatch) -> None:
    _home(monkeypatch, tmp_path)
    hops: list[dict] = []

    def ok(body):
        hops.append(dict(body))
        return {"ok": True}

    monkeypatch.setattr("agent_coord.client.tw.proc.open_session", _down)
    monkeypatch.setattr("agent_coord.client.http.mill_http_call", ok)
    code = run_argv(
        "tw-order",
        [sys.executable, "-c", "import sys; sys.exit(0)"],
    )
    assert code == 0
    kinds = [item["kind"] for item in hops if item.get("verb") == "tw.event"]
    assert kinds == ["start", "exit"]
    assert load_durable("tw-order") == []


def test_cap_drops_one_watch(tmp_path, monkeypatch, capsys) -> None:
    _home(monkeypatch, tmp_path)
    for index in range(4):
        wid = "tw-old-%s" % index
        append_hop("tw-cap", {"watch_id": wid, "kind": "start", "pid": 1})
        append_hop(
            "tw-cap",
            {"watch_id": wid, "kind": "exit", "pid": 1, "exit_code": 0},
        )
    append_hop("tw-cap", {"watch_id": "tw-new", "kind": "start", "pid": 2})
    append_hop(
        "tw-cap",
        {"watch_id": "tw-new", "kind": "exit", "pid": 2, "exit_code": 0},
    )
    kept = {_watch(item) for item in load_durable("tw-cap")}
    assert "tw-old-0" not in kept
    assert "tw-new" in kept
    assert len(load_durable("tw-cap")) == 8
    err = capsys.readouterr().err
    assert "tw: tw-old-0 dropped; spool cap" in err
    assert "spooled; replays" not in err


def _watch(item: dict) -> str:
    return str(item.get("watch_id") or "")


def test_lost_crash_stays_in_the_spool(tmp_path, monkeypatch) -> None:
    _home(monkeypatch, tmp_path)
    from agent_coord.client.tw.proc import _save, runs_path

    monkeypatch.setattr("agent_coord.client.http.mill_http_call", _down)
    dead = 2147483646
    _save(
        "tw-lost",
        {
            "tw-dead": {
                "pid": dead,
                "argv": ["tool"],
                "stop": False,
                "tw_pid": dead,
            }
        },
    )
    assert list_runs("tw-lost") == []
    rows = load_durable("tw-lost")
    assert len(rows) == 1
    assert rows[0]["kind"] == "crash"
    assert rows[0]["cause"] == "lost"
    path = runs_path("tw-lost")
    if path.exists():
        assert json.loads(path.read_text(encoding="utf-8")) == {}


def test_sit_end_does_not_replay(tmp_path, monkeypatch) -> None:
    _home(monkeypatch, tmp_path)
    from agent_coord.client.tw.link import serve

    hops: list[dict] = []

    def ok(body):
        hops.append(dict(body))
        return {"ok": True}

    monkeypatch.setattr("agent_coord.client.http.mill_http_call", ok)
    link = serve("tw-sit")
    append_hop("tw-sit", {"watch_id": "tw-b", "kind": "start", "pid": 3})
    append_hop(
        "tw-sit",
        {"watch_id": "tw-b", "kind": "exit", "pid": 3, "exit_code": 0},
    )
    link.close()
    assert hops == []
    assert [item["kind"] for item in load_durable("tw-sit")] == ["start", "exit"]
    nxt = serve("tw-sit")
    try:
        assert [item["kind"] for item in hops] == ["start", "exit"]
        assert load_durable("tw-sit") == []
    finally:
        nxt.close()


def test_orphan_exit_is_not_kept(tmp_path, monkeypatch) -> None:
    _home(monkeypatch, tmp_path)
    append_hop("tw-orphan", {"watch_id": "tw-a", "kind": "start", "pid": 1})
    for index in range(7):
        append_hop(
            "tw-orphan",
            {"watch_id": "tw-pad-%s" % index, "kind": "start", "pid": 1},
        )
    append_hop(
        "tw-orphan",
        {"watch_id": "tw-a", "kind": "exit", "pid": 1, "exit_code": 0},
    )
    kept = load_durable("tw-orphan")
    assert all(item["watch_id"] != "tw-a" for item in kept)
    assert kept
    assert all(item["kind"] != "exit" for item in kept)


def test_exit_after_a_cap_drop_is_not_kept(tmp_path, monkeypatch, capsys) -> None:
    _home(monkeypatch, tmp_path)
    append_hop("tw-later", {"watch_id": "tw-a", "kind": "start", "pid": 1})
    for index in range(7):
        append_hop(
            "tw-later",
            {"watch_id": "tw-pad-%s" % index, "kind": "start", "pid": 1},
        )
    append_hop("tw-later", {"watch_id": "tw-extra", "kind": "start", "pid": 1})
    append_hop(
        "tw-later",
        {"watch_id": "tw-a", "kind": "exit", "pid": 1, "exit_code": 0},
    )
    kept = load_durable("tw-later")
    assert all(item["watch_id"] != "tw-a" for item in kept)
    assert all(item["kind"] != "exit" for item in kept)
    err = capsys.readouterr().err
    assert err.count("tw: tw-a dropped; spool cap") == 1


def test_list_and_status_replay_once(tmp_path, monkeypatch) -> None:
    _home(monkeypatch, tmp_path)
    from agent_coord.client.tw.proc import query_status

    hops: list[dict] = []

    def ok(body):
        hops.append(dict(body))
        return {"ok": True, "result": {"done": "noop"}}

    monkeypatch.setattr("agent_coord.client.http.mill_http_call", ok)
    monkeypatch.setattr("agent_coord.client.tw.proc.open_session", _down)
    append_hop("tw-pass", {"watch_id": "tw-d", "kind": "start", "pid": 5})
    assert list_runs("tw-pass") == []
    assert [item["kind"] for item in hops] == ["start"]
    assert hops[0]["counts"]["replay"] == 1
    assert load_durable("tw-pass") == []
    hops.clear()
    append_hop(
        "tw-pass",
        {"watch_id": "tw-d", "kind": "exit", "pid": 5, "exit_code": 0},
    )
    query_status("tw-pass")
    assert [item["kind"] for item in hops] == ["exit"]
    assert load_durable("tw-pass") == []


def test_replay_transport_error_keeps_the_sit(tmp_path, monkeypatch) -> None:
    _home(monkeypatch, tmp_path)
    from agent_coord.client.tw.link import serve

    monkeypatch.setattr("agent_coord.client.http.mill_http_call", _down)
    append_hop("tw-down", {"watch_id": "tw-c", "kind": "start", "pid": 4})
    link = serve("tw-down")
    try:
        assert [item["kind"] for item in load_durable("tw-down")] == ["start"]
    finally:
        link.close()
