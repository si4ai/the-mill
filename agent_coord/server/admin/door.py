"""Office door (port). Adapters plug in; Coord never talks to Entra.



path = house, no login.

invite = one or more office invite keys (mint / TTL / revoke cohort).

directory = company IdP (OIDC/LDAP/SAML) - stub only this ship.

iam = same IdP products when there is no office directory.

Mill does not implement salt/reset/SMS. Plug Keycloak/Authentik/etc.

"""



from __future__ import annotations



import base64

import hashlib

import os

import re

import secrets

from datetime import datetime, timedelta, timezone

from pathlib import Path

from typing import Any

from urllib.parse import parse_qs, urlencode, urlparse



COOKIE = "factory-door"

COOKIE_KEY = "factory-door-key"

COOKIE_OIDC = "factory-door-oidc"

_MODES = ("path", "ip", "invite", "directory", "iam")

# Adapter name -> protocol. Unknown names treated as generic OIDC.

PROVIDERS = {

    "entra": "oidc",

    "ad": "ldap",

    "ldap": "ldap",

    "google": "oidc",

    "okta": "oidc",

    "ping": "oidc",

    "onelogin": "oidc",

    "auth0": "oidc",

    "oidc": "oidc",

    "saml": "saml",

    "keycloak": "oidc",

    "authentik": "oidc",

    "authelia": "oidc",

    "dex": "oidc",

    "fusionauth": "oidc",

    "ory": "oidc",

}



_TTL_RE = re.compile(r"^\s*(\d+)\s*([smhdw]?)\s*$", re.I)


# Host: door invite keys always expire; unset mint TTL -> 24h.

DEFAULT_INVITE_TTL = "24h"


def _invite_sp(cur, proc: str, args: tuple) -> int:
    """#867: an invite write is one SP call on the caller's cursor (commit stays with
    the caller). Returns the SP's row count column (0 when it returns none)."""
    cur.execute("CALL `%s`(%s)" % (proc, ",".join(["%s"] * len(args))), args)
    n = 0
    more = True
    while more:
        if getattr(cur, "with_rows", False):
            got = cur.fetchall()
            if got and not n and isinstance(got[0][0], int):
                n = int(got[0][0])
        nxt = getattr(cur, "nextset", None)
        more = bool(nxt and nxt())
    return n


def provider() -> str:

    """Configured IdP adapter. Empty/unknown -> oidc."""

    raw = str(_setting("directory_kind") or "entra").strip().lower()

    if raw in ("azure", "azuread", "aad", "microsoft"):

        raw = "entra"

    if raw in ("active-directory", "activedirectory"):

        raw = "ad"

    if raw in PROVIDERS:

        return raw

    return "oidc"





def protocol() -> str:

    return PROVIDERS.get(provider(), "oidc")





def mode() -> str:

    raw = str(_setting("door") or "path").strip().lower()

    if raw in ("invite", "token", "link"):

        return "invite"

    if raw in ("ip", "cidr", "lan"):

        return "ip"

    if raw == "directory":

        return "directory"

    if raw in ("iam", "mill-iam"):

        return "iam"

    return "path"





def _setting(key: str) -> str:

    from agent_coord.config import settings



    return str(settings().get(key) or "")





def hash_path() -> Path:

    from agent_coord.config import config_path



    return config_path().parent / "door.hash"





def _digest(token: str) -> str:

    return hashlib.sha256((token or "").strip().encode("utf-8")).hexdigest()





def _now() -> datetime:

    return datetime.now(timezone.utc).replace(tzinfo=None)





def parse_ttl(raw: str | int | None) -> tuple[int | None, datetime | None]:

    """Return (ttl_seconds, expires_at). Empty/0/never = no expiry (set_key_ttl / Admin escape). Mint path defaults unset to DEFAULT_INVITE_TTL."""

    if raw is None or raw == "":

        return None, None

    if isinstance(raw, (int, float)):

        secs = int(raw)

        if secs <= 0:

            return None, None

        return secs, _now() + timedelta(seconds=secs)

    text = str(raw).strip().lower()

    if not text or text in ("0", "none", "never", "-"):

        return None, None

    m = _TTL_RE.match(text)

    if not m:

        raise ValueError("ttl must look like 3600, 7d, 24h, 30m, 90s (or 0/never)")

    n = int(m.group(1))

    unit = (m.group(2) or "s").lower()

    mult = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}.get(unit, 1)

    secs = n * mult

    if secs <= 0:

        return None, None

    return secs, _now() + timedelta(seconds=secs)





def _db():

    """Short-lived office connection for invite keys. None if office not up."""

    try:

        import mysql.connector



        from agent_coord.config import settings



        s = settings()

        return mysql.connector.connect(

            host=s["host"],

            port=int(s["port"]),

            user=s["user"],

            password=s["password"],

            database=s["database"],

            connection_timeout=5,

            autocommit=False,

        )

    except Exception:

        return None





def _new_key_id() -> str:

    return secrets.token_hex(4)





_JWKS: dict[str, Any] = {}


def _redirect_uri() -> str:

    base = (_setting("mill_url") or "").strip().rstrip("/")

    if not base:

        return ""

    return base + "/mill/oidc/callback"


def _oidc_cookie(cookie: str) -> tuple[str, str, str]:

    """State, nonce and PKCE verifier from the login cookie, or three empty strings."""

    for part in (cookie or "").split(";"):

        key, _, val = part.strip().partition("=")

        if key == COOKIE_OIDC:

            bits = val.strip().split(".")

            if len(bits) == 3 and all(bits):

                return bits[0], bits[1], bits[2]

    return "", "", ""

def clear_oidc_cookie_header() -> str:

    return f"{COOKIE_OIDC}=; Path=/mill/oidc/callback; HttpOnly; SameSite=Lax; Max-Age=0"

def login_redirect() -> tuple[str, str]:

    """Browser location and login cookie for a directory or iam office. Empty if the issuer is not armed.

    The cookie binds the callback to this browser for ten minutes: state, nonce and the PKCE verifier.

    """

    issuer = (_setting("directory_issuer") or "").strip()

    client_id = (_setting("directory_client_id") or "").strip()

    redirect_uri = _redirect_uri()

    if mode() not in ("directory", "iam") or not issuer or not client_id or not redirect_uri:

        return "", ""

    from agent_coord.server.admin.oidc import authorize_url, discovery

    state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))

    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")

    try:

        loc = authorize_url(discovery(issuer), client_id, redirect_uri, state, nonce=nonce, code_challenge=challenge)

    except Exception:

        return "", ""

    cookie = f"{COOKIE_OIDC}={state}.{nonce}.{verifier}; Path=/mill/oidc/callback; HttpOnly; SameSite=Lax; Max-Age=600"

    return loc, cookie


def complete_login(code: str, state: str, cookie: str) -> str:

    """Trade ?code= for the id token when ?state= matches the login cookie.

    The PKCE verifier goes to the token endpoint, and the id token must carry the login nonce.

    """

    issuer = (_setting("directory_issuer") or "").strip()

    client_id = (_setting("directory_client_id") or "").strip()

    secret = (_setting("directory_client_secret") or "").strip()

    redirect_uri = _redirect_uri()

    if not issuer or not client_id or not secret or not redirect_uri or not (code or "").strip():

        return ""

    want, nonce, verifier = _oidc_cookie(cookie)

    if not want or not secrets.compare_digest(want.encode(), (state or "").strip().encode()):

        return ""

    from agent_coord.server.admin.oidc import discovery, exchange_code, fetch_jwks, verify_token

    try:

        tokens = exchange_code(

            discovery(issuer),

            client_id=client_id,

            client_secret=secret,

            code=code.strip(),

            redirect_uri=redirect_uri,

            code_verifier=verifier,

        )

        token = str(tokens.get("id_token") or "").strip()

        jwks = _JWKS.get(issuer)

        if jwks is None:

            jwks = fetch_jwks(issuer)

            _JWKS[issuer] = jwks

        verify_token(token, issuer=issuer, audience=client_id, jwks=jwks, nonce=nonce)

    except Exception:

        return ""

    return token


def _oidc_open(token: str) -> bool:

    issuer = (_setting("directory_issuer") or "").strip()

    audience = (_setting("directory_client_id") or "").strip()

    raw = (token or "").strip()

    if not issuer or not audience or raw.count(".") != 2:

        return False

    from agent_coord.server.admin.oidc import fetch_jwks, identity

    try:

        jwks = _JWKS.get(issuer)

        if jwks is None:

            jwks = fetch_jwks(issuer)

            _JWKS[issuer] = jwks

    except Exception:

        return False

    admin = (_setting("directory_admin_group") or "ROLE_Admin").strip() or "ROLE_Admin"

    return identity(token, issuer=issuer, audience=audience, jwks=jwks, admin_group=admin) is not None


def check(token: str) -> bool:

    """True if this office may look. path is open. invite needs an active key.

    Expired / revoked keys fail (enforced). directory without an issuer is not armed (still path).

    directory or iam with an issuer opens for a human bearer whose hash is on file.

    """

    m = mode()

    if m == "iam":

        from agent_coord.server.admin.human import allows

        return allows(token)

    if m == "directory":

        issuer = (_setting("directory_issuer") or "").strip()

        if not issuer:

            return True

        from agent_coord.server.admin.human import allows

        return allows(token)

    if m != "invite":

        return True

    plain = (token or "").strip()

    if not plain:

        return False

    row = match_key(plain)

    if row is not None:

        return True

    # Board knows this token but it is revoked/expired -> fail closed (do not honor legacy hash).

    # Board unreadable (book down or query raised) -> fail closed too (#652).

    if _board_knows_token(plain) is not False:

        return False

    # Legacy single door.hash only when the token is not on the key board.

    path = hash_path()

    if not path.is_file():

        return False

    got = path.read_text(encoding="utf-8").strip()

    if len(got) != 64:

        return False

    return secrets.compare_digest(got, _digest(plain))





def _board_knows_token(token: str) -> bool | None:

    """True if mill_invite has this token, False if it does not, None if the board cannot be read."""

    digest = _digest(token)

    cn = _db()

    if cn is None:

        return None

    try:

        cur = cn.cursor()

        try:

            cur.execute("SELECT 1 FROM mill_invite WHERE token_hash=%s LIMIT 1", (digest,))

            return cur.fetchone() is not None

        finally:

            cur.close()

    except Exception:

        return None

    finally:

        try:

            cn.close()

        except Exception:

            pass





def match_key(token: str) -> dict[str, Any] | None:

    """Return active (non-revoked, non-expired) key row for plaintext token, else None."""

    plain = (token or "").strip()

    if not plain:

        return None

    digest = _digest(plain)

    cn = _db()

    if cn is None:

        return None

    try:

        cur = cn.cursor(dictionary=True)

        try:

            cur.execute(

                "SELECT key_id, label, created_by, created_at, ttl_seconds, expires_at, revoked_at, enabled_at "

                "FROM mill_invite WHERE token_hash=%s LIMIT 1",

                (digest,),

            )

            row = cur.fetchone()

            if not row:

                return None

            if row.get("revoked_at"):

                return None

            if not row.get("enabled_at"):

                return None

            exp = row.get("expires_at")

            if exp is not None and exp < _now():

                return None

            return dict(row)

        finally:

            cur.close()

    except Exception:

        return None

    finally:

        try:

            cn.close()

        except Exception:

            pass





def mint() -> str:

    """Rotate the legacy office invite hash. Also mints a key-board row. Prints once."""

    token = secrets.token_urlsafe(24)

    path = hash_path()

    path.parent.mkdir(parents=True, exist_ok=True)

    path.write_text(_digest(token) + "\n", encoding="utf-8")

    try:

        os.chmod(path, 0o600)

    except OSError:

        pass

    try:

        mint_key(token=token, label="rotated", created_by="door", sync_legacy=False)

    except Exception:

        pass

    return token






def _invite_path_with_ca(plain: str) -> str:
    """Build /?invite=TOKEN[&ca=FP] when the office CA PEM is present."""
    token = (plain or "").strip()
    path = "/?invite=" + token if token else "/?invite=<token>"
    try:
        from agent_coord.client.http import ca_fingerprint, mill_ca_file, parse_mill_ca_pem

        ca = mill_ca_file()
        if ca.is_file():
            pem = parse_mill_ca_pem(ca.read_text(encoding="utf-8"))
            fp = ca_fingerprint(pem or "") if pem else ""
            if fp:
                return path + "&ca=" + fp
    except Exception:
        pass
    return path

def mint_key(

    *,

    label: str = "",

    ttl: str | int | None = None,

    created_by: str = "",

    token: str | None = None,

    sync_legacy: bool = True,

) -> dict[str, Any]:

    """Mint an invite key onto the board. Plaintext token printed once.

    Unset/empty ttl defaults to 24h (keys should always expire).

    Explicit 0/never remains an Admin escape (no expiry).

    """

    if ttl is None or (isinstance(ttl, str) and not str(ttl).strip()):

        ttl = DEFAULT_INVITE_TTL

    ttl_s, expires = parse_ttl(ttl)

    plain = (token or secrets.token_urlsafe(24)).strip()

    key_id = _new_key_id()

    digest = _digest(plain)

    lab = (label or "").strip()[:64]

    by = (created_by or "").strip()[:64]

    cn = _db()

    if cn is None:

        raise RuntimeError("office DB not reachable; run init first")

    try:

        cur = cn.cursor()

        try:

            _invite_sp(cur, "cmd_invite_create", (key_id, digest, lab, by, ttl_s))

            cn.commit()

        except Exception:

            cn.rollback()

            raise

        finally:

            cur.close()

    finally:

        cn.close()

    if sync_legacy:

        path = hash_path()

        path.parent.mkdir(parents=True, exist_ok=True)

        if not path.is_file() or not path.read_text(encoding="utf-8").strip():

            path.write_text(digest + "\n", encoding="utf-8")

            try:

                os.chmod(path, 0o600)

            except OSError:

                pass

    return {

        "ok": True,

        "key_id": key_id,

        "token": plain,

        "label": lab,

        "created_by": by,

        "ttl_seconds": ttl_s,

        "expires_at": expires.isoformat(sep=" ") if expires else None,

        "invite_path": _invite_path_with_ca(plain),

        "status": "pending",

    }







def enable_key(key_id: str) -> dict[str, Any]:

    """Host: enable a pending mill_invite so mill join can finish."""

    kid = (key_id or "").strip().lower()

    if not kid:

        return {"ok": False, "error": "key_id required"}

    cn = _db()

    if cn is None:

        return {"ok": False, "error": "office DB not reachable"}

    try:

        cur = cn.cursor()

        try:

            n = _invite_sp(cur, "cmd_invite_enable", (kid,))

            cn.commit()

        except Exception:

            cn.rollback()

            raise

        finally:

            cur.close()

    finally:

        cn.close()

    if n:

        return {"ok": True, "key_id": kid, "status": "active"}

    return {"ok": False, "key_id": kid, "error": "not pending (unknown, already enabled, or revoked)"}



def invite_status(token: str) -> str:

    """pending|active|expired|revoked|unknown for a plaintext invite token."""

    plain = (token or "").strip()

    if not plain:

        return "unknown"

    digest = _digest(plain)

    cn = _db()

    if cn is None:

        return "unknown"

    try:

        cur = cn.cursor(dictionary=True)

        try:

            cur.execute(

                "SELECT enabled_at, expires_at, revoked_at FROM mill_invite WHERE token_hash=%s LIMIT 1",

                (digest,),

            )

            row = cur.fetchone()

        finally:

            cur.close()

    except Exception:

        return "unknown"

    finally:

        try:

            cn.close()

        except Exception:

            pass

    if not row:

        return "unknown"

    if row.get("revoked_at"):

        return "revoked"

    exp = row.get("expires_at")

    if exp is not None and exp < _now():

        return "expired"

    if not row.get("enabled_at"):

        return "pending"

    return "active"


def list_keys(*, include_revoked: bool = True) -> list[dict[str, Any]]:

    """List invite keys with join counts and status (active|expired|revoked)."""

    cn = _db()

    if cn is None:

        return []

    now = _now()

    try:

        cur = cn.cursor(dictionary=True)

        try:

            cur.execute(

                "SELECT k.key_id, k.label, k.created_by, k.created_at, k.ttl_seconds, "

                "k.expires_at, k.revoked_at, k.enabled_at, "

                "COALESCE(j.joins, 0) AS joins "

                "FROM mill_invite k "

                "LEFT JOIN ("

                "  SELECT key_id, COUNT(*) AS joins FROM mill_invite_join GROUP BY key_id"

                ") j ON j.key_id = k.key_id "

                "ORDER BY k.created_at DESC"

            )

            rows = list(cur.fetchall() or [])

            cur.execute(

                "SELECT key_id, party, party_id, created FROM mill_invite_join ORDER BY created"

            )

            parties = {}

            for jr in cur.fetchall() or []:

                kid = str(jr.get("key_id") or "")

                created = jr.get("created")

                if hasattr(created, "isoformat"):

                    created = created.isoformat(sep=" ")

                parties.setdefault(kid, []).append({

                    "party": jr.get("party") or "",

                    "party_id": jr.get("party_id") or "",

                    "created": created or "",

                })

        finally:

            cur.close()

    except Exception:

        return []

    finally:

        try:

            cn.close()

        except Exception:

            pass

    out: list[dict[str, Any]] = []

    for row in rows:

        r = dict(row)

        revoked = r.get("revoked_at")

        exp = r.get("expires_at")

        if revoked:

            status = "revoked"

        elif exp is not None and exp < now:

            status = "expired"

        elif not r.get("enabled_at"):

            status = "pending"

        else:

            status = "active"

        if not include_revoked and status == "revoked":

            continue

        r["status"] = status

        r["parties"] = parties.get(str(r.get("key_id") or ""), [])

        for k in ("created_at", "expires_at", "revoked_at", "enabled_at"):

            v = r.get(k)

            if hasattr(v, "isoformat"):

                r[k] = v.isoformat(sep=" ")

        out.append(r)

    return out





def set_key_ttl(key_id: str, ttl: str | int | None) -> dict[str, Any]:

    kid = (key_id or "").strip().lower()

    if not kid:

        raise ValueError("key_id required")

    ttl_s, expires = parse_ttl(ttl)

    cn = _db()

    if cn is None:

        raise RuntimeError("office DB not reachable")

    try:

        cur = cn.cursor()

        try:

            n = _invite_sp(cur, "cmd_invite_ttl", (kid, ttl_s))

            cn.commit()

        except Exception:

            cn.rollback()

            raise

        finally:

            cur.close()

    finally:

        cn.close()

    if not n:

        raise ValueError(f"key {kid} not found or revoked")

    return {

        "ok": True,

        "key_id": kid,

        "ttl_seconds": ttl_s,

        "expires_at": expires.isoformat(sep=" ") if expires else None,

    }







def revoke_key(key_id: str) -> dict[str, Any]:

    """Revoke a key and list the parties that joined via it."""

    kid = (key_id or "").strip().lower()

    if not kid:

        raise ValueError("key_id required")

    cn = _db()

    if cn is None:

        raise RuntimeError("office DB not reachable")

    humans: list[str] = []

    agents: list[str] = []

    try:

        cur = cn.cursor()

        try:

            n = _invite_sp(cur, "cmd_invite_revoke", (kid,))

            cur.execute(

                "SELECT party, party_id FROM mill_invite_join WHERE key_id=%s",

                (kid,),

            )

            for party, party_id in cur.fetchall() or []:

                if party == "human":

                    humans.append(party_id)

                elif party == "agent":

                    agents.append(party_id)

            cn.commit()

        except Exception:

            cn.rollback()

            raise

        finally:

            cur.close()

    finally:

        cn.close()

    if not n:

        raise ValueError(f"key {kid} not found or already revoked")

    return {

        "ok": True,

        "key_id": kid,

        "status": "revoked",

        "cohort_humans": humans,

        "cohort_agents": agents,

        "note": "TTL expire is enforced on door check; revoke drops the key.",

    }





def record_join(key_id: str, party: str, party_id: str) -> bool:

    """Attribute a human/agent join to an invite key (idempotent)."""

    kid = (key_id or "").strip().lower()

    who = (party_id or "").strip()

    kind = (party or "human").strip().lower()

    if not kid or not who:

        return False

    if kind not in ("human", "agent"):

        kind = "human"

    cn = _db()

    if cn is None:

        return False

    try:

        cur = cn.cursor()

        try:

            _invite_sp(cur, "cmd_invite_join_record", (kid, kind, who))

            cn.commit()

            return True

        except Exception:

            cn.rollback()

            return False

        finally:

            cur.close()

    finally:

        try:

            cn.close()

        except Exception:

            pass





def ensure_ootb_invite(*, created_by: str = "installer") -> dict[str, Any]:

    """OOTB: mint default invite key if none active; installer is default admin."""

    who = (created_by or "installer").strip() or "installer"

    active = [k for k in list_keys() if k.get("status") == "active"]

    if active:

        row = dict(active[0])

        row["token"] = None

        row["invite_path"] = "/?invite=<existing-active-key>"

        row["minted"] = False

        row["admin"] = who

        return row

    minted = mint_key(label="ootb", created_by=who, ttl="30d", sync_legacy=True)

    minted["minted"] = True

    minted["admin"] = who

    return minted





def board_packet() -> dict[str, Any]:

    """Wall Admin / CLI status: keys + security ladder + OIDC stub + network."""

    from agent_coord.server.netbind import network_packet



    m = mode()

    keys = list_keys()

    active_n = sum(1 for k in keys if k.get("status") == "active")

    if m == "path" and active_n <= 1:

        ladder = "solo"

    elif m in ("directory", "iam"):

        ladder = "company"

    else:

        ladder = "office"

    issuer = (_setting("directory_issuer") or "").strip()

    return {

        "door": m,

        "ladder": ladder,

        "keys": keys,

        "active_keys": active_n,

        "oidc": {

            "stub": True,

            "enabled": False,

            "provider": provider(),

            "protocol": protocol(),

            "issuer": issuer,

            "client_id": (_setting("directory_client_id") or "").strip(),

            "connect": "disabled",

            "note": "Company directory - coming later; use invite keys today",

            "providers": ["okta", "entra", "google"],

        },

        "notes": {

            "ttl": "Mint defaults to 24h when unset. Expired keys fail door check. Set/extend via invite --ttl KEY 7d (0/never = Admin escape).",

            "revoke": "invite --revoke KEY revokes the key and humans who joined via it.",

            "cli": (

                "invite [--door path|invite] [--rotate] [--mint [--ttl 7d] [--label X]] "

                "[--list] [--revoke KEY] [--ttl KEY DURATION] [--join KEY --party human|agent PARTY] "

                "[--lan-only on|off]"

            ),

            "https": "HTTPS only - plain HTTP redirects/denied. No cleartext convenience mode.",

        },

        "network": network_packet(),

    }





def set_door(kind: str = "", *, rotate: bool = False) -> dict[str, Any]:

    """Set path|invite. Rotate mints a new token (required the first time invite is on)."""

    from agent_coord.config import save_config, settings



    want = (kind or mode() or "path").strip().lower()

    if want in ("token", "link"):

        want = "invite"

    if want in ("entra", "oidc", "ad", "ldap"):

        want = "directory"

    if want in ("mill-iam",):

        want = "iam"

    if want not in _MODES:

        raise ValueError("door must be path, invite, directory, or iam")

    s = settings()

    data = {

        "host": s["host"],

        "port": int(s["port"]),

        "user": s["user"],

        "password": s["password"],

        "database": s["database"],

        "node": s.get("node") or "",

        "dashboard_bind": s["dashboard_bind"],

        "dashboard_port": int(s["dashboard_port"]),

        "door": want,

        "directory_kind": s.get("directory_kind") or "entra",

        "directory_issuer": s.get("directory_issuer") or "",

        "directory_client_id": s.get("directory_client_id") or "",

        "directory_logout_url": s.get("directory_logout_url") or "",

        "lan_only": s.get("lan_only") or "0",

    }

    written = save_config(data)

    token = None

    key_row = None

    hashed = hash_path().is_file() and len(hash_path().read_text(encoding="utf-8").strip()) == 64

    if rotate or (want == "invite" and not hashed and not any(k.get("status") == "active" for k in list_keys())):

        try:

            key_row = mint_key(label="rotated" if rotate else "ootb", created_by="door", sync_legacy=True)

            token = key_row.get("token")

            hashed = True

        except Exception:

            token = mint()

            hashed = True

    path = _invite_path_with_ca(token) if token else "/?invite=<token>"

    return {

        "door": want,

        "config_path": str(written),

        "hash_set": hashed,

        "token": token,

        "key": key_row,

        "invite_path": path if want == "invite" else "/",

        "board": board_packet() if want == "invite" else None,

        "note": {

            "invite": (

                "invite: missing/wrong/expired/revoked token is 404. Writes still need a mill session token. "

                "Re-run install wall so mill-wall (nginx TLS) gates / when door=invite. "

                "Keys: invite --mint / --list / --revoke / --ttl."

            ),

            "directory": (

                "directory: human or agent token checked against directory_issuer. "

                "Empty issuer is not armed (still path). Groups map to mill roles. Admin is the mill admin role."

            ),

            "iam": (

                "iam: same issuer check as directory, for an office with no company directory. "

                "Cloud IAM stays on the VM. It is not this door."

            ),

        }.get(want, "path: house default, no login. LAN/VPN is the wall."),

    }





def invite_from_request(path: str, headers) -> str:

    """Query ?invite=, X-Mill-Invite, Bearer, or factory-door cookie."""

    qs = parse_qs(urlparse(path).query)

    raw = ((qs.get("invite") or [""])[0] or "").strip()

    if raw:

        return raw

    hdr = (headers.get("X-Mill-Invite") or "").strip()

    if hdr:

        return hdr

    auth = (headers.get("Authorization") or "").strip()

    if auth.lower().startswith("bearer "):

        return auth[7:].strip()

    for part in (headers.get("Cookie") or "").split(";"):

        key, _, val = part.strip().partition("=")

        if key == COOKIE:

            return val.strip()

    return ""





def key_id_from_request(path: str, headers) -> str:

    qs = parse_qs(urlparse(path).query)

    raw = ((qs.get("invite_key") or [""])[0] or "").strip()

    if raw:

        return raw

    hdr = (headers.get("X-Mill-Invite-Key") or "").strip()

    if hdr:

        return hdr

    for part in (headers.get("Cookie") or "").split(";"):

        key, _, val = part.strip().partition("=")

        if key == COOKIE_KEY:

            return val.strip()

    return ""





def strip_invite_query(path: str) -> str:

    parsed = urlparse(path)

    qs = parse_qs(parsed.query, keep_blank_values=True)

    qs.pop("invite", None)

    query = urlencode(qs, doseq=True)

    out = parsed.path or "/"

    if query:

        out += "?" + query

    return out





def set_cookie_header(token: str) -> str:

    return f"{COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=2592000"





def set_key_cookie_header(key_id: str) -> str:

    return f"{COOKIE_KEY}={key_id}; Path=/; HttpOnly; SameSite=Lax; Max-Age=2592000"





def logout_url() -> str:

    """Host directory_logout_url when it is an http(s) URL. Empty otherwise."""

    raw = (_setting("directory_logout_url") or "").strip()

    if not raw or any(ch.isspace() for ch in raw):

        return ""

    from urllib.parse import urlsplit

    parts = urlsplit(raw)

    if parts.scheme not in ("http", "https") or not parts.netloc:

        return ""

    return raw





def signout_href() -> str:

    """Logout URL for a directory or iam door. Invite, path, and ip have none."""

    if mode() not in ("directory", "iam"):

        return ""

    return logout_url()





def clear_session_headers() -> list[tuple[str, str]]:

    dead = "Path=/; HttpOnly; SameSite=Lax; Max-Age=0"

    return [

        ("Set-Cookie", f"{COOKIE}=; {dead}"),

        ("Set-Cookie", f"{COOKIE_KEY}=; {dead}"),

    ]





_SIGNOUT_OFF = 'class="wall-signout" data-signout="off"'

_SIGNOUT_ON = 'class="wall-signout" data-signout="on"'





def board_signout(html: str) -> str:

    """Show the wall Sign out control only when this office has a logout URL."""

    if not signout_href():

        return html

    return html.replace(_SIGNOUT_OFF, _SIGNOUT_ON, 1)

