# One-seat agent invite mint. Ready immediately (no door pending/enable).
from __future__ import annotations

import base64
import re
import secrets
from typing import Any
from urllib.parse import urlencode

from agent_coord.client.tokens import token_hash
from agent_coord.helpers.errors import CoordError
from agent_coord.helpers.ident import desk_name
from agent_coord.server.records import join as rec_join


def _stored_desk(value: str) -> str:
    return desk_name(value)


def wall_base() -> str:
    """HTTPS Wall origin for invite_url. mill_url or preferred host."""
    from agent_coord.config import settings

    base = str(settings().get("mill_url") or "").strip().rstrip("/")
    if base.startswith("http://"):
        base = "https://" + base[len("http://") :]
    if base:
        return base
    try:
        from agent_coord.server.netbind import preferred_office_host

        host = (preferred_office_host() or "").strip()
    except Exception:
        host = ""
    if host:
        if host.startswith("http"):
            return host.rstrip("/")
        return "https://" + host
    return ""


def invite_url_for(
    *,
    desk: str,
    seat: str,
    base: str | None = None,
    project: str = "",
    ca_pem: str = "",
) -> str:
    """https://<wall>/welcome?desk=&seat=&project=&pem=

    pem= is base64 of the CA PEM so join needs no /ca.crt fetch (#253).
    """
    origin = (base if base is not None else wall_base()).rstrip("/")
    who = _stored_desk(desk)
    fields = {"desk": who, "seat": seat}
    proj = (project or "").strip()
    if proj:
        fields["project"] = proj
    pem = (ca_pem or "").strip()
    if pem:
        if not pem.endswith("\n"):
            pem += "\n"
        if "BEGIN CERTIFICATE" in pem and "END CERTIFICATE" in pem:
            fields["pem"] = base64.b64encode(pem.encode("utf-8")).decode("ascii")
    qs = urlencode(fields)
    path = "/welcome?" + qs
    if origin:
        return origin + path
    return path



_SAFE_ORIGIN = re.compile(r"^https://[A-Za-z0-9._:-]+$")
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9._:-]+$")
_SHELL_META = set("&|;<>^$`%!")


def _mill_ca_pem() -> str:
    """CA certificate bytes. Empty when the office has no PEM yet."""
    try:
        from agent_coord.install.host import mill_ca_crt

        path = mill_ca_crt()
        if not path.is_file():
            return ""
        text = path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""
    if "BEGIN CERTIFICATE" not in text or "END CERTIFICATE" not in text:
        return ""
    return text + "\n"


def mint_seat_secret() -> str:
    """Seat value that does not start with '-', so argparse can take it (#145)."""
    for _ in range(8):
        seat = secrets.token_urlsafe(24)
        if seat and not seat.startswith("-"):
            return seat
    return "s" + secrets.token_urlsafe(23)



def resolve_seat_roster(cn, desk: str, wanted: str = "") -> str:
    """Seat roster for mint: explicit wanted, else the desk's one non-Office roster.

    Any live roster works (0.7.0), a former role included. Office and unknown refuse (#252).
    """
    from agent_coord.helpers.errors import CoordError
    from agent_coord.server.api.mill.rpc import _require_live_project, _seat_roster

    from agent_coord.server.admin.guard import is_admin_roster, is_office_roster

    who = (wanted or "").strip()
    if who:
        if is_office_roster(cn, who):  # #722: also after an Admin renamed Office
            raise CoordError("invite-seat: Office is not a seat roster; name another roster")
        # #674: a seat never lands on Admin; Admin is member-add on the office host.
        if is_admin_roster(cn, who):
            raise CoordError(
                "invite-seat: Admin is not a seat roster; Admin is granted only by "
                "member-add on the office host"
            )
        return _require_live_project(cn, who, "invite-seat")
    seated = _seat_roster(cn, desk)
    if not seated or is_office_roster(cn, seated) or is_admin_roster(cn, seated):
        raise CoordError("invite-seat: roster required")
    return _require_live_project(cn, seated, "invite-seat")


def mint_seat(
    cn,
    *,
    desk: str,
    project: str = "the-mill",
    created_by: str = "",
    doing: str = "invited",
    mill_url: str | None = None,
) -> dict[str, Any]:
    """Mint one agent seat + welcome invite URL. Book stores token_hash only."""
    who_raw = (desk or "").strip()
    if not who_raw:
        raise CoordError("mint_seat: desk required")
    who = _stored_desk(who_raw)
    proj = (project or "").strip() or "the-mill"
    seat = mint_seat_secret()
    digest = token_hash(seat)
    rows = rec_join.upsert(cn, proj, who, "", digest, (doing or "invited")[:64])
    got = rows[0] if rows else {}
    registered = _stored_desk(str(got.get("owner") or who))
    try:
        from agent_coord.server.records import member as rec_member

        rec_member.put_office(cn, registered)
    except Exception:
        pass
    did = got.get("desk_id")
    try:
        desk_id = int(did) if did is not None and str(did).strip() != "" else 0
    except (TypeError, ValueError):
        desk_id = 0
    pem = _mill_ca_pem()
    url = invite_url_for(
        desk=registered, seat=seat, base=mill_url, project=proj, ca_pem=pem
    )
    out: dict[str, Any] = {
        "ok": True,
        "desk": registered,
        "seat": seat,
        "invite_url": url,
        "status": "ready",
        "created_by": (created_by or "").strip()[:64],
        "project": proj,
    }
    if desk_id:
        out["desk_id"] = desk_id
    if pem:
        out["ca"] = pem
    return out

def seat_count(cn) -> dict[str, Any]:
    """Nest invite book totals for wall-ui Host strip.

    invites = COUNT(*) FROM mill_invite
    joined  = COUNT(*) FROM mill_invite_join
    Display shape: joined (joined) / invites (invited).
    Not agent seat / join.token_hash totals.
    """
    cur = cn.cursor()
    try:
        cur.execute("SELECT COUNT(*) FROM mill_invite")
        invites = int((cur.fetchone() or [0])[0] or 0)
        cur.execute("SELECT COUNT(*) FROM mill_invite_join")
        joined = int((cur.fetchone() or [0])[0] or 0)
        return {"ok": True, "invites": invites, "joined": joined}
    except Exception:
        return {"ok": True, "invites": 0, "joined": 0}
    finally:
        cur.close()


def seat_known(token: str) -> bool:
    """True when plaintext matches a join.token_hash. Not a mill_invite key."""
    plain = (token or "").strip()
    if not plain:
        return False
    digest = token_hash(plain)
    if len(digest) != 64:
        return False
    from agent_coord.server.admin.door import _db

    cn = _db()
    if cn is None:
        return False
    try:
        cur = cn.cursor()
        try:
            cur.execute(
                "SELECT token_hash FROM seat WHERE token_hash=%s LIMIT 1",
                (digest,),
            )
            row = cur.fetchone()
        finally:
            cur.close()
    except Exception:
        return False
    finally:
        try:
            cn.close()
        except Exception:
            pass
    if not row:
        return False
    got = row[0] if not isinstance(row, dict) else row.get("token_hash")
    got = str(got or "")
    if len(got) != 64:
        return False
    return secrets.compare_digest(got, digest)
