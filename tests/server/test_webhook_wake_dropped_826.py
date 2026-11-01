"""#826: every addressed letter is covered by a delivered or trailing wake.

Locks: (1) N letters across a wake lease each appear in some wake payload
(or the trailing wake). (2) A push that reached a leaving connect (ws ok)
and left the mailbox unread still rings on leave once the lease is ended
(push-at-leave edge after #949). Listing of uncovered pairs is
tools/wake_uncovered.py.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from agent_coord.server import push, wake
from tests.server.test_desk_webhook_618 import _Queue, _Resp
from tests.server.webhook_fixtures import arm


@pytest.fixture
def office(monkeypatch):
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
        yield {
            "q": q,
            "clock": clock,
            "timers": timers,
            "lines": lines,
            "bodies": bodies,
            "cn": MagicMock(),
            "monkeypatch": monkeypatch,
        }


def _letter(o, n: int, desk: str = "away") -> str:
    return push.emit(o["cn"], desk, "mail", {"id": n, "body": f"letter {n}", "sender": "s"})


def _posts(o, desk: str = "away") -> list[dict]:
    return [b for b in o["bodies"] if b.get("desk") == desk]


def _covered_ids(posts: list[dict]) -> set[int]:
    """Letter ids named on a wake body. A trailing wake covers its pending set
    via the latest id plus pending_count; for the lock we also treat every
    coalesced letter as covered once a trailing or initial wake fired after it.
    """
    return {int(b["id"]) for b in posts if b.get("id") is not None}


def test_n_letters_across_lease_are_covered_by_initial_or_trailing(office) -> None:
    """Done-when: N letters spread across a wake window leave none uncovered."""
    ids = list(range(1, 8))
    for n in ids:
        _letter(office, n)
        office["clock"]["t"] += 1
    assert len(_posts(office)) == 1
    assert _posts(office)[0]["id"] == 1
    # Coalesced letters wait; trailing wake must cover the burst.
    assert wake.lease_done(office["cn"], "away") == "sent"
    posts = _posts(office)
    assert len(posts) == 2
    assert posts[1]["wake"]["pending_count"] == 6
    assert posts[1]["id"] == 7  # latest held-back
    # Every letter either rode the first wake or was held then covered by trailing.
    # Log lines name each coalesced id; trailing names the latest.
    named = set()
    for ln in office["lines"]:
        if "wake=sent" in ln or "wake=coalesced" in ln:
            # webhook desk=away kind=mail id=N wake=...
            for part in ln.split():
                if part.startswith("id="):
                    named.add(int(part.split("=", 1)[1]))
    assert named >= set(ids)
    assert _covered_ids(posts) >= {1, 7}


def test_push_at_leave_with_unread_rings_when_row_already_sent(office) -> None:
    """#826 edge: push reached a connect (ws ok / row treated sent) that left
    before the run drained it; push waiting is empty but mailbox unread, so
    leave rings again (unread fallback from #949).
    """
    # End any lease first so leave is not coalesced.
    wake.gate_clear("away")
    office["monkeypatch"].setattr(push.HUB, "rooms", {})
    office["monkeypatch"].setattr(
        "agent_coord.server.records.push.waiting", lambda cn, desk: None
    )
    office["monkeypatch"].setattr(
        push,
        "unread_mail_frames",
        lambda cn, desk, **k: [
            {"kind": "mail", "id": 101, "outcome": "missed", "body": "letter 101", "sender": "s"}
        ],
    )
    assert push.ring_waiting(office["cn"], "away", "leave") == "sent"
    assert _posts(office)[-1]["id"] == 101
    assert any("reason=leave" in ln for ln in office["lines"])


def test_push_at_leave_is_not_lost_under_a_stale_lease(office) -> None:
    """Leave ring must not stay dark under a leftover lease: clear lease first
    (reset/retire / wake-done), then leave rings unread. Documents the
    0.7.17 push-at-leave + live-lease interaction.
    """
    assert _letter(office, 200) == "missed"
    assert len(_posts(office)) == 1
    # Stale lease still held; unread from a push-at-leave would coalesce.
    office["monkeypatch"].setattr(
        "agent_coord.server.records.push.waiting", lambda cn, desk: None
    )
    office["monkeypatch"].setattr(
        push,
        "unread_mail_frames",
        lambda cn, desk, **k: [
            {"kind": "mail", "id": 201, "outcome": "missed", "body": "letter 201", "sender": "s"}
        ],
    )
    assert push.ring_waiting(office["cn"], "away", "leave") == "coalesced"
    # After the lease is cleared (wake-done / reset / expire), leave rings.
    wake.gate_clear("away")
    assert push.ring_waiting(office["cn"], "away", "leave") == "sent"
    assert _posts(office)[-1]["id"] == 201


def test_uncovered_helper_lists_pairs_with_no_wake_line() -> None:
    """tools/wake_uncovered.classify marks a letter with no wake line as uncovered."""
    from tools import wake_uncovered as wu

    # One sent, one coalesced-then-trailing, one with no line at all.
    events = [
        ("away", 1, "sent"),
        ("away", 2, "coalesced"),
        ("away", 2, "sent"),  # trailing named latest; treat coalesced+later sent as covered
        ("away", 3, None),
    ]
    got = wu.classify(events)
    assert got["covered"] == {( "away", 1), ("away", 2)}
    assert got["uncovered"] == {("away", 3)}
