# -*- coding: utf-8 -*-
"""Card 1140: the lease token rides every command and renews only its own lease.

Unit level (no book): MILL_LEASE on the client puts wake.lease on each command;
the office renews the live lease for that token and refuses an older one;
wake-done reports ended, already_done or stale (Auditor 5532 change C).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from agent_coord.server import wake
from agent_coord.server.api.mill import rpc


def _body(argv: list[str]) -> dict:
    from agent_coord.__main__ import _build_parser
    from agent_coord.client.outbound import body_from_args

    args = _build_parser().parse_args(argv)
    with patch("agent_coord.client.tokens.resolve_desk_owner", lambda _x: "away"):
        return body_from_args(args)


def test_mill_lease_rides_every_command(monkeypatch) -> None:
    monkeypatch.setenv("MILL_LEASE", "abc123def456")
    assert _body(["inbox"])["lease"] == "abc123def456"
    assert _body(["wake-done"])["lease"] == "abc123def456"
    # An explicit --lease wins over the environment.
    assert _body(["wake-done", "--lease", "fedcba654321"])["lease"] == "fedcba654321"
    monkeypatch.delenv("MILL_LEASE")
    assert "lease" not in _body(["inbox"])


def test_a_command_with_the_live_token_renews_and_an_old_token_does_not(monkeypatch) -> None:
    import time

    monkeypatch.setattr(wake, "_GATE", {})
    monkeypatch.setattr(wake, "_EPOCH", {})
    monkeypatch.setattr(wake, "_UNTIL", {})
    now = time.monotonic()
    with wake._GATE_LOCK:
        wake._GATE["away"] = now - wake.lease_s() + 5  # 5 s left
        wake._EPOCH["away"] = "live-token-1"
    rpc._renew_lease(MagicMock(), "away", "inbox", {"lease": "old-token-00"})
    assert "away" not in wake._UNTIL
    rpc._renew_lease(MagicMock(), "away", "inbox", {"lease": "live-token-1"})
    assert wake._UNTIL["away"] > now + wake.lease_s() - 1
    # wake-done ends the lease; it never renews it.
    wake._UNTIL.clear()
    rpc._renew_lease(MagicMock(), "away", "wake-done", {"lease": "live-token-1"})
    assert "away" not in wake._UNTIL


def test_wake_done_reports_the_lease_outcome(monkeypatch) -> None:
    for got, lease in (("none", "ended"), ("sent", "ended"), ("already_done", "already_done"), ("stale", "stale")):
        monkeypatch.setattr(wake, "lease_done", lambda cn, desk, note="", lease="", _g=got: _g)
        out = rpc.HANDLERS["wake-done"](MagicMock(), {"verb": "wake-done", "lease": "tok"}, "the-mill", "away")
        assert out["lease"] == lease and out["wake"] == got
