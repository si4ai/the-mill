# -*- coding: utf-8 -*-
"""Card 817: every browser write needs JSON plus a same-origin signal.

Card 749 gated only cookie-authenticated writes. Path and ip doors have no
cookie, so a page on another site could still post to a LAN wall from a
browser on that LAN. Any write that looks like a browser (Origin,
Sec-Fetch-Site, or a door/glance session cookie) and carries no credential
header must be application/json and same-origin. A bare CLI post (no Origin,
no Sec-Fetch-Site, no session cookie) stays open for open-house join; bearer
requests stay unchanged.
"""
from __future__ import annotations

from pathlib import Path

import pytest

JSON = {"Content-Type": "application/json"}
BODY = b'{"action": "mint_seat", "desk": "x"}'


@pytest.fixture()
def calls(monkeypatch):
    seen: list[dict] = []

    def fake(data, office=None, human_token=""):
        seen.append({"data": data, "token": human_token})
        return {"ok": True}

    monkeypatch.setattr("agent_coord.server.admin.invites.post_invites", fake)
    monkeypatch.setenv("AGENT_COORD_DOOR", "path")
    return seen


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from agent_coord.lib.observe import parse_roots
    from agent_coord.server.asgi import make_asgi_app

    monkeypatch.delenv("AGENT_COORD_WALL_ALLOW", raising=False)
    here = Path(__file__).resolve().parents[2]
    return TestClient(make_asgi_app(parse_roots(cwd=here), api_only=False))


def _post(client, headers, body=BODY, method="POST"):
    return client.request(method, "/api/admin/invites", content=body, headers=headers)


def test_no_cookie_text_plain_from_a_foreign_origin_is_refused(client, calls):
    """The card-749 gap: path door, no cookie, foreign Origin, non-JSON."""
    r = _post(
        client,
        {"Content-Type": "text/plain", "Origin": "http://evil.example"},
    )
    assert r.status_code == 415
    assert calls == []


@pytest.mark.parametrize(
    "origin",
    ["http://evil.example", "http://testserver:8080", "https://sub.testserver", "null"],
)
def test_no_cookie_json_from_a_foreign_origin_is_refused(client, calls, origin):
    r = _post(client, {**JSON, "Origin": origin})
    assert r.status_code == 403
    assert calls == []


@pytest.mark.parametrize("site", ["cross-site", "same-site"])
def test_no_cookie_marked_cross_or_same_site_is_refused(client, calls, site):
    r = _post(
        client,
        {**JSON, "Sec-Fetch-Site": site, "Origin": "http://testserver"},
    )
    assert r.status_code == 403
    assert calls == []


def test_cli_post_without_browser_signal_is_unaffected(client, calls):
    """Open-house mill join and other CLI posts send neither Origin nor cookie."""
    r = _post(client, {"Content-Type": "text/plain"})
    assert r.status_code == 200, r.text
    assert len(calls) == 1


@pytest.mark.parametrize(
    "extra",
    [
        {"Origin": "http://testserver"},
        {"Sec-Fetch-Site": "same-origin"},
        {"X-Mill-Wall": "1", "Origin": "http://testserver"},
    ],
)
def test_same_origin_json_without_cookie_goes_through(client, calls, extra):
    r = _post(client, {**JSON, **extra})
    assert r.status_code == 200, r.text
    assert len(calls) == 1


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE"])
def test_other_write_methods_without_cookie_get_the_same_check(client, calls, method):
    r = _post(
        client,
        {"Content-Type": "text/plain", "Origin": "http://evil.example"},
        method=method,
    )
    assert r.status_code == 415
    r = _post(client, {**JSON, "Origin": "http://evil.example"}, method=method)
    assert r.status_code == 403


@pytest.mark.parametrize(
    "cred",
    [{"Authorization": "Bearer seat-1"}, {"X-Mill-Invite": "inv-1"}, {"PRIVATE-TOKEN": "tok-1"}],
)
def test_bearer_with_foreign_origin_is_unaffected(client, calls, cred):
    r = _post(
        client,
        {**cred, "Content-Type": "text/plain", "Origin": "http://evil.example"},
    )
    assert r.status_code == 200, r.text
    assert len(calls) == 1
