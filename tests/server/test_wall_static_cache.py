# -*- coding: utf-8 -*-
"""F-row (wall-static-cache-pins, #712): pinned Wall assets cache for a year.

A static file asked for with a ?v= pin is immutable for that URL, so the
browser keeps it for a year. The page and unpinned files keep a short
max-age plus an ETag, so a new pin or edit is picked up and a recheck is 304.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agent_coord.server.middleware import _static_cache_control

_YEAR = "public, max-age=31536000, immutable"
_SHORT = "public, max-age=60"


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from agent_coord.lib.observe import parse_roots
    from agent_coord.server.asgi import make_asgi_app

    monkeypatch.delenv("AGENT_COORD_WALL_ALLOW", raising=False)
    here = Path(__file__).resolve().parents[2]
    return TestClient(make_asgi_app(parse_roots(cwd=here), api_only=False))


@pytest.mark.parametrize(
    "path",
    ["/boot.js?v=wow285", "/board.css?v=wow283", "/mail/mail.js?v=wow285&x=1"],
)
def test_pinned_cache_is_immutable(path: str) -> None:
    assert _static_cache_control(path, "text/javascript") == _YEAR


@pytest.mark.parametrize(
    "path",
    ["/boot.js", "/gutter.js", "/boot.js?v=", "/boot.js?x=1", "/boot.js?v=a%20b", "/boot.js?v=" + "a" * 65],
)
def test_unpinned_cache_stays_short(path: str) -> None:
    assert _static_cache_control(path, "text/javascript") == _SHORT


def test_http_pinned_asset_year(client) -> None:
    r = client.get("/boot.js?v=wow285")
    assert r.status_code == 200
    assert r.headers["cache-control"] == _YEAR


def test_http_page_and_unpinned_short_with_etag(client) -> None:
    page = client.get("/")
    assert page.status_code == 200
    assert page.headers["cache-control"] == "private, max-age=60"
    r = client.get("/gutter.js")
    assert r.status_code == 200
    assert r.headers["cache-control"] == _SHORT
    etag = r.headers.get("etag")
    assert etag
    again = client.get("/gutter.js", headers={"If-None-Match": etag})
    assert again.status_code == 304
    assert again.headers["cache-control"] == _SHORT
    assert again.headers["etag"] == etag
    stale = client.get("/gutter.js", headers={"If-None-Match": '"stale"'})
    assert stale.status_code == 200


def test_read_static_refuses_outside_roots(tmp_path) -> None:
    from agent_coord.server.middleware import _read_static, _safe_static

    outside = tmp_path / "x.js"
    outside.write_text("x", encoding="utf-8")
    assert _read_static(outside) is None
    found = _safe_static("gutter.js")
    assert found is not None
    assert _read_static(found) == found.read_bytes()
