# GET/POST /api/admin/invites (alias /api/invites). mill_invite book + mint_seat.
from __future__ import annotations

from typing import Any, Callable

from agent_coord.const import CONST_ADMIN, CONST_ROSTER
from agent_coord.helpers.errors import CoordError
from agent_coord.server.admin import door as door_mod
from agent_coord.client.tokens import token_hash
from agent_coord.server.records import join as rec_join
from agent_coord.server.admin.guard import (
    is_human_admin,
    is_role_admin,
    require_invite_seat_mint,
)


def board() -> dict[str, Any]:
    return door_mod.board_packet()


def _human_token_ok(cn, owner: str, token: str) -> bool:
    if not (token or "").strip():
        return False
    return rec_join.token_matches(cn, owner, token_hash(token))


def _human_bearer_ok(cn, token: str) -> bool:
    """True when this bearer hashes to a signed-in human (directory cookie)."""
    raw = (token or "").strip()
    if not raw:
        return False
    try:
        from agent_coord.server.records import human as rec_human

        return bool(rec_human.open(cn, token_hash(raw)))
    except Exception:
        return False


def _seat_human_ok(cn, owner: str, body_token: str, session_token: str) -> bool:
    """Desk badge in the body, or the human sign-in already checked at the door."""
    if body_token and _human_token_ok(cn, owner, body_token):
        return True
    if session_token and _human_bearer_ok(cn, session_token):
        return True
    if body_token and body_token != session_token and _human_bearer_ok(cn, body_token):
        return True
    return False


def _verified_admin_desk(cn, *tokens: str) -> str:
    """Desk proven by a bearer/seat token whose hash is on file AND is Admin.

    Identity comes from the credential, never from a body `owner` string (#sec
    S-4). Returns the Admin desk name, or "" when no token proves one.
    """
    for tok in tokens:
        t = (tok or "").strip()
        if not t:
            continue
        try:
            desk = rec_join.desk_for_token_hash(cn, token_hash(t))
        except Exception:
            desk = ""
        if not desk:
            continue
        try:
            if is_role_admin(cn, desk):
                return desk
        except Exception:
            pass
    return ""


def _admin_human(cn, token: str) -> bool:
    """True when this bearer is a signed-in human whose role is Admin."""
    raw = (token or "").strip()
    if not raw or not _human_bearer_ok(cn, raw):
        return False
    try:
        return is_human_admin(cn, token_hash(raw))
    except Exception:
        return False


def _mutate_ok(cn, *, token: str, session: str) -> bool:
    """A door-mutating action is allowed for an Admin desk bearer or a signed-in
    Admin human (directory cookie). The body `owner` is never proof (#sec S-4).
    """
    if _verified_admin_desk(cn, token, session):
        return True
    return any(_admin_human(cn, tok) for tok in (session, token))


ADMIN_REQUIRED = (
    f"admin invites: {CONST_ROSTER} {CONST_ADMIN} bearer or a signed-in "
    "human is required; a body owner name is not proof of identity"
)


def list_invites(*, office: Callable, token: str = "", session: str = "") -> dict[str, Any]:
    """GET /api/admin/invites: the key list and door state, Admin only.

    The read carries key ids, labels and who minted them, so it takes the same
    Admin check as a mutation (#sec S-5).
    """
    with office() as c:
        if not _mutate_ok(c._cn, token=token, session=session):
            raise CoordError(ADMIN_REQUIRED)
    return door_mod.board_packet()


def post_invites(
    data: dict[str, Any], *, office: Callable, human_token: str = ""
) -> dict[str, Any]:
    action = str(data.get("action") or "").strip().lower()
    owner = str(data.get("owner") or data.get("src") or "")
    token = str(data.get("token") or "")
    session = str(human_token or "")

    # One-seat agent invite (ready immediately). Gate: Admin always;
    # human badge only when trust=high. Door mint/list/enable unchanged below.
    if action in ("mint_seat", "seat"):
        desk = str(data.get("desk") or data.get("target") or "").strip()
        if not desk:
            raise CoordError("mint_seat: desk required")
        with office() as c:
            human_ok = _seat_human_ok(c._cn, owner, token, session)
            # #sec S-4: the Admin check runs on the desk the credential proves,
            # never on the body owner string.
            require_invite_seat_mint(
                c._cn, _verified_admin_desk(c._cn, token, session), human_ok=human_ok
            )
            from agent_coord.server.admin.seats import mint_seat, resolve_seat_roster

            proj = resolve_seat_roster(c._cn, desk, str(data.get("project") or ""))
            return mint_seat(
                c._cn,
                desk=desk,
                project=proj,
                created_by=owner or "wall",
            )

    # Nest invite book totals: COUNT(mill_invite), COUNT(mill_invite_join).
    # Same gate as mint_seat. Action kept as seat_count (alias invite_count).
    if action in ("seat_count", "count_seats", "invite_count"):
        with office() as c:
            human_ok = _seat_human_ok(c._cn, owner, token, session)
            require_invite_seat_mint(
                c._cn, _verified_admin_desk(c._cn, token, session), human_ok=human_ok
            )
            from agent_coord.server.admin.seats import seat_count

            return seat_count(c._cn)

    # #sec S-4: door-mutating actions authenticate from the real session or a
    # bearer that resolves to an Admin desk, never from the body `owner` string.
    if action in (
        "mint",
        "create",
        "revoke",
        "ttl",
        "set_ttl",
        "door",
        "join",
        "network",
        "lan_only",
        "set_lan_only",
        # #sec S-5: the read-only list takes the same Admin check.
        "list",
        "board",
        "",
    ):
        with office() as c:
            if not _mutate_ok(c._cn, token=token, session=session):
                raise CoordError(ADMIN_REQUIRED)
    if action in ("mint", "create"):
        return door_mod.mint_key(
            label=str(data.get("label") or ""),
            ttl=data.get("ttl"),
            created_by=owner or "wall",
        )
    if action == "revoke":
        return door_mod.revoke_key(
            str(data.get("key_id") or data.get("key") or ""),
        )
    if action in ("ttl", "set_ttl"):
        return door_mod.set_key_ttl(
            str(data.get("key_id") or data.get("key") or ""),
            data.get("ttl"),
        )
    if action == "door":
        return door_mod.set_door(
            str(data.get("door") or ""),
            rotate=bool(data.get("rotate")),
        )
    if action == "join":
        ok = door_mod.record_join(
            str(data.get("key_id") or ""),
            str(data.get("party") or "human"),
            str(data.get("party_id") or ""),
        )
        return {"ok": ok}
    if action in ("network", "lan_only", "set_lan_only"):
        from agent_coord.server.netbind import set_lan_only

        raw = data.get("lan_only", data.get("value", data.get("on")))
        if raw is None:
            raise CoordError("network: pass lan_only true|false")
        if isinstance(raw, str):
            on = raw.strip().lower() in ("1", "true", "yes", "on")
        else:
            on = bool(raw)
        bind = data.get("bind")
        return set_lan_only(on, bind=str(bind) if bind else None)
    if action in ("list", "board", ""):
        return door_mod.board_packet()
    raise CoordError(f"unknown action {action}")
