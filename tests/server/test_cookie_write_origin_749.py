# -*- coding: utf-8 -*-
"""Card 749: a cookie-authenticated write must be same-origin JSON.

A request that carries a door or glance session cookie and no credential
header, on any method but GET, HEAD or OPTIONS, needs Content-Type
application/json and a same-origin signal: Sec-Fetch-Site same-origin, an
Origin that matches the wall, or the X-Mill-Wall header. A cross-site or
same-site Sec-Fetch-Site, or a foreign Origin, is refused before any route
runs. Bearer requests (agents, the CLI) and requests with no session
cookie are not touched.
"""
from __future__ import annotations

from pathlib import Path

import pytest

COOKIE = {"Cookie": "factory-door=session-1"}
JSON = {"Content-Type": "application/json"}


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


def _post(client, headers, body=b'{"action": "mint_seat", "desk": "x"}', method="POST"):
    return client.request(method, "/api/admin/invites", content=body, headers=headers)


def test_cookie_text_plain_post_is_refused(client, calls):
    r = _post(client, {**COOKIE, "Content-Type": "text/plain", "Origin": "http://testserver"})
    assert r.status_code == 415
    assert calls == []


def test_cookie_post_without_content_type_is_refused(client, calls):
    r = _post(client, {**COOKIE, "Origin": "http://testserver", "Content-Type": ""})
    assert r.status_code == 415
    assert calls == []


@pytest.mark.parametrize(
    "origin",
    ["http://evil.example", "http://testserver:8080", "https://sub.testserver", "null"],
)
def test_cookie_post_from_a_foreign_origin_is_refused(client, calls, origin):
    r = _post(client, {**COOKIE, **JSON, "Origin": origin})
    assert r.status_code == 403
    assert calls == []


@pytest.mark.parametrize("site", ["cross-site", "same-site"])
def test_cookie_post_marked_cross_or_same_site_is_refused(client, calls, site):
    r = _post(client, {**COOKIE, **JSON, "Sec-Fetch-Site": site, "Origin": "http://testserver"})
    assert r.status_code == 403
    assert calls == []


def test_cookie_post_with_no_origin_signal_is_refused(client, calls):
    r = _post(client, {**COOKIE, **JSON})
    assert r.status_code == 403
    assert calls == []


@pytest.mark.parametrize(
    "extra",
    [
        {"Origin": "http://testserver"},
        {"Sec-Fetch-Site": "same-origin"},
        {"Sec-Fetch-Site": "same-origin", "Origin": "https://office.example"},
        {"X-Mill-Wall": "1"},
    ],
)
def test_same_origin_json_cookie_post_goes_through(client, calls, extra):
    r = _post(client, {**COOKIE, **JSON, **extra})
    assert r.status_code == 200, r.text
    assert len(calls) == 1


@pytest.mark.parametrize("cookie", ["factory-door-key=k1", "mill-glance=g1"])
def test_every_session_cookie_counts(client, calls, cookie):
    r = _post(client, {"Cookie": cookie, "Content-Type": "text/plain"})
    assert r.status_code == 415
    assert calls == []


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE"])
def test_other_write_methods_get_the_same_check(client, calls, method):
    r = _post(client, {**COOKIE, "Content-Type": "text/plain", "Origin": "http://evil.example"}, method=method)
    assert r.status_code == 415
    r = _post(client, {**COOKIE, **JSON, "Origin": "http://evil.example"}, method=method)
    assert r.status_code == 403


@pytest.mark.parametrize(
    "cred",
    [{"Authorization": "Bearer seat-1"}, {"X-Mill-Invite": "inv-1"}, {"PRIVATE-TOKEN": "tok-1"}],
)
def test_bearer_requests_are_unaffected(client, calls, cred):
    """An agent or the CLI sends its credential in a header; a cookie riding along changes nothing."""
    r = _post(client, {**cred, **COOKIE, "Content-Type": "text/plain", "Origin": "http://evil.example"})
    assert r.status_code == 200, r.text
    assert len(calls) == 1


def test_no_cookie_requests_are_unaffected(client, calls):
    r = _post(client, {"Content-Type": "text/plain"})
    assert r.status_code == 200, r.text
    assert len(calls) == 1


def test_cookie_get_is_not_gated(client):
    r = client.get("/health", headers={**COOKIE, "Origin": "http://evil.example"})
    assert r.status_code in (200, 503)


def _h(**kw):
    from email.message import Message

    m = Message()
    for k, v in kw.items():
        m[k.replace("_", "-")] = v
    return m


def test_origin_behind_the_tls_edge():
    """The installed edge proxies https on 443 to mill-wall with Host kept and no proto header."""
    from agent_coord.server.middleware import origin_matches

    hdr = _h(Host="office.example")
    assert origin_matches("https://office.example", hdr, "127.0.0.1")
    assert origin_matches("http://office.example", hdr, "127.0.0.1")
    assert not origin_matches("https://office.example:8443", hdr, "127.0.0.1")
    assert not origin_matches("https://evil.example", hdr, "127.0.0.1")
    assert origin_matches("https://office.example:8443", _h(Host="office.example:8443"), "127.0.0.1")


def test_forwarded_host_and_proto_only_from_a_trusted_proxy():
    from agent_coord.server.middleware import origin_matches

    hdr = _h(Host="127.0.0.1:18765", X_Forwarded_Host="office.example", X_Forwarded_Proto="https")
    assert origin_matches("https://office.example", hdr, "127.0.0.1")
    assert not origin_matches("http://office.example", hdr, "127.0.0.1")
    # An untrusted peer cannot name the host it wants to match.
    assert not origin_matches("https://office.example", hdr, "198.51.100.7")
    assert origin_matches("http://127.0.0.1:18765", hdr, "198.51.100.7")
