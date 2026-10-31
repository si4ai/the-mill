# -*- coding: utf-8 -*-
"""#783: the stdlib wall caps a request body before it reads it (as #747 does for ASGI).

The stdlib handler read Content-Length bytes with no cap on every POST route
that takes a body. A declared length over BODY_MAX_BYTES is refused with 413
before one body byte is read; a length that is not a number gets 400.
"""
from __future__ import annotations

import socket
import threading
from http.server import ThreadingHTTPServer

import pytest

from agent_coord.server import middleware
from agent_coord.server.middleware import make_handler

PATHS = (
    "/mill/v1/join",
    "/api/mill/join",
    "/api/admin/invites",
    "/api/collect",
    "/api/wall-prefs",
    "/api/desk",
)


@pytest.fixture()
def wall(monkeypatch):
    monkeypatch.setattr("agent_coord.server.admin.door.mode", lambda: "path")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler({}, api_only=True))
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield srv.server_address[1]
    finally:
        srv.shutdown()
        srv.server_close()


def _post(port: int, path: str, length: str) -> int:
    """Send headers only (no body) and return the status line's code."""
    with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
        s.sendall(
            (
                "POST %s HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                "Content-Type: application/json\r\nContent-Length: %s\r\n\r\n" % (path, length)
            ).encode("ascii")
        )
        try:
            head = s.recv(64)
        except socket.timeout:
            return 0  # the wall sat waiting for body bytes
    return int(head.split(b" ", 2)[1])


@pytest.mark.parametrize("path", PATHS)
def test_declared_length_over_cap_is_413_before_any_read(wall, path) -> None:
    assert _post(wall, path, str(64 * 1024 * 1024)) == 413


@pytest.mark.parametrize("path", PATHS)
def test_non_numeric_length_is_400(wall, path) -> None:
    assert _post(wall, path, "abc") == 400


def test_cap_matches_the_asgi_cap() -> None:
    from agent_coord.server import asgi

    assert middleware.BODY_MAX_BYTES == asgi.BODY_MAX_BYTES == 256 * 1024
