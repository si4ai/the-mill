"""#625 every webhook wake outcome logs one line per desk, on the letter path
and the hint fanout path alike: sent with the HTTP status, coalesced or
skipped with the reason, fail with the status or error type. Never the URL
path or the key. Row F72 (wake-log)."""
from __future__ import annotations

import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from agent_coord.server import push, wake
from tests.server.test_desk_webhook_618 import _hint, _Queue, _Resp
from tests.server.webhook_fixtures import HOOK_HOST, HOOK_KEY, arm


@pytest.fixture
def logged(monkeypatch):
    lines: list[str] = []
    monkeypatch.setattr(push, "_bc_log", lines.append)
    arm(monkeypatch)
    _Queue().install(monkeypatch)
    monkeypatch.setattr(push.HUB, "rooms", {})
    return lines


def _hooks(lines):
    out = [ln for ln in lines if ln.startswith("webhook ")]
    for ln in out:
        assert "/automations/" not in ln and HOOK_KEY not in ln and HOOK_HOST not in ln
    return out


def _ok(req, timeout=0):
    return _Resp()


def test_a_letter_logs_sent_with_status(logged):
    with patch("agent_coord.server.wake._open", _ok):
        push.emit(MagicMock(), "away", "mail", {"id": 6250})
    assert _hooks(logged) == ["webhook desk=away kind=mail id=6250 wake=sent status=200"]


def test_a_second_letter_logs_coalesced_with_the_reason(logged):
    with patch("agent_coord.server.wake._open", _ok):
        push.emit(MagicMock(), "away", "mail", {"id": 6251})
        push.emit(MagicMock(), "away", "mail", {"id": 6252})
    assert _hooks(logged)[1] == "webhook desk=away kind=mail id=6252 wake=coalesced reason=lease"


def test_hints_log_one_line_each_on_the_fanout_path(logged):
    with patch("agent_coord.server.wake._open", _ok):
        _hint(MagicMock(), 6253)
        _hint(MagicMock(), 6254)
    assert _hooks(logged) == [
        f"webhook desk=away type=todo id=6253 wake=sent status=200",
        "webhook desk=away type=todo id=6254 wake=coalesced reason=lease",
    ]


def test_a_failed_post_logs_one_fail_line_with_the_status(logged):
    def no(req, timeout=0):
        raise urllib.error.HTTPError(req.full_url, 503, "busy", {}, None)

    with patch("agent_coord.server.wake._open", no):
        push.emit(MagicMock(), "away", "mail", {"id": 6255})  # carries idem: one retry, still one line
    assert _hooks(logged) == [f"webhook desk=away kind=mail id=6255 wake=fail status=503"]


def test_an_unreachable_host_logs_the_error_type(logged):
    def down(req, timeout=0):
        raise OSError("down")

    with patch("agent_coord.server.wake._open", down):
        _hint(MagicMock(), 6256)
    assert _hooks(logged) == [f"webhook desk=away type=todo id=6256 wake=fail err=OSError"]


def test_a_refused_url_logs_skipped_with_the_reason(logged, monkeypatch):
    monkeypatch.setattr(
        "agent_coord.server.records.join.wake_target",
        lambda cn, desk: ("https://elsewhere.example.com/automations/webhook/x", HOOK_KEY),
    )
    push.emit(MagicMock(), "away", "mail", {"id": 6257})
    assert _hooks(logged) == ["webhook desk=away kind=mail id=6257 wake=skipped reason=not-allowed"]


def test_a_host_that_is_not_public_logs_skipped(logged, monkeypatch):
    monkeypatch.setattr(wake, "public_host", lambda host: False)
    _hint(MagicMock(), 6258)
    assert _hooks(logged) == [f"webhook desk=away type=todo id=6258 wake=skipped reason=not-public"]


def test_a_desk_that_is_not_armed_logs_nothing(logged, monkeypatch):
    monkeypatch.setattr("agent_coord.server.records.join.wake_target", lambda cn, desk: None)
    push.emit(MagicMock(), "away", "mail", {"id": 6259})
    assert _hooks(logged) == []
