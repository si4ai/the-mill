"""F144 (wake-lease): one woken run at a time per desk, server side.

Seen: the platform starts one cold run per webhook POST, and the runs overlap.
Every connect sync cleared the wake window (gate_clear), and a routine desk
connects for a second or two per shell call, so the woken run's first read
dropped the window and the next letter POSTed again: a storm of overlapping runs.

Now a POST takes a wake lease for that desk. A connect sync does not end it.
While it is held, new items wait in the push queue and post nothing. The run
ends it with `mill wake-done [--note TEXT]`; then the wall sends exactly one trailing
wake carrying pending_count (distinct items held back) and the run's note. A run
that never says done (a crash, or a client older than the verb) loses the lease
after wake_lease_s (default 900 s): the window-end timer sends the one trailing
wake, and the next item after that time POSTs again. Design credit: the
grokbot-wake-relay repo (queue until done, lease timeout, one batched wake).
"""
from __future__ import annotations

import importlib.util
import json
from unittest.mock import MagicMock, patch

import pytest

from agent_coord.server import push, wake
from tests.server.test_desk_webhook_618 import _Queue, _Resp
from tests.server.webhook_fixtures import arm


@pytest.fixture
def office(monkeypatch):
    """Armed desks, an in-memory queue, a fake receiver, a settable clock and
    captured window-end timers. No network, no threads."""
    arm(monkeypatch)
    q = _Queue()
    q.install(monkeypatch)
    monkeypatch.setattr(push.HUB, "rooms", {})
    monkeypatch.setattr(wake, "_NOTE", {}, raising=False)
    clock = {"t": 1000.0}
    monkeypatch.setattr("time.monotonic", lambda: clock["t"])
    timers: list = []
    monkeypatch.setattr(wake, "_schedule", lambda delay, fn, *args: timers.append((delay, fn, args)))
    monkeypatch.setattr(wake, "_book", lambda: MagicMock())
    lines: list[str] = []
    monkeypatch.setattr(push, "_bc_log", lines.append)
    bodies: list[dict] = []

    def receive(req, timeout=0):
        bodies.append(json.loads(req.data.decode("utf-8")))
        return _Resp()

    with patch("agent_coord.server.wake._open", receive):
        yield {"q": q, "clock": clock, "timers": timers, "lines": lines, "bodies": bodies, "cn": MagicMock()}


def _letter(o, n: int, desk: str = "away") -> str:
    return push.emit(o["cn"], desk, "mail", {"id": n, "body": f"letter {n}", "sender": "s"})


def _posts(o, desk: str = "away") -> list[dict]:
    return [b for b in o["bodies"] if b.get("desk") == desk]


def test_five_letters_post_once_then_done_sends_one_trailing_wake(office) -> None:
    for n in range(1, 6):
        _letter(office, n)
        office["clock"]["t"] += 1
    assert len(_posts(office)) == 1
    assert _posts(office)[0]["wake"]["pending_count"] == 0
    assert wake.lease_done(office["cn"], "away") == "sent"
    got = _posts(office)
    assert len(got) == 2
    assert got[1]["wake"]["pending_count"] == 4
    assert got[1]["id"] == 5  # the latest held-back item
    assert any("wake=coalesced reason=lease" in ln for ln in office["lines"])
    assert any(ln.startswith("webhook desk=away wake=done ") and "queued=4" in ln for ln in office["lines"])
    assert office["lines"][-1].endswith("wake=sent status=200 reason=trailing")


def test_a_connect_sync_does_not_end_the_lease(office) -> None:
    """The incident: wake on letter A, the run's short connect sync, letter B 10 s later."""
    _letter(office, 1)
    frame = push.connect_sync_frame(office["cn"], "away")
    assert [r["id"] for r in frame["sync"]] == [1]
    office["clock"]["t"] += 10
    _letter(office, 2)
    assert len(_posts(office)) == 1  # B waits in the queue; no second cold run


def test_no_done_from_an_old_client_the_lease_times_out(office) -> None:
    """A 0.7.18-shaped run: it connects and reads, never calls done. The wall
    still sends one trailing wake at lease end, and is not wedged after it."""
    _letter(office, 1)
    push.connect_sync_frame(office["cn"], "away")
    office["clock"]["t"] += 5
    _letter(office, 2)
    _letter(office, 3)
    assert len(_posts(office)) == 1
    assert len(office["timers"]) == 1
    delay, fn, args = office["timers"][0]
    assert delay == pytest.approx(wake.lease_s() - 5)
    office["clock"]["t"] += delay
    assert fn(*args) == "sent"
    got = _posts(office)
    assert len(got) == 2 and got[1]["wake"]["pending_count"] == 2
    assert office["lines"][-1].endswith("reason=lease-expired")
    # The trailing wake took a fresh lease; after it times out, a new letter posts at once.
    office["clock"]["t"] += wake.lease_s() + 1
    _letter(office, 4)
    assert len(_posts(office)) == 3


def test_lease_timeout_with_nothing_held_lets_the_next_letter_post(office) -> None:
    _letter(office, 1)
    office["clock"]["t"] += wake.lease_s() + 1
    _letter(office, 2)
    assert len(_posts(office)) == 2
    assert office["timers"] == []


def test_done_note_rides_the_trailing_wake(office) -> None:
    _letter(office, 1)
    _letter(office, 2)
    assert wake.lease_done(office["cn"], "away", note="answered 1; 2 is next") == "sent"
    got = _posts(office)
    assert got[1]["wake"]["last_note"] == "answered 1; 2 is next"
    assert got[0]["wake"]["last_note"] is None


def test_done_with_nothing_held_posts_nothing_and_frees_the_desk(office) -> None:
    _letter(office, 1)
    assert wake.lease_done(office["cn"], "away", note="all handled") == "none"
    assert len(_posts(office)) == 1
    _letter(office, 2)
    got = _posts(office)
    assert len(got) == 2  # the lease ended: the next letter posts at once
    assert got[1]["wake"]["last_note"] == "all handled"  # the note waits for the next wake
    assert got[1]["wake"]["pending_count"] == 0


def test_done_after_the_run_read_every_held_item_sends_nothing(office) -> None:
    _letter(office, 1)
    _letter(office, 2)
    push.connect_sync_frame(office["cn"], "away")  # the run read letter 2 itself
    assert wake.lease_done(office["cn"], "away") == "none"
    assert len(_posts(office)) == 1
    assert any("wake=none reason=drained" in ln for ln in office["lines"])


def test_a_repeated_item_counts_once(office) -> None:
    _letter(office, 1)
    _letter(office, 2)
    _letter(office, 2)
    _letter(office, 3)
    assert wake.lease_done(office["cn"], "away") == "sent"
    assert _posts(office)[1]["wake"]["pending_count"] == 2


def test_a_second_done_is_a_no_op(office) -> None:
    _letter(office, 1)
    _letter(office, 2)
    assert wake.lease_done(office["cn"], "away") == "sent"
    # The trailing wake opened run 2's lease; nothing new is held, so its done sends nothing.
    assert wake.lease_done(office["cn"], "away") == "none"
    assert wake.lease_done(office["cn"], "away") == "none"
    assert len(_posts(office)) == 2


def test_two_seats_hold_their_own_leases(office) -> None:
    _letter(office, 1, desk="away")
    _letter(office, 2, desk="other")
    _letter(office, 3, desk="away")
    assert len(_posts(office, "away")) == 1
    assert len(_posts(office, "other")) == 1
    assert wake.lease_done(office["cn"], "other") == "none"
    assert wake.lease_done(office["cn"], "away") == "sent"


def test_two_offices_hold_their_own_leases() -> None:
    """Each office is its own wall process with its own book (records.db pool),
    so each holds its own lease table: a seat in two offices has two leases."""
    path = wake.__file__
    a = importlib.util.module_from_spec(importlib.util.spec_from_file_location("wake_office_a", path))
    b = importlib.util.module_from_spec(importlib.util.spec_from_file_location("wake_office_b", path))
    a.__spec__.loader.exec_module(a)
    b.__spec__.loader.exec_module(b)
    assert a._gate_take("desk", 1.0) is True
    assert a._gate_open("desk", 2.0) is False
    assert b._gate_open("desk", 2.0) is True


def test_lease_length_is_configurable(monkeypatch) -> None:
    monkeypatch.delenv("AGENT_COORD_WAKE_LEASE_S", raising=False)
    monkeypatch.setattr("agent_coord.config.settings", lambda: {})
    assert wake.lease_s() == 900.0
    monkeypatch.setattr("agent_coord.config.settings", lambda: {"wake_lease_s": "60"})
    assert wake.lease_s() == 60.0
    monkeypatch.setattr("agent_coord.config.settings", lambda: {"wake_lease_s": "junk"})
    assert wake.lease_s() == 900.0


def test_done_rpc_ends_the_callers_own_lease(monkeypatch) -> None:
    from agent_coord.server.api.mill import rpc

    seen: list = []
    monkeypatch.setattr(wake, "lease_done", lambda cn, desk, note="", lease="": seen.append((desk, note)) or "none")
    book = MagicMock()
    out = rpc.HANDLERS["wake-done"](book, {"verb": "wake-done", "note": "wrapped up", "desk": "someone-else"}, "the-mill", "away")
    assert seen == [("away", "wrapped up")]
    assert out["ok"] is True and out["wake"] == "none"


def test_mill_wake_done_sends_the_note() -> None:
    from agent_coord.__main__ import _build_parser
    from agent_coord.client.outbound import COMMANDS, body_from_args

    args = _build_parser().parse_args(["wake-done", "--note", "handled 1"])
    with patch("agent_coord.client.tokens.resolve_desk_owner", lambda _x: "away"):
        body = body_from_args(args)
    assert body["verb"] == "wake-done" and body["note"] == "handled 1"
    assert "wake-done" in COMMANDS


def test_mill_wake_done_takes_no_card() -> None:
    from agent_coord.__main__ import _build_parser

    with pytest.raises(SystemExit):
        _build_parser().parse_args(["wake-done", "the-mill", "some-need"])
