# -*- coding: utf-8 -*-
"""Fixtures for Validator mill_live probes against a live mill-wall.

Skip-all unless MILL_LIVE=1. Required / optional env:

  MILL_LIVE=1                 gate for this package (required)
  MILL_LIVE_URL               Wall base URL (default https://192.0.2.10)
  MILL_LIVE_CA                optional CA file; else TLS verify off
  MILL_LIVE_DESK              role desk for /ws sit (e.g. validator)
  MILL_LIVE_TOKEN             Bearer for that desk; WS tests skip if absent

Join path for token (do not commit secrets): mill join / office invite for a
role desk, then export MILL_LIVE_DESK + MILL_LIVE_TOKEN from the session file
(agent_coord.client.tokens.read_session_token). See tests/validator/README.md.

Sets AGENT_COORD_MILL_URL from MILL_LIVE_URL so mill_ws_url resolves wss.
"""
from __future__ import annotations

import os
import ssl
import sys
from pathlib import Path
from typing import Iterator

import httpx
import pytest

# Same-dir import for live_util (repo root is on path; this dir may not be).
_VDIR = Path(__file__).resolve().parent
if str(_VDIR) not in sys.path:
    sys.path.insert(0, str(_VDIR))

pytestmark = pytest.mark.mill_live

_DEFAULT_URL = "https://192.0.2.10"


def _under_this_dir(item: pytest.Item) -> bool:
    """True only for an item collected from a file under tests/validator/."""
    try:
        Path(str(item.path)).resolve().relative_to(_VDIR)
    except ValueError:
        return False
    return True


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    # This hook gets every item in the session, not only this package's, so
    # it skips by the item's path under this directory, never by a substring
    # of the path: tests/install/test_validator_*.py must still run (#663, F113).
    if os.environ.get("MILL_LIVE") == "1":
        return
    skip = pytest.mark.skip(reason="MILL_LIVE=1 required for tests/validator")
    for item in items:
        if _under_this_dir(item):
            item.add_marker(skip)


@pytest.fixture(scope="session")
def mill_base_url() -> str:
    raw = (os.environ.get("MILL_LIVE_URL") or _DEFAULT_URL).strip().rstrip("/")
    if not raw:
        raw = _DEFAULT_URL
    return raw


@pytest.fixture(scope="session")
def mill_tls_verify():
    """httpx verify=: CA path string, or False (verify off)."""
    ca = (os.environ.get("MILL_LIVE_CA") or "").strip()
    if ca:
        p = Path(ca)
        if not p.is_file():
            pytest.skip(f"MILL_LIVE_CA not a file: {ca}")
        return str(p)
    return False


@pytest.fixture(scope="session")
def mill_ssl_context(mill_tls_verify) -> ssl.SSLContext:
    """SSLContext for websockets (wss)."""
    if mill_tls_verify is False:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    if isinstance(mill_tls_verify, str):
        return ssl.create_default_context(cafile=mill_tls_verify)
    return ssl.create_default_context()


@pytest.fixture
def mill_url_env(mill_base_url: str, monkeypatch: pytest.MonkeyPatch) -> str:
    """Point client helpers (mill_ws_url / mill_url) at the live Wall."""
    monkeypatch.setenv("AGENT_COORD_MILL_URL", mill_base_url)
    return mill_base_url


@pytest.fixture(scope="session")
def mill_live_desk() -> str:
    return (os.environ.get("MILL_LIVE_DESK") or "").strip()


@pytest.fixture(scope="session")
def mill_live_token() -> str:
    return (os.environ.get("MILL_LIVE_TOKEN") or "").strip()


@pytest.fixture(scope="session")
def require_live_creds(mill_live_desk: str, mill_live_token: str) -> tuple[str, str]:
    """Skip /ws tests when MILL_LIVE=1 but desk/token absent."""
    missing: list[str] = []
    if not mill_live_desk:
        missing.append("MILL_LIVE_DESK")
    if not mill_live_token:
        missing.append("MILL_LIVE_TOKEN")
    if missing:
        pytest.skip(
            "live /ws creds missing: set "
            + ", ".join(missing)
            + " (role desk + session Bearer; see tests/validator/README.md)"
        )
    return mill_live_desk, mill_live_token


@pytest.fixture
def http_client(mill_tls_verify) -> Iterator[httpx.Client]:
    with httpx.Client(verify=mill_tls_verify, timeout=20.0, follow_redirects=True) as client:
        yield client


@pytest.fixture
def mill_ws_url_live(
    mill_url_env: str,
    require_live_creds: tuple[str, str],
) -> str:
    """wss URL via shared mill_ws_url helper (not a disconnected harness)."""
    from agent_coord.client.ws import mill_ws_url

    desk, _token = require_live_creds
    url = mill_ws_url(desk)
    assert url.startswith("wss://"), f"expected wss for live HTTPS Wall, got {url!r}"
    assert ":80/" not in url and not url.startswith("ws://"), f"must not use http://:80 path: {url}"
    return url