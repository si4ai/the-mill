"""card 827: a failed desk wake retries off the request path.

a 503 then a 200 still wakes the desk, on the same idempotency key and the same
lease. a 401 or a 404 does not retry. a connect that drains the queue stops the
retry. a newer wake that succeeds stops the older retry. the wait doubles from
5s, never passes 10 min, and stops at about 1 h.
"""
from __future__ import annotations

import json
import urllib.error

from agent_coord.server import push, wake
from tests.server.test_desk_webhook_618 import _Queue, _Resp
from tests.server.webhook_fixtures import arm


def _hooks(lines: list[str]) -> list[str]:
    return [ln for ln in lines if ln.startswith("webhook ")]


def _arrange(monkeypatch, opener, *, roll: float = 1.0):
    lines: list[str] = []
    scheduled: list[tuple] = []
    monkeypatch.setattr(push, "_bc_log", lines.append)
    arm(monkeypatch)
    queue = _Queue()
    queue.install(monkeypatch)
    monkeypatch.setattr(push.HUB, "rooms", {})
    monkeypatch.setattr(wake, "_book", lambda: object())
    monkeypatch.setattr(wake, "_roll", lambda: roll, raising=False)

    def capture(delay, fn, *args):
        scheduled.append((float(delay), fn, args))

    monkeypatch.setattr(wake, "_schedule", capture)
    return lines, queue, scheduled, opener


def _emit(monkeypatch, opener, mail_id: int, *, roll: float = 1.0):
    lines, queue, scheduled, _opener = _arrange(monkeypatch, opener, roll=roll)
    monkeypatch.setattr(wake, "_open", opener)
    push.emit(object(), "away", "mail", {"id": mail_id})
    return lines, queue, scheduled


def _run(scheduled: list[tuple]) -> None:
    delay, fn, args = scheduled.pop(0)
    fn(*args)


def _posted(opener) -> list[dict]:
    return [json.loads(req.data.decode()) for req in opener.posts]


class _Opener:
    def __init__(self, codes: list[int]):
        self.codes = list(codes)
        self.posts: list = []

    def __call__(self, req, timeout=0):
        self.posts.append(req)
        code = self.codes.pop(0) if self.codes else 503
        if code < 200 or code > 299:
            raise urllib.error.HTTPError(req.full_url, code, "busy", {}, None)
        return _Resp()


def test_503_then_200_wakes_on_the_same_key(monkeypatch) -> None:
    opener = _Opener([503, 200])
    lines, _queue, scheduled = _emit(monkeypatch, opener, 8271)
    assert len(opener.posts) == 1
    assert scheduled, "the retry waits off the request"
    first = _posted(opener)[0]
    assert first["idem"]
    _run(scheduled)
    assert len(opener.posts) == 2
    second = _posted(opener)[1]
    assert second["idem"] == first["idem"]
    assert second["wake"]["lease"] == first["wake"]["lease"]
    assert any("wake=sent" in ln and "status=200" in ln for ln in _hooks(lines))


def test_401_and_404_do_not_retry(monkeypatch) -> None:
    for code, mail_id in ((401, 8272), (404, 8273)):
        opener = _Opener([code, 200])
        lines, _queue, scheduled = _emit(monkeypatch, opener, mail_id)
        assert len(opener.posts) == 1
        assert scheduled == []
        assert any(f"status={code}" in ln for ln in _hooks(lines))
        assert not any("retry-exhausted" in ln for ln in _hooks(lines))


def test_a_drained_queue_stops_the_retry(monkeypatch) -> None:
    opener = _Opener([503, 200])
    lines, queue, scheduled = _emit(monkeypatch, opener, 8274)
    assert len(opener.posts) == 1 and scheduled
    queue.rows.clear()
    _run(scheduled)
    assert len(opener.posts) == 1
    assert not any("retry-exhausted" in ln for ln in _hooks(lines))


def test_a_newer_success_stops_the_older_retry(monkeypatch) -> None:
    opener = _Opener([503, 200, 200])
    lines, _queue, scheduled = _emit(monkeypatch, opener, 8275)
    assert len(opener.posts) == 1 and scheduled
    older = scheduled.pop(0)
    wake.gate_clear("away")
    push.emit(object(), "away", "mail", {"id": 8276})
    assert len(opener.posts) == 2
    older[1](*older[2])
    assert len(opener.posts) == 2
    assert any("wake=sent" in ln and "status=200" in ln for ln in _hooks(lines))


def test_backoff_stays_inside_the_cap_and_the_hour(monkeypatch) -> None:
    assert wake.retry_delay(1, 1.0) == 5.0
    assert wake.retry_delay(2, 1.0) == 10.0
    assert wake.retry_delay(20, 1.0) == 600.0
    assert wake.retry_delay(3, 0.0) == 0.0
    opener = _Opener([503] * 80)
    lines, _queue, scheduled = _emit(monkeypatch, opener, 8277, roll=1.0)
    waits: list[float] = []
    guard = 0
    while scheduled and guard < 80:
        guard += 1
        delay, fn, args = scheduled.pop(0)
        assert 0 <= delay <= 600.0
        waits.append(delay)
        fn(*args)
    assert waits
    assert waits[0] == 5.0
    assert sum(waits) <= 3600.0
    assert sum(waits) >= 3600.0 - 600.0
    assert sum(1 for ln in _hooks(lines) if "retry-exhausted" in ln) == 1
    assert any("retry-exhausted" in ln and "attempts=" in ln and "status=503" in ln for ln in _hooks(lines))
