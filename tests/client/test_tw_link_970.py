# -*- coding: utf-8 -*-
"""Card 970 slice (a): local link, one route, 4572 frames."""
from __future__ import annotations

import ctypes
import socket
import threading
from pathlib import Path

import pytest

from agent_coord.client.route_chain import load_routes, split_cmd
from agent_coord.client.tw.link import Session, serve
from agent_coord.client.tw.protocol import LINE_MAX, MAX_SESSIONS
from agent_coord.client.tw.transport import kind
from agent_coord.client.tw.unix_sock import socket_path
from agent_coord.client.tw.win_pipe import PIPE_REJECT_REMOTE_CLIENTS


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


def test_pipe_module_imports_without_kernel32(monkeypatch) -> None:
    import importlib

    import agent_coord.client.tw.win_pipe as win_pipe

    monkeypatch.delattr(ctypes, "WinDLL", raising=False)
    loaded = importlib.reload(win_pipe)
    assert loaded.PIPE_REJECT_REMOTE_CLIENTS == 0x00000008
    assert loaded._kernel32._lib is None


def test_linux_macos_and_wsl_share_the_unix_transport() -> None:
    assert kind("posix") == "unix"
    assert kind("nt") == "pipe"


def test_local_peer_is_refused_by_mode_or_flag() -> None:
    assert PIPE_REJECT_REMOTE_CLIENTS == 0x00000008
    from agent_coord.client.tw import unix_sock

    src = Path(unix_sock.__file__).read_text(encoding="utf-8")
    assert "0o600" in src
    assert "AF_INET" not in src


def test_connect_opens_the_link(tmp_path, monkeypatch) -> None:
    _home(monkeypatch, tmp_path)
    from agent_coord.client.http import _open_tw_link

    link = _open_tw_link("tw-open")
    assert link is not None
    session = Session(link)
    try:
        got = _within(lambda: session.request(_register("tw:open")))
        assert got["type"] == "reply"
        assert got["ok"] is True
    finally:
        session.close()
        link.close()


def test_register_adds_one_route(tmp_path, monkeypatch) -> None:
    _home(monkeypatch, tmp_path)
    link = serve("tw-reg")
    session = Session(link)
    try:
        got = _within(
            lambda: session.request(
                {"type": "register", "key": "tw:1", "argv": ["tw", "run", "--card", "970"]}
            )
        )
        assert got == {"type": "reply", "ok": True, "msg": "registered"}
        routes = load_routes("tw-reg")
        assert [key for key, _ in routes] == ["tw:1"]
        assert split_cmd(routes[0][1])[:4] == ["tw", "run", "--card", "970"]
    finally:
        session.close()
        link.close()


def test_event_is_accepted_without_writing_doing(tmp_path, monkeypatch) -> None:
    _home(monkeypatch, tmp_path)
    from agent_coord.client.tw import link as linkmod

    assert "mill_transition_put" not in Path(linkmod.__file__).read_text(encoding="utf-8")
    assert "mill_doing_put" not in Path(linkmod.__file__).read_text(encoding="utf-8")
    calls = []
    hops = []
    monkeypatch.setattr(linkmod, "add_route", lambda *args, **kwargs: calls.append(args))
    monkeypatch.setattr(
        "agent_coord.client.http.mill_http_call",
        lambda body: hops.append(dict(body)) or {"ok": True, "result": {"ok": True}},
    )
    link = serve("tw-event")
    session = Session(link)
    try:
        _within(lambda: session.request(_register("tw:event")))
        calls.clear()
        before = list(tmp_path.rglob("*"))
        got = _within(
            lambda: session.request(
                {
                    "type": "event",
                    "watch_id": "w1",
                    "kind": "start",
                    "card": 970,
                    "argv": ["tw", "run"],
                    "title": "secret",
                    "pattern": "*.py",
                }
            )
        )
        assert got["type"] == "reply"
        assert got["ok"] is True
        assert got["watch_id"] == "w1"
        assert got["msg"] == "accepted"
        assert calls == []
        extra = [p for p in tmp_path.rglob("*") if p not in before]
        assert all(".hops.sqlite" in p.name for p in extra)
        assert link.drain() == "empty"
        events = [item for item in hops if item.get("verb") == "tw.event"]
        assert len(events) == 1
        assert events[0]["verb"] == "tw.event"
        assert events[0]["watch_id"] == "w1"
        assert "argv" not in events[0]
        assert "title" not in events[0]
        assert "pattern" not in events[0]
    finally:
        session.close()
        link.close()


def test_event_hop_leaves_stream_and_sample_on_the_desk(tmp_path, monkeypatch) -> None:
    _home(monkeypatch, tmp_path)
    hops = []

    def fake_http(body):
        hops.append(dict(body))
        return {"ok": True, "result": {"ok": True}}

    monkeypatch.setattr("agent_coord.client.http.mill_http_call", fake_http)
    link = serve("tw-nofire")
    session = Session(link)
    try:
        got = _within(
            lambda: session.request({
                "type": "event",
                "watch_id": "w5",
                "desk": "tw-nofire",
                "card": 970,
                "kind": "exit",
                "cause": "exit",
                "exit_code": 3,
                "counts": {"lines": 4},
                "pid": 4242,
                "stdout": "STDOUT-BODY",
                "stderr": "STDERR-BODY",
                "log": "LOG-BODY",
                "sample": {"tree": [{"pid": 4242, "cmd": "SAMPLE-BODY"}]},
            })
        )
        assert got["ok"] is True
        assert link.drain() == "empty"
        events = [item for item in hops if item.get("verb") == "tw.event"]
        assert len(events) == 1
        hop = events[0]
        assert hop == {
            "verb": "tw.event",
            "watch_id": "w5",
            "desk": "tw-nofire",
            "card": 970,
            "kind": "exit",
            "cause": "exit",
            "exit_code": 3,
            "counts": {"lines": 4},
        }
        blob = repr(hop)
        for marker in ("STDOUT-BODY", "STDERR-BODY", "LOG-BODY", "SAMPLE-BODY", "4242"):
            assert marker not in blob
    finally:
        session.close()
        link.close()


def test_stop_is_pushed_to_the_session(tmp_path, monkeypatch) -> None:
    _home(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "agent_coord.client.http.mill_http_call",
        lambda body: {"ok": True, "result": {"ok": True}},
    )
    link = serve("tw-stop")
    session = Session(link)
    try:
        _within(lambda: session.request(_register("tw:stop")))
        _within(
            lambda: session.request({"type": "event", "watch_id": "w9", "kind": "stall"})
        )
        box: dict = {}

        def wait():
            box["msg"] = session.read()

        waiter = threading.Thread(target=wait, daemon=True)
        waiter.start()
        assert link.stop("w9", "desk") is True
        waiter.join(3)
        assert not waiter.is_alive()
        assert box["msg"] == {"type": "stop", "watch_id": "w9", "reason": "desk"}
    finally:
        session.close()
        link.close()


def test_oversize_line_keeps_the_session(tmp_path, monkeypatch) -> None:
    _home(monkeypatch, tmp_path)
    link = serve("tw-over")
    session = Session(link)
    try:
        session.send_raw(b"{" + b"x" * (LINE_MAX + 200) + b"\n")
        err = _within(session.read)
        assert err == {"type": "error", "code": "line_too_long", "max": LINE_MAX}
        got = _within(lambda: session.request(_register("tw:over")))
        assert got["ok"] is True
    finally:
        session.close()
        link.close()


def test_bad_line_keeps_the_session(tmp_path, monkeypatch) -> None:
    _home(monkeypatch, tmp_path)
    link = serve("tw-bad")
    session = Session(link)
    try:
        session.send_raw(b"not-json\n")
        bad = _within(session.read)
        assert bad["type"] == "reply"
        assert bad["ok"] is False
        got = _within(lambda: session.request(_register("tw:bad")))
        assert got["ok"] is True
    finally:
        session.close()
        link.close()


def test_two_registers_at_once(tmp_path, monkeypatch) -> None:
    _home(monkeypatch, tmp_path)
    link = serve("tw-two")
    first = Session(link)
    second = Session(link)
    box: dict = {}

    def run(name, session, key):
        try:
            box[name] = session.request(_register(key))
        except BaseException as exc:
            box[name] = exc

    left = threading.Thread(target=run, args=("a", first, "tw:a"), daemon=True)
    right = threading.Thread(target=run, args=("b", second, "tw:b"), daemon=True)
    try:
        left.start()
        right.start()
        left.join(3)
        right.join(3)
        assert not left.is_alive()
        assert not right.is_alive()
        assert box["a"]["ok"] is True
        assert box["b"]["ok"] is True
        assert {key for key, _ in load_routes("tw-two")} == {"tw:a", "tw:b"}
    finally:
        first.close()
        second.close()
        link.close()


def test_ninth_session_is_refused(tmp_path, monkeypatch) -> None:
    _home(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "agent_coord.client.http.mill_http_call",
        lambda body: {"ok": True, "result": {"ok": True}},
    )
    link = serve("tw-cap")
    held = []
    try:
        for index in range(MAX_SESSIONS):
            session = Session(link)
            held.append(session)
            got = _within(lambda session=session, index=index: session.request(_register("tw:%s" % index)))
            assert got["ok"] is True
        extra = Session(link)
        held.append(extra)
        refused = _within(lambda: extra.request(_register("tw:extra")))
        assert refused["type"] == "reply"
        assert refused["ok"] is False
        assert refused["msg"] == "cap"
        assert refused["code"] == "cap"
        keys = [key for key, _ in load_routes("tw-cap")]
        assert "tw:extra" not in keys
        assert len(keys) == MAX_SESSIONS
        still = _within(
            lambda: held[0].request({"type": "event", "watch_id": "alive", "kind": "resume"})
        )
        assert still["ok"] is True
        assert "cap" in link.marks
    finally:
        for session in held:
            session.close()
        link.close()


def test_pointer_is_not_printed(tmp_path, monkeypatch, capsys) -> None:
    _home(monkeypatch, tmp_path)
    from agent_coord.client.tw.link import pointer_path

    link = serve("tw-ptr")
    path = pointer_path("tw-ptr")
    text = path.read_text(encoding="utf-8").strip()
    out = capsys.readouterr().out
    try:
        assert text.startswith(kind() + " ")
        assert path.name.endswith(".tw")
        assert text not in out
        assert "mill-tw-" not in out
    finally:
        link.close()
        assert not path.exists()


def test_unix_path_is_local_and_not_tcp(tmp_path) -> None:
    path = socket_path(tmp_path, "grok-tui")
    assert path.name == "grok-tui.tw.sock"
    assert ":" not in path.name


def test_unix_listen_requires_the_os_socket(tmp_path) -> None:
    if hasattr(socket, "AF_UNIX"):
        pytest.skip("this OS has a unix socket")
    from agent_coord.client.tw.unix_sock import Unix

    with pytest.raises(OSError):
        Unix("grok-tui", tmp_path).serve(threading.Event(), lambda _c: None, threading.Event())


def _register(key: str) -> dict:
    return {"type": "register", "key": key, "argv": ["tw", "run", "echo"]}
