# -*- coding: utf-8 -*-
"""Security: a client may not inject server-only request fields.

Behavior under test:
  - a non-admin desk cannot become Admin by sending host:true over /ws
  - the office host (loopback /ws peer) can still grant Admin
  - server-internal (_-prefixed) keys from a client are dropped on both paths
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agent_coord.server.api.mill import rpc
from agent_coord.server.book import Book


def _capture_handler(store):
    def handler(c, body, project, owner):
        store["body"] = dict(body)
        store["owner"] = owner
        return [{"ok": True}]

    return handler


def test_non_admin_desk_cannot_become_admin_via_ws_host_flag(monkeypatch):
    """A remote desk's host:true is stripped before the member-add handler runs."""
    store: dict = {}
    monkeypatch.setitem(rpc.HANDLERS, "member-add", _capture_handler(store))
    c = MagicMock(spec=Book)
    rpc.dispatch_ws(
        c,
        "intruder",
        "member-add",
        {"group": "Admin", "desk": "intruder", "host": True},
        req_id="r1",
    )
    assert "host" not in store["body"]
    # identity is the sitting desk, not a body-supplied owner
    assert store["owner"] == "intruder"


def test_office_host_loopback_peer_still_marks_host(monkeypatch):
    """A genuine loopback /ws peer may set host (office-host Admin grant path)."""
    store: dict = {}
    monkeypatch.setitem(rpc.HANDLERS, "member-add", _capture_handler(store))
    c = MagicMock(spec=Book)
    rpc.dispatch_ws(
        c,
        "root",
        "member-add",
        {"group": "Admin", "desk": "root"},
        req_id="r2",
        peer="127.0.0.1",
        forwarded=False,
    )
    assert store["body"].get("host") is True


def test_loopback_peer_with_forwarded_header_is_not_host(monkeypatch):
    """A proxied request (X-Forwarded-For present) is not treated as the office host."""
    store: dict = {}
    monkeypatch.setitem(rpc.HANDLERS, "member-add", _capture_handler(store))
    c = MagicMock(spec=Book)
    rpc.dispatch_ws(
        c,
        "intruder",
        "member-add",
        {"group": "Admin", "desk": "intruder", "host": True},
        req_id="r3",
        peer="127.0.0.1",
        forwarded=True,
    )
    assert "host" not in store["body"]


def test_ws_strips_client_internal_underscore_keys(monkeypatch):
    """Server-internal keys supplied by a client are dropped on the /ws path."""
    store: dict = {}
    monkeypatch.setitem(rpc.HANDLERS, "todo", _capture_handler(store))
    c = MagicMock(spec=Book)
    rpc.dispatch_ws(
        c,
        "desk-a",
        "todo",
        {"need": "x", "note": "hi", "_redacted": ["token"], "host": True},
        req_id="r4",
        peer="203.0.113.9",
    )
    assert "host" not in store["body"]
    assert "_redacted" not in store["body"]


def test_http_dispatch_strips_client_internal_underscore_keys(monkeypatch):
    """HTTP dispatch drops client _-keys; host there is owned by guard.mark_host."""
    store: dict = {}
    monkeypatch.setitem(rpc.HANDLERS, "join", _capture_handler(store))
    c = MagicMock(spec=Book)
    c._cn = MagicMock()
    rpc.dispatch(
        c,
        {"verb": "join", "project": "the-mill", "owner": "a", "_redacted": ["x"]},
        token="",
    )
    assert "_redacted" not in store["body"]
