# -*- coding: utf-8 -*-
"""Card 1289: tw counts bytes and names the card and the pull on start."""
from __future__ import annotations

import io
import sys
import threading
import time

from agent_coord.client.tw.cli import main
from agent_coord.client.tw.link import Session, serve
from agent_coord.client.tw.outbox import Outbox, _post_body
from agent_coord.client.tw.proc import _argv_bytes, run_argv
from agent_coord.client.tw.protocol import bounded_int


def _home(monkeypatch, tmp_path):
    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)
    monkeypatch.setattr("agent_coord.client.offices.desk_local_file", lambda *a, **k: None)


def _within(fn, seconds=3):
    box: dict = {}

    def run():
        try:
            box["value"] = fn()
        except BaseException as exc:
            box["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(seconds)
    if thread.is_alive():
        raise AssertionError("timed out")
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _wait_kind(hops, kind):
    deadline = time.time() + 5
    while time.time() < deadline:
        if any(item.get("kind") == kind for item in hops):
            return
        time.sleep(0.05)
    raise AssertionError(hops)


def test_bounded_int_drops_a_bad_value() -> None:
    assert bounded_int(0) == 0
    assert bounded_int(1, positive=True) == 1
    assert bounded_int(0, positive=True) is None
    assert bounded_int(True) is None
    assert bounded_int(False, positive=True) is None
    assert bounded_int(-1) is None
    assert bounded_int(1.5) is None
    assert bounded_int("1") is None
    assert bounded_int(2**53) is None
    assert bounded_int(2**53 - 1) == 2**53 - 1


def test_bad_card_flag_exits_before_a_sit(capsys) -> None:
    assert main(["--card", "0", sys.executable, "-c", "import sys; sys.exit(0)"]) == 2
    assert main(["--pr"]) == 2
    assert main(["--card", "no", "cmd"]) == 2
    err = capsys.readouterr().err
    assert "positive integer" in err


def test_hop_forwards_pr_and_bytes_and_drops_a_bool(tmp_path, monkeypatch) -> None:
    _home(monkeypatch, tmp_path)
    hops = []

    def fake_http(body):
        hops.append(dict(body))
        return {"ok": True, "result": {"ok": True}}

    monkeypatch.setattr("agent_coord.client.http.mill_http_call", fake_http)
    link = serve("tw-bytes")
    session = Session(link)
    try:
        got = _within(
            lambda: session.request({
                "type": "event",
                "watch_id": "w-bytes",
                "desk": "tw-bytes",
                "kind": "exit",
                "exit_code": 0,
                "pr": 513,
                "bytes_in": 4,
                "bytes_out": True,
                "stdout": "SECRET",
            })
        )
        assert got["ok"] is True
        assert link.drain() == "empty"
        events = [item for item in hops if item.get("verb") == "tw.event"]
        assert len(events) == 1
        hop = events[0]
        assert hop.get("pr") == 513
        assert hop.get("bytes_in") == 4
        assert "bytes_out" not in hop
        assert "SECRET" not in repr(hop)
    finally:
        session.close()
        link.close()


def test_outbox_round_trip_keeps_the_new_keys(tmp_path) -> None:
    box = Outbox(tmp_path / "desk.hops.sqlite")
    try:
        box.add({
            "watch_id": "tw-row",
            "kind": "exit",
            "exit_code": 0,
            "pr": 0,
            "bytes_in": 8,
            "bytes_out": 3,
        })
        item = box.next_row(set())
        posted = _post_body(item)
        assert posted["bytes_in"] == 8
        assert posted["bytes_out"] == 3
        assert "pr" not in posted
    finally:
        box.close()


def test_run_puts_card_and_pr_on_start_and_bytes_on_exit(tmp_path, monkeypatch) -> None:
    _home(monkeypatch, tmp_path)
    hops = []

    def hop(body):
        hops.append(dict(body))
        return {"ok": True, "result": {"ok": True}}

    monkeypatch.setattr("agent_coord.client.http.mill_http_call", hop)
    link = serve("tw-1289")
    argv = [sys.executable, "-c", "import sys; sys.stdout.write('hi')"]
    try:
        code = run_argv(
            "tw-1289",
            argv,
            card=1289,
            pr=513,
            stdin_stream=io.BytesIO(b"ab"),
        )
        assert code == 0
        _wait_kind(hops, "exit")
        events = [item for item in hops if item.get("verb") == "tw.event"]
        assert [item.get("kind") for item in events] == ["start", "exit"]
        start, done = events
        assert start.get("card") == 1289
        assert start.get("pr") == 513
        assert "bytes_in" not in start
        assert "card" not in done
        assert "pr" not in done
        assert done.get("bytes_in") == _argv_bytes(argv) + 2
        assert done.get("bytes_out") == 2
    finally:
        link.close()
