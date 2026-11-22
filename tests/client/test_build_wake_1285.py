# -*- coding: utf-8 -*-
"""Card 1285: the Build parent shell prints one safe line and stays quiet on success."""
from __future__ import annotations

from agent_coord.client.build_wake import classify, command_line, seat_after


def _lines(text: str) -> list[str]:
    seen: set[str] = set()
    sit: set[str] = set()
    out: list[str] = []
    for line in text.splitlines():
        out.extend(classify(line, seen, sit))
    return out


def test_socket_address_never_prints():
    secret = "wss://203.0.113.10/ws/grok-tui"
    text = "\n".join(
        [
            '{"desk": "grok-tui", "mode": "ws"}',
            '{"backchannel":"ws","url":"%s","desk":"grok-tui"}' % secret,
            '{"ready": true, "desk": "grok-tui", "note": "connected"}',
            '{"kind": "sync", "sync": [{"kind": "mail", "id": 6794, "body": "%s"}], "holds": []}'
            % secret,
            "{'HINT': {'id': 6795, 'route': '', 'kind': 'mail', 'desk': 'grok-tui'}}",
            '{"ok": true, "mode": "sit-exit", "hint": {"kind": "mail", "id": 6795, "body": "%s"}}'
            % secret,
            '{"ok": false, "error": "connect closed", "url": "%s"}' % secret,
            "{'connector': 'error', 'detail': 'wake failed: %s'}" % secret,
        ]
    )
    got = _lines(text)
    assert secret not in "\n".join(got)
    assert "203.0.113.10" not in "\n".join(got)
    assert got == [
        "SEATED grok-tui",
        "SYNC n=1 newest=6794 mail=1",
        "HINT mail 6795",
        "HINT mail 6795 sit-exit",
        "CONNECT_CLOSED",
        "POKE error",
    ]


def test_zero_exit_is_quiet_and_failure_is_one_line():
    assert command_line(0) is None
    assert command_line(1) == "CMD exit 1"


def test_second_drop_stops():
    assert seat_after(True, 0) == "restart"
    assert seat_after(True, 1) == "hold-drop"
    assert seat_after(False, 0) == "hold-end"
