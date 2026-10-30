"""Directory and IAM door tokens. Local RSA key. No network."""

from __future__ import annotations

import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from agent_coord.server.admin import door
from agent_coord.server.admin.oidc import identity, mapped_roles, token_kind, verify_token

ISSUER = "https://issuer.example/office"
AUDIENCE = "mill-wall"


def _key_and_jwks():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(RSAAlgorithm.to_jwk(key.public_key()))
    jwk["kid"] = "test"
    return key, {"keys": [jwk]}


def _token(key, **claims):
    body = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": "subject-1",
        "exp": int(time.time()) + 600,
    }
    body.update(claims)
    return jwt.encode(body, key, algorithm="RS256", headers={"kid": "test"})


def test_human_admin_group_maps_to_role_admin():
    key, jwks = _key_and_jwks()
    token = _token(key, token_use="id", email="a@office.example", **{"cognito:groups": ["ROLE_Admin"]})
    who = identity(token, issuer=ISSUER, audience=AUDIENCE, jwks=jwks)
    assert who is not None
    assert who["kind"] == "human"
    assert who["roles"] == ["Admin"]


def test_agent_access_token_has_no_role_without_the_group():
    key, jwks = _key_and_jwks()
    token = _token(key, token_use="access", client_id=AUDIENCE)
    who = identity(token, issuer=ISSUER, audience=AUDIENCE, jwks=jwks)
    assert who is not None
    assert who["kind"] == "agent"
    assert who["roles"] == []
    assert token_kind({"token_use": "access"}) == "agent"


def test_wrong_issuer_is_rejected():
    key, jwks = _key_and_jwks()
    token = _token(key, token_use="id", email="a@office.example")
    assert verify_token(token, issuer=ISSUER, audience=AUDIENCE, jwks=jwks)["sub"] == "subject-1"
    assert identity(token, issuer="https://other.example", audience=AUDIENCE, jwks=jwks) is None


def test_directory_door_opens_for_a_human_bearer(monkeypatch):
    monkeypatch.setenv("AGENT_COORD_DOOR", "directory")
    monkeypatch.setenv("AGENT_COORD_DIRECTORY_ISSUER", ISSUER)
    monkeypatch.setenv("AGENT_COORD_DIRECTORY_CLIENT_ID", AUDIENCE)
    monkeypatch.setattr(
        "agent_coord.server.admin.human.allows",
        lambda token: token == "human-bearer",
    )
    assert door.check("human-bearer") is True
    assert door.check("header.payload.sig") is False


def test_door_cognito_is_not_a_door(monkeypatch):
    monkeypatch.setenv("AGENT_COORD_DOOR", "cognito")
    assert door.mode() == "path"


def test_directory_without_issuer_stays_open(monkeypatch):
    monkeypatch.setenv("AGENT_COORD_DOOR", "directory")
    monkeypatch.setenv("AGENT_COORD_DIRECTORY_ISSUER", "")
    assert door.check("") is True


def test_iam_door_rejects_a_bad_token(monkeypatch):
    monkeypatch.setenv("AGENT_COORD_DOOR", "iam")
    monkeypatch.setenv("AGENT_COORD_DIRECTORY_ISSUER", ISSUER)
    monkeypatch.setenv("AGENT_COORD_DIRECTORY_CLIENT_ID", AUDIENCE)
    monkeypatch.setattr("agent_coord.server.admin.human.allows", lambda token: False)
    assert door.check("nope") is False


def test_mapped_roles_reads_groups_string():
    assert mapped_roles({"groups": "ROLE_Admin other"}) == ["Admin"]
    assert mapped_roles({"groups": "viewers"}) == []


def test_mapped_roles_dual_accepts_role_admin_and_admin():
    assert mapped_roles({"groups": ["Admin"]}, admin_group="ROLE_Admin") == ["Admin"]
    assert mapped_roles({"groups": ["ROLE_Admin"]}, admin_group="Admin") == ["Admin"]
    assert mapped_roles({"groups": ["Admin"]}, admin_group="Admin") == ["Admin"]
    assert mapped_roles({"groups": ["viewers"]}, admin_group="ROLE_Admin") == []


def test_authorize_url_uses_discovery():
    from agent_coord.server.admin.oidc import authorize_url

    url = authorize_url(
        {"authorization_endpoint": "https://issuer.example/oauth2/authorize"},
        AUDIENCE,
        "https://wall.example/mill/oidc/callback",
    )
    assert url.startswith("https://issuer.example/oauth2/authorize?")
    assert "client_id=mill-wall" in url
    assert "redirect_uri=" in url


def test_exchange_code_reads_id_token():
    from agent_coord.server.admin.oidc import exchange_code

    class _Resp:
        def __init__(self, payload):
            self.payload = payload

        def read(self):
            return json.dumps(self.payload).encode()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def opener(req, timeout=5):
        return _Resp({"id_token": "header.payload.sig", "access_token": "access"})

    out = exchange_code(
        {"token_endpoint": "https://issuer.example/oauth2/token"},
        client_id=AUDIENCE,
        client_secret="secret",
        code="code-1",
        redirect_uri="https://wall.example/mill/oidc/callback",
        opener=opener,
    )
    assert out["id_token"] == "header.payload.sig"


def test_login_redirect_empty_without_mill_url(monkeypatch):
    monkeypatch.setenv("AGENT_COORD_DOOR", "directory")
    monkeypatch.setenv("AGENT_COORD_DIRECTORY_ISSUER", ISSUER)
    monkeypatch.setenv("AGENT_COORD_DIRECTORY_CLIENT_ID", AUDIENCE)
    monkeypatch.setenv("AGENT_COORD_MILL_URL", "")
    assert door.login_redirect() == ("", "")


def test_logout_url_rejects_a_non_http_value(monkeypatch):
    monkeypatch.setenv("AGENT_COORD_DIRECTORY_LOGOUT_URL", "javascript:alert(1)")
    assert door.logout_url() == ""
    monkeypatch.setenv("AGENT_COORD_DIRECTORY_LOGOUT_URL", "https://issuer.example/logout?client_id=abc")
    assert door.logout_url().startswith("https://issuer.example/logout?")


def test_signout_link_is_directory_only(monkeypatch):
    url = "https://issuer.example/logout?client_id=abc"
    html = '<a id="wall-signout" class="wall-signout" data-signout="off" href="/mill/signout">'
    monkeypatch.setenv("AGENT_COORD_DIRECTORY_LOGOUT_URL", url)
    monkeypatch.setenv("AGENT_COORD_DOOR", "invite")
    assert door.signout_href() == ""
    assert door.board_signout(html) == html
    monkeypatch.setenv("AGENT_COORD_DOOR", "path")
    assert door.signout_href() == ""
    monkeypatch.setenv("AGENT_COORD_DOOR", "directory")
    assert door.signout_href() == url
    assert 'data-signout="on"' in door.board_signout(html)
    monkeypatch.setenv("AGENT_COORD_DOOR", "iam")
    assert door.signout_href() == url


def _signout_get(path: str):
    from agent_coord.server.middleware import make_handler

    Handler = make_handler({}, api_only=True)

    class Fake:
        def __init__(self):
            self.path = path
            self.headers = {}
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
    hit.do_GET = Handler.do_GET.__get__(hit, Fake)
    hit._send = Handler._send.__get__(hit, Fake)
    hit._door_ok = Handler._door_ok.__get__(hit, Fake)
    hit._do_GET_inner = Handler._do_GET_inner.__get__(hit, Fake)
    hit.do_GET()
    return hit


def test_invite_signout_returns_home_without_clearing(monkeypatch):
    monkeypatch.setenv("AGENT_COORD_DOOR", "invite")
    monkeypatch.setenv("AGENT_COORD_DIRECTORY_LOGOUT_URL", "https://issuer.example/logout")
    hit = _signout_get("/mill/signout")
    assert hit._code == 302
    assert ("location", "/") in hit._hdrs
    assert not any(key == "set-cookie" for key, _value in hit._hdrs)


def test_directory_signout_clears_the_cookie_and_redirects(monkeypatch):
    monkeypatch.setenv("AGENT_COORD_DOOR", "directory")
    monkeypatch.setenv(
        "AGENT_COORD_DIRECTORY_LOGOUT_URL",
        "https://issuer.example/logout?client_id=abc&logout_uri=https%3A%2F%2Fwall.example%2F",
    )
    hit = _signout_get("/mill/signout")
    assert hit._code == 302
    locations = [value for key, value in hit._hdrs if key == "location"]
    cookies = [value for key, value in hit._hdrs if key == "set-cookie"]
    assert locations == [
        "https://issuer.example/logout?client_id=abc&logout_uri=https%3A%2F%2Fwall.example%2F"
    ]
    assert any(value.startswith("factory-door=;") and "Max-Age=0" in value for value in cookies)
    assert any(value.startswith("factory-door-key=;") and "Max-Age=0" in value for value in cookies)


def test_expired_token_is_rejected():
    key, jwks = _key_and_jwks()
    token = _token(key, token_use="id", email="a@office.example", exp=int(time.time()) - 60)
    with pytest.raises(Exception):
        verify_token(token, issuer=ISSUER, audience=AUDIENCE, jwks=jwks)
