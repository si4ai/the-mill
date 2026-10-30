# -*- coding: utf-8 -*-
"""#838 a desk's webhook that keeps failing is seen. Regression row F128 (webhook-fail-seen).

Seen: the builder desk's webhook answered 400 to every wake for 37 hours
(168 in a row, same URL, key and body shape as the 200s before and after). The
only trace was a host log line `wake=fail status=400`: the receiver's answer was
dropped, the desk's connect still said `webhook armed`, and no one was told.

Now the fail line carries the receiver's short reason (no URL, host path or key),
a desk whose wakes fail FAIL_ALERT_N times in a row gets one Admin letter for
that run, the desk's connect sync wake line says the webhook is failing, and the
first 2xx clears it.
"""
from __future__ import annotations

import io
import json
import re
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from agent_coord.server import push, wake
from tests.server.webhook_fixtures import HOOK_HOST, HOOK_KEY, HOOK_URL, arm


class _Ok:
    status = 200

    def read(self, _n: int = 0) -> bytes:
        return b""

    def __enter__(self):
        return self

    def __exit__(self, *_a) -> bool:
        return False


def _answer(status: int, body: bytes):
    def fn(req, timeout=0):
        if status < 300:
            return _Ok()
        raise urllib.error.HTTPError(HOOK_URL, status, "Bad Request", {}, io.BytesIO(body))
    return fn


@pytest.fixture
def world(monkeypatch):
    arm(monkeypatch)
    monkeypatch.setattr(wake, "_FAILS", {}, raising=False)
    lines: list[str] = []
    monkeypatch.setattr("agent_coord.server.push._bc_log", lambda line: lines.append(line))
    alerts: list[str] = []
    monkeypatch.setattr("agent_coord.server.push.mill_admin_alert", lambda cn, text, command="": alerts.append(text))
    monkeypatch.setattr("agent_coord.server.records.join.wake_state",
                        lambda cn, desk: {"armed": True, "host": HOOK_HOST, "wake_on": "addressed"})
    return lines, alerts


def _wake(n: int, desk: str = "away") -> str:
    wake.gate_clear(desk)  # one wake per call; the window is #618's own test
    return wake.post_desk(MagicMock(), desk, {"kind": "mail", "id": n, "idem": f"letter:{n}:{desk}"}, hint_id=n)


def test_the_fail_line_carries_the_receivers_reason_without_url_or_key(world) -> None:
    lines, _ = world
    said = json.dumps({"error": f"key {HOOK_KEY} not accepted for {HOOK_URL}"}).encode()
    with patch("agent_coord.server.wake._open", _answer(400, said)):
        assert _wake(8380) == "error"
    fail = [x for x in lines if "wake=fail" in x]
    assert len(fail) == 1 and "status=400" in fail[0]
    assert 'why="key' in fail[0] and "not accepted" in fail[0]
    assert HOOK_KEY not in fail[0] and "/automations/webhook/" not in fail[0]


def test_a_failing_run_alerts_admin_once_and_the_desk_sees_it(world) -> None:
    lines, alerts = world
    said = b'{"message": "automation is paused"}'
    with patch("agent_coord.server.wake._open", _answer(400, said)):
        for n in range(wake.FAIL_ALERT_N - 1):
            _wake(8381 + n)
        assert alerts == []
        _wake(8390)
        assert len(alerts) == 1
        a = alerts[0]
        assert "away" in a and f"{wake.FAIL_ALERT_N} in a row" in a and "400" in a and "automation is paused" in a
        assert HOOK_KEY not in a and "/automations/webhook/" not in a
        _wake(8391)
        assert len(alerts) == 1  # one letter per failing run
    line = push.wake_line(MagicMock(), "away")
    assert line.startswith(f"webhook armed (host {HOOK_HOST}")
    assert f"failing: {wake.FAIL_ALERT_N + 1} wakes in a row" in line and "400" in line
    assert "mill connect" in line
    assert any("failing" in x and "desk=away" in x for x in lines)


def test_a_2xx_clears_the_run_and_a_new_run_alerts_again(world) -> None:
    _, alerts = world
    with patch("agent_coord.server.wake._open", _answer(400, b"no")):
        for n in range(wake.FAIL_ALERT_N):
            _wake(8400 + n)
    assert len(alerts) == 1
    with patch("agent_coord.server.wake._open", _answer(200, b"")):
        assert _wake(8410) == "sent"
    assert "failing" not in push.wake_line(MagicMock(), "away")
    with patch("agent_coord.server.wake._open", _answer(400, b"no")):
        for n in range(wake.FAIL_ALERT_N):
            _wake(8420 + n)
    assert len(alerts) == 2


def test_other_desks_are_not_marked(world) -> None:
    with patch("agent_coord.server.wake._open", _answer(400, b"no")):
        for n in range(wake.FAIL_ALERT_N):
            _wake(8430 + n, desk="away")
    assert "failing" in push.wake_line(MagicMock(), "away")
    assert "failing" not in push.wake_line(MagicMock(), "other")


def test_an_echoed_path_and_query_are_removed_and_the_reason_is_capped(world) -> None:
    lines, _ = world
    path = "/automations/webhook/fixture-routine"
    said = json.dumps({"error": {"message": f"unknown routine {path}?k={HOOK_KEY} " + "x" * 400}}).encode()
    with patch("agent_coord.server.wake._open", _answer(400, said)):
        _wake(8440)
    fail = [x for x in lines if "wake=fail" in x][0]
    why = fail.split('why="', 1)[1].rsplit('"', 1)[0]
    assert "unknown routine" in why and len(why) <= wake.WHY_MAX
    assert path not in fail and HOOK_KEY not in fail and "fixture-routine" not in fail


def test_a_non_raising_non_2xx_answer_keeps_its_reason(world) -> None:
    lines, _ = world

    class _Refused(_Ok):
        status = 409

        def read(self, _n: int = 0) -> bytes:
            return b'{"detail": "run already active"}'

    with patch("agent_coord.server.wake._open", lambda req, timeout=0: _Refused()):
        assert _wake(8450) == "error"
    fail = [x for x in lines if "wake=fail" in x][0]
    assert "status=409" in fail and 'why="run already active"' in fail


def test_no_answer_counts_toward_the_run(world) -> None:
    _, alerts = world

    def down(req, timeout=0):
        raise urllib.error.URLError("timed out")

    with patch("agent_coord.server.wake._open", down):
        for n in range(wake.FAIL_ALERT_N):
            _wake(8460 + n)
    assert len(alerts) == 1 and "URLError" in alerts[0]
    line = push.wake_line(MagicMock(), "away")
    assert f"failing: {wake.FAIL_ALERT_N} wakes in a row" in line and "last URLError" in line


def test_one_failed_wake_reads_singular_and_since_is_clean(world) -> None:
    lines, _ = world
    with patch("agent_coord.server.wake._open", _answer(400, b"no")):
        for n in range(wake.FAIL_ALERT_N):
            _wake(8470 + n)
    run = [x for x in lines if "failing n=" in x][0]
    assert re.search(r"since=\d{4}-\d\d-\d\dT\d\d:\d\dZ$", run)
    wake._FAILS["away"]["n"] = 1
    assert "failing: 1 wake in a row" in push.wake_line(MagicMock(), "away")
