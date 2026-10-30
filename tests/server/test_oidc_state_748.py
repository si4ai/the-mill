"""Card 748: the directory and iam login binds the callback to the browser that started it.

The login sets state, nonce and a PKCE verifier in a short-lived cookie. The
callback refuses a code without a matching state, sends the verifier at the
code exchange and refuses an id token whose nonce does not match. Local RSA
key, stubbed issuer, no network.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from agent_coord.server.admin import door

ISSUER = "https://issuer.example/office"
AUDIENCE = "mill-wall"
DOC = {
    "authorization_endpoint": "https://issuer.example/oauth2/authorize",
    "token_endpoint": "https://issuer.example/oauth2/token",
    "jwks_uri": "https://issuer.example/jwks",
}


@pytest.fixture
def office(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(RSAAlgorithm.to_jwk(key.public_key()))
    jwk["kid"] = "test"
    for name, value in (
        ("DOOR", "directory"),
        ("DIRECTORY_ISSUER", ISSUER),
        ("DIRECTORY_CLIENT_ID", AUDIENCE),
        ("DIRECTORY_CLIENT_SECRET", "secret"),
        ("MILL_URL", "https://wall.example"),
    ):
        monkeypatch.setenv("AGENT_COORD_" + name, value)
    monkeypatch.setattr("agent_coord.server.admin.oidc.discovery", lambda issuer, **_kw: DOC)
    monkeypatch.setattr("agent_coord.server.admin.oidc.fetch_jwks", lambda issuer, **_kw: {"keys": [jwk]})
    monkeypatch.setattr(door, "_JWKS", {})
    monkeypatch.setattr("agent_coord.server.admin.human.allows", lambda token: False)
    monkeypatch.setattr("agent_coord.server.admin.human.seat", lambda token: "bearer-1" if token else "")
    sent: list[dict] = []
    nonce_box = {"nonce": ""}

    def exchange(doc, **kw):
        sent.append(kw)
        claims = {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": "subject-1",
            "exp": int(time.time()) + 600,
            "token_use": "id",
        }
        if nonce_box["nonce"]:
            claims["nonce"] = nonce_box["nonce"]
        return {"id_token": jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test"})}

    monkeypatch.setattr("agent_coord.server.admin.oidc.exchange_code", exchange)
    return {"sent": sent, "nonce": nonce_box}


def _get(path: str, cookie: str = ""):
    from agent_coord.server.middleware import make_handler

    Handler = make_handler({}, api_only=True)

    class Fake:
        command = "GET"

        def __init__(self):
            self.path = path
            self.headers = {"Cookie": cookie} if cookie else {}
            self._code = None
            self._hdrs: list[tuple[str, str]] = []
            self._body = b""
            self.wfile = self

        def write(self, data):
            self._body += data

        def send_response(self, code):
            self._code = code

        def send_header(self, key, value):
            self._hdrs.append((key.lower(), value))

        def end_headers(self):
            pass

        def log_message(self, *_args):
            pass

    hit = Fake()
    for name in ("do_GET", "_send", "_door_ok", "_do_GET_inner"):
        setattr(hit, name, getattr(Handler, name).__get__(hit, Fake))
    hit.do_GET()
    return hit


def _login():
    loc, cookie = door.login_redirect()
    query = {k: v[0] for k, v in parse_qs(urlparse(loc).query).items()}
    pair = cookie.split(";", 1)[0]
    return query, cookie, pair


def _session(hit) -> bool:
    return any(k == "set-cookie" and v.startswith(door.COOKIE + "=bearer-1") for k, v in hit._hdrs)


def test_login_sends_state_nonce_and_s256_challenge(office):
    query, cookie, pair = _login()
    assert len(query["state"]) >= 32 and len(query["nonce"]) >= 32
    assert query["code_challenge_method"] == "S256"
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie
    assert "Max-Age=600" in cookie and "Path=/mill/oidc/callback" in cookie
    state, nonce, verifier = pair.split("=", 1)[1].split(".")
    assert (state, nonce) == (query["state"], query["nonce"])
    want = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert query["code_challenge"] == want


def test_login_is_fresh_each_time(office):
    first, _c1, _p1 = _login()
    second, _c2, _p2 = _login()
    assert first["state"] != second["state"] and first["nonce"] != second["nonce"]


def test_callback_without_state_cookie_is_refused(office):
    hit = _get("/mill/oidc/callback?code=attacker-code")
    assert not _session(hit)
    assert office["sent"] == []


def test_callback_with_mismatched_state_is_refused(office):
    query, _cookie, pair = _login()
    hit = _get("/mill/oidc/callback?code=attacker-code&state=other-state", cookie=pair)
    assert not _session(hit)
    assert office["sent"] == []
    hit = _get("/mill/oidc/callback?code=attacker-code", cookie=pair)
    assert not _session(hit)
    assert office["sent"] == []


def test_callback_sends_verifier_and_checks_nonce(office):
    query, _cookie, pair = _login()
    office["nonce"]["nonce"] = query["nonce"]
    hit = _get(f"/mill/oidc/callback?code=code-1&state={query['state']}", cookie=pair)
    assert hit._code == 302
    assert _session(hit)
    verifier = pair.split("=", 1)[1].split(".")[2]
    assert office["sent"][0]["code_verifier"] == verifier
    assert office["sent"][0]["code"] == "code-1"
    assert any(k == "set-cookie" and v.startswith(door.COOKIE_OIDC + "=;") and "Max-Age=0" in v for k, v in hit._hdrs)


@pytest.mark.parametrize("token_nonce", ["", "other-nonce"])
def test_callback_refuses_a_token_without_the_login_nonce(office, token_nonce):
    query, _cookie, pair = _login()
    office["nonce"]["nonce"] = token_nonce
    hit = _get(f"/mill/oidc/callback?code=code-1&state={query['state']}", cookie=pair)
    assert not _session(hit)
    assert len(office["sent"]) == 1


def test_iam_door_takes_the_same_binding(office, monkeypatch):
    monkeypatch.setenv("AGENT_COORD_DOOR", "iam")
    query, _cookie, pair = _login()
    assert "state" in query and "code_challenge" in query
    hit = _get("/mill/oidc/callback?code=attacker-code&state=other-state", cookie=pair)
    assert not _session(hit)
