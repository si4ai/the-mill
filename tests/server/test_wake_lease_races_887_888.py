"""F144a / F144b: the two wake-lease races (cards 887, 888).

F144a (card 887). Seen: post_desk peeked the lease (_gate_open) and recorded the
held-back item (_coalesced) under two separate lock holds. A mill wake-done that
landed between them popped the lease with nothing held back; _coalesced then
found no lease and returned, so the letter waited with no wake at all. Now the
peek and the record are one lock hold, and a lease that ended in between lets
the item post. Checked at every lock boundary of the letter's path.

F144b (card 888). Seen: lease_done popped whatever lease was current, so a run
that outlived wake_lease_s and said done after a newer wake ended the newer
run's lease. Now every wake carries wake.lease (a token per lease) and
mill wake-done --lease TOKEN ends only that lease; a stale done stores its note
and changes nothing else. A done with no token (an older client) ends the
current lease, as before.
"""
from __future__ import annotations

import threading

import pytest

from agent_coord.server import wake
from tests.server.test_wake_lease_F144 import _letter, _posts, office  # noqa: F401  (fixture)


class _DoneBefore:
    """A stand-in for wake._GATE_LOCK that runs one wake-done just before its
    Nth acquire after arming: a deterministic interleaving of a concurrent done."""

    def __init__(self, real, cn):
        self.real = real
        self.cn = cn
        self.n = 0
        self.at = None
        self.fired = False

    def arm(self, at: int) -> None:
        self.n, self.at, self.fired = 0, at, False

    def _maybe(self) -> None:
        if self.at is None or self.fired:
            return
        self.n += 1
        if self.n == self.at:
            self.fired = True
            wake._GATE_LOCK = self.real  # the done takes the real lock
            try:
                wake.lease_done(self.cn, "away")
            finally:
                wake._GATE_LOCK = self

    def __enter__(self):
        self._maybe()
        return self.real.__enter__()

    def __exit__(self, *a):
        return self.real.__exit__(*a)

    def acquire(self, *a, **k):
        self._maybe()
        return self.real.acquire(*a, **k)

    def release(self):
        return self.real.release()


@pytest.mark.parametrize("at", range(1, 4))
def test_a_done_at_any_lock_boundary_never_strands_a_letter(office, monkeypatch, at) -> None:  # noqa: F811
    _letter(office, 1)  # wake 1 takes the lease
    gate = _DoneBefore(threading.Lock(), office["cn"])
    monkeypatch.setattr(wake, "_GATE_LOCK", gate)
    gate.arm(at)
    _letter(office, 2)  # arrives while wake 1's run says done
    gate.at = None
    # Past the letter path's last lock hold the done never fires; the assert holds either way.
    posts = _posts(office)
    # Letter 2 waits in the queue; it must be on a wake of its own: posted
    # directly, or held back by a live lease (so its done or timeout rings it).
    if len(posts) == 1:
        held = wake._TRAIL.get("away") or {}
        assert wake._GATE.get("away") is not None and held.get("keys"), (
            "letter 2 waits in the queue with no wake and no lease to ring it"
        )
    else:
        assert len(posts) == 2 and posts[1]["id"] == 2


def test_every_wake_carries_its_lease_token(office) -> None:  # noqa: F811
    _letter(office, 1)
    _letter(office, 2)
    first = _posts(office)[0]["wake"]["lease"]
    assert isinstance(first, str) and len(first) >= 8
    assert wake.lease_done(office["cn"], "away", lease=first) == "sent"
    second = _posts(office)[1]["wake"]["lease"]
    assert second and second != first


def test_a_stale_done_does_not_end_the_newer_lease(office) -> None:  # noqa: F811
    """Run 1 outlives the lease; the timer wakes run 2; run 1's late done must not end run 2's lease."""
    _letter(office, 1)
    old = _posts(office)[0]["wake"]["lease"]
    _letter(office, 2)
    office["clock"]["t"] += wake.lease_s()
    delay, fn, args = office["timers"][0]
    assert fn(*args) == "sent"  # lease-expired: run 2 is woken
    new = _posts(office)[1]["wake"]["lease"]
    assert wake.lease_done(office["cn"], "away", lease=old, note="run 1 finally done") == "stale"
    _letter(office, 3)
    assert len(_posts(office)) == 2  # run 2 still holds its lease: no overlapping run 3
    assert any("wake=done stale=yes" in ln for ln in office["lines"])
    # Run 2's own done ends it; letter 3 rings once, with run 1's note kept.
    assert wake.lease_done(office["cn"], "away", lease=new) == "sent"
    got = _posts(office)
    assert len(got) == 3 and got[2]["wake"]["last_note"] == "run 1 finally done"


def test_a_done_without_a_token_still_ends_the_current_lease(office) -> None:  # noqa: F811
    """Old clients send no token: the 0.7.19 behaviour holds for them."""
    _letter(office, 1)
    _letter(office, 2)
    assert wake.lease_done(office["cn"], "away") == "sent"


def test_mill_wake_done_sends_the_lease_token() -> None:
    from unittest.mock import patch

    from agent_coord.__main__ import _build_parser
    from agent_coord.client.outbound import body_from_args

    args = _build_parser().parse_args(["wake-done", "--lease", "abc123def456", "--note", "n"])
    with patch("agent_coord.client.tokens.resolve_desk_owner", lambda _x: "away"):
        body = body_from_args(args)
    assert body["lease"] == "abc123def456"


def test_wake_done_rpc_passes_the_token(monkeypatch) -> None:
    from unittest.mock import MagicMock

    from agent_coord.server.api.mill import rpc

    seen: list = []
    monkeypatch.setattr(wake, "lease_done", lambda cn, desk, note="", lease="": seen.append((desk, lease)) or "stale")
    out = rpc.HANDLERS["wake-done"](MagicMock(), {"verb": "wake-done", "lease": "tok"}, "the-mill", "away")
    assert seen == [("away", "tok")] and out["wake"] == "stale"
