"""Directory and IAM tokens for the human wall.

The browser trades a code for an id token. Groups on that token map onto mill
roles. The configured admin group maps to Admin. A viewer token has no mill role.
An agent access token can be classified here. It does not seat a human and
it is not sent on /mill/v1 or /ws. This module does not write the book.
"""

from __future__ import annotations

import hmac
import json
from typing import Any
from urllib.request import urlopen

import jwt
from jwt.algorithms import RSAAlgorithm

from agent_coord.const import CONST_ADMIN

_GROUP_CLAIMS = ("cognito:groups", "groups", "roles")


def discovery(issuer: str, opener=urlopen, timeout: float = 5.0) -> dict[str, Any]:
    url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    with opener(url, timeout=timeout) as resp:
        doc = json.loads(resp.read().decode("utf-8"))
    if not isinstance(doc, dict):
        raise ValueError("oidc: discovery")
    return doc


def fetch_jwks(issuer: str, opener=urlopen, timeout: float = 5.0) -> dict[str, Any]:
    doc = discovery(issuer, opener=opener, timeout=timeout)
    jwks_uri = str(doc.get("jwks_uri") or "")
    if not jwks_uri:
        raise ValueError("oidc: issuer has no jwks_uri")
    with opener(jwks_uri, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def authorize_url(
    doc: dict[str, Any],
    client_id: str,
    redirect_uri: str,
    state: str = "",
    *,
    nonce: str = "",
    code_challenge: str = "",
) -> str:
    endpoint = str(doc.get("authorization_endpoint") or "").strip()
    if not endpoint or not client_id or not redirect_uri:
        raise ValueError("oidc: authorize")
    from urllib.parse import urlencode

    query = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": "openid",
    }
    if state:
        query["state"] = state
    if nonce:
        query["nonce"] = nonce
    if code_challenge:
        query["code_challenge"] = code_challenge
        query["code_challenge_method"] = "S256"
    return endpoint + ("&" if "?" in endpoint else "?") + urlencode(query)


def exchange_code(
    doc: dict[str, Any],
    *,
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
    code_verifier: str = "",
    opener=urlopen,
    timeout: float = 5.0,
) -> dict[str, Any]:
    from urllib.request import Request
    from urllib.parse import urlencode

    endpoint = str(doc.get("token_endpoint") or "").strip()
    if not endpoint or not code:
        raise ValueError("oidc: token")
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "client_secret": client_secret,
    }
    if code_verifier:
        form["code_verifier"] = code_verifier
    body = urlencode(form).encode()
    req = Request(endpoint, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
    with opener(req, timeout=timeout) as resp:
        out = json.loads(resp.read().decode("utf-8"))
    if not isinstance(out, dict):
        raise ValueError("oidc: token response")
    return out


def _key_for(jwks: dict[str, Any], kid: str | None):
    keys = list(jwks.get("keys") or [])
    chosen = None
    for item in keys:
        if kid and item.get("kid") == kid:
            chosen = item
            break
    if chosen is None and len(keys) == 1:
        chosen = keys[0]
    if not chosen:
        raise ValueError("oidc: no matching key")
    return RSAAlgorithm.from_jwk(json.dumps(chosen))


def verify_token(
    token: str,
    *,
    issuer: str,
    audience: str,
    jwks: dict[str, Any],
    nonce: str = "",
) -> dict[str, Any]:
    header = jwt.get_unverified_header(token)
    key = _key_for(jwks, header.get("kid"))
    claims = jwt.decode(
        token,
        key,
        algorithms=["RS256"],
        audience=audience,
        issuer=issuer,
        options={"require": ["exp", "iss", "aud"]},
    )
    if not isinstance(claims, dict):
        raise ValueError("oidc: claims")
    if nonce and not hmac.compare_digest(str(claims.get("nonce") or "").encode(), nonce.encode()):
        raise ValueError("oidc: nonce")
    return claims


def token_kind(claims: dict[str, Any]) -> str:
    """human = glance login. agent = app client or workload."""
    use = str(claims.get("token_use") or "").strip().lower()
    gty = str(claims.get("gty") or "").strip().lower()
    if use == "id":
        return "human"
    if use == "access" or gty == "client-credentials":
        return "agent"
    if claims.get("email") or claims.get("preferred_username"):
        return "human"
    if claims.get("client_id") or claims.get("sub"):
        return "agent"
    return "human"


def mapped_roles(claims: dict[str, Any], admin_group: str = "ROLE_Admin") -> list[str]:
    raw: list[Any] = []
    for key in _GROUP_CLAIMS:
        val = claims.get(key)
        if isinstance(val, str):
            raw.extend(val.split())
        elif isinstance(val, (list, tuple)):
            raw.extend(val)
    names = {str(item).strip() for item in raw if str(item).strip()}
    want = (admin_group or "").strip()
    # Dual-accept IdP ROLE_Admin and mill bare Admin; do not flip IdP-only.
    aliases = {want} if want else set()
    if want in ("ROLE_Admin", CONST_ADMIN):
        aliases.update({"ROLE_Admin", CONST_ADMIN})
    if aliases and (aliases & names):
        return [CONST_ADMIN]
    return []

def identity(
    token: str,
    *,
    issuer: str,
    audience: str,
    jwks: dict[str, Any],
    admin_group: str = "ROLE_Admin",
) -> dict[str, Any] | None:
    try:
        claims = verify_token(token, issuer=issuer, audience=audience, jwks=jwks)
    except Exception:
        return None
    return {
        "sub": str(claims.get("sub") or ""),
        "kind": token_kind(claims),
        "client_id": str(claims.get("client_id") or claims.get("azp") or ""),
        "roles": mapped_roles(claims, admin_group),
    }
