"""A timed-out command names itself and reuses its id on the next try (#137)."""
from __future__ import annotations

import threading

from agent_coord.client import ws as ws_cli
from agent_coord.server.api.mill import rpc


def test_timeout_message_names_the_command_and_id():
    text = ws_cli.rpc_timeout_error("send", "abc-1")
    assert text == (
        "ws rpc: no reply in 30s for send (id abc-1); "
        "it may have applied - check with mill inbox / mill todo before retrying"
    )
    text.encode("ascii")


def test_reply_timeout_points_at_mail_thread():
    text = ws_cli.rpc_timeout_error("reply", "abc-1", {"mail_id": 1269})
    assert "mill mail-thread 1269" in text
    assert "mill inbox" not in text
    assert ws_cli.rpc_timeout_error("reply", "abc-1", {}).endswith(
        "check with mill mail-thread <root> before retrying"
    )
    text.encode("ascii")


def test_late_reply_matches_the_request_id():
    late: dict = {}
    ws_cli.stash_rpc_reply(late, {"id": "abc", "ok": True, "result": {"id": 4}})
    assert ws_cli.pop_rpc_reply(late, "other") is None
    got = ws_cli.pop_rpc_reply(late, "abc")
    assert got is not None and got["ok"] is True
    assert ws_cli.pop_rpc_reply(late, "abc") is None


def test_retry_id_is_reused_then_cleared(monkeypatch, tmp_path):
    monkeypatch.setenv("TEMP", str(tmp_path))
    monkeypatch.setenv("TMP", str(tmp_path))
    args = {"project": "the-mill", "body": "hello"}
    assert ws_cli.load_retry_id("send", args) == ""
    ws_cli.save_retry_id("send", args, "same-id")
    assert ws_cli.load_retry_id("send", args) == "same-id"
    assert ws_cli.load_retry_id("todo", args) == ""
    ws_cli.clear_retry_id("send", args)
    assert ws_cli.load_retry_id("send", args) == ""


def test_server_returns_the_first_result_for_a_repeated_id():
    assert rpc.rpc_claim("grok-tui", "req-1") == "owner"
    rpc.rpc_finish("grok-tui", "req-1", {"id": 9})
    hit, cached = rpc.rpc_remembered("grok-tui", "req-1")
    assert hit is True
    assert cached == {"id": 9}
    assert rpc.rpc_claim("grok-tui", "req-1") == "done"


def test_second_caller_waits_until_the_first_finishes():
    assert rpc.rpc_claim("grok-tui", "req-2") == "owner"
    seen: list[str] = []

    def _other() -> None:
        assert rpc.rpc_claim("grok-tui", "req-2") == "wait"
        rpc.rpc_wait("grok-tui", "req-2", 2.0)
        hit, cached = rpc.rpc_remembered("grok-tui", "req-2")
        seen.append("hit" if hit and cached == {"ok": 1} else "miss")

    worker = threading.Thread(target=_other)
    worker.start()
    rpc.rpc_finish("grok-tui", "req-2", {"ok": 1})
    worker.join(2)
    assert seen == ["hit"]


def test_reply_request_id_runs_the_handler_once(monkeypatch):
    from unittest.mock import MagicMock

    calls = {"n": 0}

    def fake(c, body, project, owner):
        calls["n"] += 1
        return {"id": 9, "replied_to": 3}

    monkeypatch.setitem(rpc.HANDLERS, "reply", fake)
    monkeypatch.setattr(rpc, "desk_name", lambda desk: "grok-tui")
    monkeypatch.setattr(rpc, "_note_doing", lambda *a, **k: None)
    body = {"mail_id": 3, "body": "hi"}
    first = rpc.dispatch_ws(MagicMock(), "grok-tui", "reply", body, req_id="req-reply-176")
    second = rpc.dispatch_ws(
        MagicMock(), "grok-tui", "reply", dict(body), req_id="req-reply-176"
    )
    assert calls["n"] == 1
    assert second == first
