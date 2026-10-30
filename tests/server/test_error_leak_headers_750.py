# -*- coding: utf-8 -*-
"""Card 750: no exception text in a 500, security headers on every response.

The catch-all 500 sends a fixed message and an opaque error id; the
exception text goes only to the server log under that id. Every response
carries nosniff, a deny-framing pair, a referrer policy and a content
security policy the current Wall works under. The door-gated board page is
private to the browser and varies on the cookie.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

LEAK = "db.example:3306 role mill_rw /home/<user>/the-mill/book.cnf"


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from agent_coord.lib.observe import parse_roots
    from agent_coord.server.asgi import make_asgi_app

    monkeypatch.delenv("AGENT_COORD_WALL_ALLOW", raising=False)
    here = Path(__file__).resolve().parents[2]
    return TestClient(make_asgi_app(parse_roots(cwd=here), api_only=False))


@pytest.fixture()
def logged(monkeypatch):
    lines: list[str] = []
    monkeypatch.setattr("agent_coord.server.push.api_log", lambda msg: lines.append(msg))
    return lines


def _door_raises(monkeypatch):
    def boom(*_a, **_kw):
        raise RuntimeError(LEAK)

    monkeypatch.setattr("agent_coord.server.admin.door.invite_from_request", boom)


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_pre_auth_500_sends_no_exception_text(client, logged, monkeypatch, method):
    _door_raises(monkeypatch)
    r = client.request(method, "/api/todo", content=b"{}" if method == "POST" else None)
    assert r.status_code == 500
    assert "db.example" not in r.text and "mill_rw" not in r.text and "/home/" not in r.text
    body = r.json()
    assert body["error"] == "mill API error"
    assert re.fullmatch(r"[0-9a-f]{12}", body["error_id"])
    assert "detail" not in body
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-content-type-options"] == "nosniff"
    hit = [line for line in logged if body["error_id"] in line]
    assert hit and "db.example" in hit[0]


def test_two_errors_get_different_ids(client, logged, monkeypatch):
    _door_raises(monkeypatch)
    one = client.get("/api/todo").json()["error_id"]
    two = client.get("/api/todo").json()["error_id"]
    assert one != two


def _csp(r) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for part in r.headers["content-security-policy"].split(";"):
        bits = part.split()
        if bits:
            out[bits[0]] = bits[1:]
    return out


@pytest.mark.parametrize("path", ["/", "/gutter.js", "/health", "/no-such-page"])
def test_security_headers_on_every_response(client, path):
    r = client.get(path)
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "same-origin"
    csp = _csp(r)
    assert csp["default-src"] == ["'self'"]
    assert csp["frame-ancestors"] == ["'none'"]
    assert csp["object-src"] == ["'none'"]
    assert csp["base-uri"] == ["'none'"]
    assert csp["connect-src"] == ["'self'"]


def test_board_page_is_private_and_varies_on_cookie(client):
    page = client.get("/")
    assert page.status_code == 200
    assert page.headers["cache-control"] == "private, max-age=60"
    assert "cookie" in [v.strip().lower() for v in page.headers["vary"].split(",")]
    again = client.get("/", headers={"If-None-Match": page.headers["etag"]})
    assert again.status_code == 304
    assert again.headers["cache-control"] == "private, max-age=60"
    assert "cookie" in again.headers["vary"].lower()


class _Refs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls: list[str] = []
        self.inline_script = False
        self.inline_handler = False
        self.inline_style = False
        self._in_script = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if any(k.startswith("on") for k in a):
            self.inline_handler = True
        if "style" in a or tag == "style":
            self.inline_style = True
        if tag == "script":
            if a.get("src"):
                self.urls.append(a["src"])
            else:
                self._in_script = True
        if tag in ("link", "img", "source", "iframe", "embed", "object"):
            for key in ("href", "src", "data"):
                if a.get(key):
                    self.urls.append(a[key])

    def handle_data(self, data):
        if self._in_script and data.strip():
            self.inline_script = True

    def handle_endtag(self, tag):
        if tag == "script":
            self._in_script = False


def _allows(sources: list[str], url: str) -> bool:
    if url.startswith("data:"):
        return "data:" in sources
    return not re.match(r"^[a-z][a-z0-9+.-]*:|^//", url, re.I) and "'self'" in sources


def test_wall_loads_under_its_csp(client):
    """Every asset the board page names is same-origin, served, and allowed by the policy."""
    page = client.get("/")
    csp = _csp(page)
    refs = _Refs()
    refs.feed(page.text)
    assert refs.urls, "board page names no assets"
    script_src = csp.get("script-src", csp["default-src"])
    style_src = csp.get("style-src", csp["default-src"])
    img_src = csp.get("img-src", csp["default-src"])
    if refs.inline_script or refs.inline_handler:
        assert "'unsafe-inline'" in script_src
    if refs.inline_style:
        assert "'unsafe-inline'" in style_src
    for url in refs.urls:
        assert _allows(csp["default-src"], url), url
        got = client.get(url)
        assert got.status_code == 200, url
        if url.split("?")[0].endswith(".css"):
            for ref in re.findall(r"url\(\s*['\"]?([^'\")]+)", got.text):
                assert _allows(img_src, ref) or _allows(csp.get("font-src", csp["default-src"]), ref), ref


def test_asgi_dispatch_500_sends_no_exception_text(client, logged, monkeypatch):
    """The adapter's own catch-all (outside the handler) answers the same way."""

    def boom(*_a, **_kw):
        raise RuntimeError(LEAK)

    monkeypatch.setattr("agent_coord.server.asgi.record_access", boom)
    r = client.get("/health")
    assert r.status_code == 500
    assert "db.example" not in r.text and "/home/" not in r.text
    body = r.json()
    assert body["error"] == "mill API error"
    assert re.fullmatch(r"[0-9a-f]{12}", body["error_id"])
    assert r.headers["x-frame-options"] == "DENY"
    assert any(body["error_id"] in line and "db.example" in line for line in logged)
