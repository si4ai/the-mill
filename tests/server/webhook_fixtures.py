"""Shared arrange for desk webhook tests (#618). A fake receiver; no network."""
from __future__ import annotations

from unittest.mock import patch

HOOK_HOST = "hooks.example.test"
HOOK_URL = f"https://{HOOK_HOST}/automations/webhook/fixture-routine"
HOOK_KEY = "unit-key-0123456789"


def arm(monkeypatch, *, armed: dict[str, tuple[str, str]] | None = None) -> None:
    """Allow the fixture host, resolve it public, start with an empty wake gate.

    armed maps desk -> (url, key) for rec_join.wake_target; default: every desk
    is armed at HOOK_URL with HOOK_KEY.
    """
    from agent_coord.server import wake

    monkeypatch.setenv("AGENT_COORD_WAKE_HOSTS", f"{HOOK_HOST}/automations/webhook/")
    monkeypatch.setattr(wake, "public_host", lambda host: True)
    monkeypatch.setattr("agent_coord.server.records.opened.picked_up_ids", lambda cn, ids, desk: set())
    monkeypatch.setattr(wake, "_GATE", {})
    monkeypatch.setattr(wake, "_LEASE_MAIL", {}, raising=False)
    monkeypatch.setattr(wake, "_DONE_MAIL", {}, raising=False)
    monkeypatch.setattr(wake, "_RERINGS", {}, raising=False)
    # #669: no real window-end timer thread in a unit test; a test that checks the
    # trailing POST captures _schedule itself.
    monkeypatch.setattr(wake, "_TRAIL", {})
    monkeypatch.setattr(wake, "_schedule", lambda delay, fn, *args: None)
    table = armed

    def target(cn, desk):
        if table is None:
            return (HOOK_URL, HOOK_KEY)
        return table.get(desk)

    monkeypatch.setattr("agent_coord.server.records.join.wake_target", target)
    # Card 1098 item 5c empty-skip: a wake POST needs waiting work. Real emit/fanout
    # put a row first so pending >= 1; unit tests that expect a POST need the same.
    # Empty-skip cases mock pending=0 themselves (see test_wake_owed_real_1098).
    monkeypatch.setattr("agent_coord.server.records.push.pending", lambda cn, desk: 1)
    monkeypatch.setattr("agent_coord.server.records.push.pending_addressed", lambda cn, desk: False)
    monkeypatch.setattr(wake, "desk_roster", lambda cn, desk: "")


def opener(fn):
    """Patch the wake POST opener (redirects refused) with a fake receiver."""
    return patch("agent_coord.server.wake._open", fn)
