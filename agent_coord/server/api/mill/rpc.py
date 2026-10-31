# -*- coding: utf-8 -*-
"""POST /mill/v1/<command> - mill-wall opens MySQL; laptops never do.

Access token is the mill here token (GitLab PAT / PyPI token): Authorization
Bearer or PRIVATE-TOKEN. mill-wall does not write ~/.mill/session for laptops.
"""
from __future__ import annotations

import logging
import re
import secrets
import threading
from collections import OrderedDict
from datetime import datetime
from typing import Any

from agent_coord.const import (
    ACTIVITY_TYPES,
    CONST_ADMIN,
    CONST_DESK,
    CONST_HOLD,
    CONST_LABEL,
    CONST_MAIL,
    CONST_OFFICE,
    CONST_ROSTER,
    CONST_TODO,
    CONST_TREE,
)
from agent_coord.helpers.errors import CoordError
from agent_coord.helpers.ident import desk as desk_stem
from agent_coord.helpers.ident import desk_name, slug

_log = logging.getLogger("mill.rpc")


def _stored(value: Any) -> str:
    """Catalog name as stored."""
    return str(value or "").strip()


def _live_projects(cn) -> list[str]:
    """Live project names. Office first, then the rest by name."""
    from agent_coord.server.records import name as rec_name

    names: list[str] = []
    # Rosters only, in id order: the catalog minus desks, labels, trees, files (F23).
    for raw in rec_name.live_roster_names(cn) or []:
        nm = _stored(raw)
        if nm:
            names.append(nm)
    office = _office(cn)
    names.sort(key=lambda s: (s != office, s.lower()))
    return names


def _office(cn) -> str:
    """Stored name of the Office roster, id 1 (an Admin may rename it, #722)."""
    from agent_coord.server.admin.guard import office_name

    return office_name(cn)


def _project_alias(cn, project: str) -> str:
    """The protocol name Office means roster id 1, whatever it is called now (#722)."""
    if project and project.casefold() == CONST_OFFICE.casefold() and cn is not None:
        return _office(cn)
    return project


def _require_live_project(cn, project: str, command: str) -> str:
    """Refuse an unknown, retired, or empty project before any write (#237)."""
    from agent_coord.helpers.projects import project_refusal
    from agent_coord.server.records import name as rec_name

    who = _stored(project)
    # One indexed lookup on the happy path; the roster list only for the refusal (F23).
    if who and cn is not None:
        got = rec_name.live_roster(cn, who)
        if got is not None and _stored(got) == who:
            return who
    err = project_refusal(command, who, _live_projects(cn))
    if err:
        raise CoordError(err)
    return who


def _check_roster(cn, command: str, name: str) -> None:
    """Refuse a sender roster that is not a live roster (#241). Any roster works (0.7.0)."""
    from agent_coord.server.records import name as rec_name

    if not name:
        return
    if len(name) > 64 or rec_name.get(cn, name, CONST_ROSTER) is None:
        raise CoordError(f"{command}: no such roster {name[:64]}")


def _seat_roster(cn, desk: str) -> str:
    """Sender roster from the seat: the desk's single non-Office roster (Admin counts), else Office."""
    from agent_coord.server.records import member as rec_member

    office = _office(cn)
    if not desk:
        return office
    names = {str(r.get("slot") or "") for r in (rec_member.select(cn, "", desk, CONST_ROSTER) or [])}
    names.discard("")
    names.discard(office)
    return names.pop() if len(names) == 1 else office


def _connect_roster(cn, desk: str, name: str) -> str:
    """Sender roster named at mill connect ROSTER DESK (#337); the desk must be on it."""
    from agent_coord.server.records import member as rec_member

    want = _project_alias(cn, _stored(name))
    office = _office(cn)
    if want == office:
        return office
    names = {_stored(r.get("slot")) for r in (rec_member.select(cn, "", desk, CONST_ROSTER) or [])}
    if want not in names:
        raise CoordError(
            f"mail: {desk} is not on roster {want[:64]}, the roster this connect named; "
            "pass --roster NAME, or connect on a roster this desk is on"
        )
    return want


def _live_dest_kind(cn, name: str) -> str:
    """desk or roster already in the name table. Desk wins when the bare string is shared."""
    from agent_coord.server.records import name as rec_name

    for kind in (CONST_DESK, CONST_ROSTER):
        if rec_name.get(cn, name, kind) is not None:
            return kind
    return ""

from agent_coord.server.book import Book
from agent_coord.client.tokens import token_hash

OPEN_COMMANDS = frozenset({"join"})

# Keys the server alone may set on a request body. A client must never supply
# them: `host` is the office-host (loopback) marker the Admin gate trusts, and
# any `_`-prefixed key is server-internal (for example the redaction marker).
# Both HTTP and /ws strip these from client input before a handler runs; the
# server re-sets `host` from the verified transport peer where it applies.
_SERVER_ONLY_KEYS = frozenset({"host"})


def _strip_server_only(body: dict[str, Any]) -> None:
    """Drop server-only keys a client tried to inject (trusted-field spoofing)."""
    if not isinstance(body, dict):
        return
    for key in list(body.keys()):
        if key in _SERVER_ONLY_KEYS or (isinstance(key, str) and key.startswith("_")):
            body.pop(key, None)


def _join_credential(body: dict[str, Any], token: str) -> str:
    """The credential a join presents: the Bearer, else the body token (seat)."""
    cand = (token or "").strip()
    if cand:
        return cand
    return str(body.get("token") or "").strip()


def _require_join_authorized(c: Book, body: dict[str, Any], token: str) -> None:
    """Gate new-desk minting by the office door (#sec S-2).

    A path or ip office is open by configuration, so door.check returns True and
    join needs no credential (the existing open-house behavior). An invite,
    directory, or iam office requires either a valid door credential (invite key
    or human/agent bearer) or a pre-provisioned seat token. The loopback office
    host (installer) always may join: mark_host set host=True from the socket
    peer, never from client args.
    """
    if body.get("host") is True:
        return
    cand = _join_credential(body, token)
    from agent_coord.server.admin import door

    try:
        if door.check(cand):
            return
    except Exception:
        pass
    if cand:
        try:
            from agent_coord.server.admin.seats import seat_known

            if seat_known(cand):
                return
        except Exception:
            pass
    from agent_coord.client.session_errors import SESSION_JOIN_DENIED

    raise CoordError(SESSION_JOIN_DENIED)


def _require_live_ws(owner: str | None) -> None:
    """HTTP desk-acting commands are refused. Commands run as JSON RPC on sitting /ws.

    owner is unused; kept so existing monkeypatches stay compatible.
    """
    from agent_coord.client.session_errors import SESSION_WS_RPC_ONLY

    raise CoordError(SESSION_WS_RPC_ONLY)



def _poke(
    c: Book, typ: str, nid: Any, command: str, *, owner: str | None = None, fresh: bool = False
) -> None:
    """Same HTTPS request: SELECT watchers -> Hub. Hint = type.upper(). Never raises.

    owner is the acting desk: it gets no hint for its own change; other watchers
    still do. fresh stamps the hint time now, for a write (a label) that leaves
    the activity row's time alone (0.7.4, card #280).
    """
    if not nid:
        return
    from agent_coord.server.records.db import after_commit

    # #818: inside a --doing request the pokes wait for its commit.
    after_commit(c._cn, lambda: _poke_now(c, typ, nid, command, owner=owner, fresh=fresh))


def _poke_now(c: Book, typ: str, nid: Any, command: str, *, owner: str | None, fresh: bool) -> None:
    try:
        from agent_coord.server.push import fanout

        when = ""
        if fresh:
            from agent_coord.server.records.db import scalar

            when = str(scalar(c._cn, "SELECT NOW(6)") or "")
        fanout(c._cn, typ, int(nid), typ.upper(), skip_desk=_stored(owner or ""), when=when)
    except Exception as e:
        try:
            from agent_coord.server.push import mill_admin_alert

            mill_admin_alert(c._cn, f"{command} fanout: {e}", command=command)
        except Exception:
            pass


def _todo_nid(c: Book, project: str, need: str) -> int:
    from agent_coord.server.records import todo as rec_todo

    try:
        hit = rec_todo.find(c._cn, project, slug(str(need or "")))
        return int(hit["id"]) if hit else 0
    except Exception:
        return 0


def _issue_here(c: Book, body: dict[str, Any]) -> dict[str, Any]:
    """Mint a mill access token. Laptop stores it; mill-wall stores the hash."""
    from agent_coord.server.records import join as rec_join

    project_raw = str(body.get("project") or "").strip()
    owner_raw = str(body.get("owner") or "").strip()
    if not project_raw or not owner_raw:
        raise CoordError("mill here: project and owner required")
    project = _project_alias(getattr(c, "_cn", None), _stored(project_raw))
    owner = _stored(owner_raw)
    role_raw = str(body.get("role") or "").strip()
    from agent_coord.server.admin.guard import is_admin_roster

    cn = getattr(c, "_cn", None)
    if role_raw and is_admin_roster(cn, role_raw):
        raise CoordError(
            f"{CONST_ROSTER} {CONST_ADMIN} is granted only by member-add on the office host"
        )
    role_s = _stored(role_raw) if role_raw else ""
    if role_s:
        from agent_coord.config import mill_catalog_open
        from agent_coord.server.records import name as rec_name

        rs = _stored(role_s)
        if rec_name.get(c._cn, rs, CONST_ROSTER) is None and not mill_catalog_open(CONST_ROSTER):
            raise CoordError("limited-trust: mill Admin mill roster NAME NAME --yes")
    doing = str(body.get("doing") or "present")[:64]
    # Join posts Office as a placeholder; the seat's one roster replaces it.
    # mill connect with no roster sends Office on purpose and keeps it.
    office = _office(c._cn)
    if project == office and body.get("placeholder"):
        seated = _seat_roster(c._cn, owner)
        # An Admin desk keeps Admin; its join row sits on Office (#674).
        if seated and seated != office and not is_admin_roster(cn, seated):
            project = seated
    # #674: join never adds a desk to the reserved Admin roster, in any spelling
    # the book resolves to it. mill_join_upsert refuses the same in SQL.
    if is_admin_roster(cn, project):
        _log.warning("join refused: project resolves to the Admin roster (desk %s)", owner[:64])
        raise CoordError(
            f"join: {CONST_ROSTER} {CONST_ADMIN} is not a join roster; "
            f"{CONST_ROSTER} {CONST_ADMIN} is granted only by member-add on the office host"
        )
    token = str(body.get("token") or "").strip() or secrets.token_urlsafe(24)
    rows = rec_join.upsert(
        c._cn,
        _stored(project),
        _stored(owner),
        _stored(role_s) if role_s else "",
        token_hash(token),
        doing,
    )
    got = rows[0] if rows else {}
    if got.get("id"):
        _poke(c, "doing", got.get("id"), "join")
    registered = _stored(_stored(str(got.get("owner") or owner)))
    try:
        from agent_coord.server.records import member as rec_member

        rec_member.put_office(c._cn, owner)
    except Exception:
        pass
    did = got.get("desk_id")
    try:
        desk_id = int(did) if did is not None and str(did).strip() != "" else 0
    except (TypeError, ValueError):
        desk_id = 0
    out = {
        "group_id": project,
        "owner": registered,
        "role": role_s,
        "doing": doing,
        "token": token,
    }
    if desk_id:
        out["desk_id"] = desk_id
    delivery = body.get("delivery")
    if isinstance(delivery, dict):
        # #618: after the upsert, so the seat token has authenticated this desk.
        out["wake"] = _join_delivery(c, registered, delivery)
    return out


def _join_delivery(c: Book, desk: str, delivery: dict[str, Any]) -> dict[str, Any]:
    """Set the desk's delivery on its join row (#618). websocket, or webhook URL + its own key.

    The webhook is test-fired once, and stored only on a 2xx; a failed test
    leaves the old state and raises the fix. The same URL and key again are a
    no-op (no second test POST). No answer, log line or error carries the URL
    path or the key.
    """
    from agent_coord.server import wake
    from agent_coord.server.records import join as rec_join

    mode = str(delivery.get("mode") or "").strip().lower()
    if mode == "websocket":
        rec_join.wake_off(c._cn, desk)
        return {"webhook": "off", "delivery": "websocket"}
    if mode != "webhook":
        raise CoordError("join: delivery is websocket or webhook")
    # Card 836: no --wake-on arms addressed; a room copy waits for the next connect.
    wake_on = str(delivery.get("wake_on") or wake.ADDRESSED).strip().lower()
    if wake_on not in wake.WAKE_ON:
        raise CoordError("join: --wake-on is addressed or all")
    try:
        url, host = wake.check_url(str(delivery.get("url") or ""))
        key = wake.normalize_key(str(delivery.get("key") or ""))
    except wake.WakeRefused as e:
        raise CoordError(str(e)) from None
    if rec_join.wake_target(c._cn, desk) == (url, key):
        # Same routine: no second test POST. #628: a new --wake-on alone is stored.
        if str(rec_join.wake_state(c._cn, desk).get("wake_on") or wake.ADDRESSED) != wake_on:
            rec_join.wake_arm(c._cn, desk, url, key, wake_on=wake_on)
        return {"webhook": "armed", "host": host, "test": "unchanged", "wake_on": wake_on}
    got = wake.test_fire(url, key, desk, roster=wake.desk_roster(c._cn, desk))
    if not got["ok"]:
        raise CoordError("join: webhook not armed: " + str(got.get("fix") or "test POST failed"))
    rec_join.wake_arm(c._cn, desk, url, key, wake_on=wake_on)
    return {"webhook": "armed", "host": host, "test": got["status"], "wake_on": wake_on}


def _h_inbox(c: Book, body: dict[str, Any], project: str, owner: str | None) -> Any:
    from agent_coord.server.records import mail as rec_mail
    from agent_coord.server.records.name import by_id as name_by_id

    lim = int(body.get("limit") or 100)
    if not owner:
        raise CoordError("inbox: owner required")
    desk_raw = str(body.get("dst") or owner or "").strip()
    if not desk_raw:
        raise CoordError("inbox: dest required")
    desk = _stored(desk_raw)
    self_desk = _stored(owner)
    if desk != self_desk:
        raise CoordError(
            "inbox: dest must be the Bearer desk (cannot read/mark another desk's mail)"
        )
    # A fetch does not mark handled. A crash after this read loses nothing (#195).
    unread_only = not bool(body.get("all"))

    # The page is cut and ordered in SQL from mail_to idx_desk_unread: unread is
    # the newest `lim` unread, newest first (card 846); --all is the newest `lim`, newest
    # first. Bodies come on the same rows.
    page = max(1, lim or 100)
    kept = rec_mail.inbox(c._cn, _stored(desk), all_mail=not unread_only, limit=page)
    mids = [int(r["id"]) for r in kept]
    dests = rec_mail.tos_by_id(c._cn, mids) if mids else {}
    crumbs_by = rec_mail.tree_crumbs_batch(c._cn, mids) if mids else {}
    out = []
    for rec in kept:
        mid = int(rec["id"])
        pub = rec_mail.public_mail(
            dict(rec), dests.get(mid) or [], crumbs=crumbs_by.get(mid) or None
        )
        out.append(pub)
    return out


def _truthy(v: Any) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return bool(v)


def _peek_int(raw: str) -> int | None:
    """A todo id written as digits, or a leading minus and digits. Else None."""
    s = (raw or "").strip()
    if s.isdigit() or (len(s) > 1 and s[0] == "-" and s[1:].isdigit()):
        return int(s)
    return None


def _deleted_hint(c: Book, needle: int) -> str:
    """Suffix when the card is gone but its activity row is stamped deleted."""
    cn = getattr(c, "_cn", None)
    if cn is None or type(cn).__module__ == "unittest.mock":
        return ""
    try:
        from agent_coord.server.records.db import scalar

        gone = scalar(
            cn,
            "SELECT deleted FROM activity WHERE type = 'todo' AND id = %s",
            (needle,),
        )
    except Exception:
        return ""
    if gone is None:
        return ""
    return "; it is deleted"


def _todo_miss_hint(
    c: Book, project: str, needle: int, with_done: bool, want_st: str, show_fix: bool
) -> str:
    """Suffix for a numeric peek that missed. Empty when the id is simply absent."""
    from agent_coord.lib.observe import is_fixture_project
    from agent_coord.server.records import todo as rec_todo

    if int(needle) <= 0:
        return ""
    try:
        wide = list(rec_todo.page(c._cn, _stored(project), "", card_id=int(needle)) or [])
    except Exception:
        return ""
    hit = next((r for r in wide if int(r.get("id") or 0) == needle), None)
    if not hit:
        return ""
    aff = str(hit.get("roster") or "")
    st = str(hit.get("status") or "open")
    if is_fixture_project(aff) and not show_fix:
        return "; pass --fixtures"
    if st == "done" and not with_done:
        return "; pass --done"
    if want_st and st != want_st:
        return "; status is %s" % st
    return ""


TODO_ROSTERS_MAX = 200


def _todo_card(r: dict, project_label: str, st: str, fields: dict) -> dict:
    card = {
        "project_id": project_label,
        "need_id": fields["need_id"],
        "id": r.get("id"),
        "status": st,
        "detail": fields["detail"],
        "progress": fields["progress"],
        "volunteer": _stored(r.get("assigned") or ""),
        "asker": _stored(r.get("creator") or ""),
        # Plan and labels for client grouping (#274).
        "tree": _stored(r.get("tree") or "") or None,
        "labels": _json_names(r.get("labels")),
    }
    # #867: the acceptance line and the last ship/done evidence, when set.
    if r.get("done_when"):
        card["done_when"] = str(r["done_when"])
    if r.get("evidence"):
        card["evidence"] = str(r["evidence"])
    # #330: notes land in detail. A progress token that was never set is left
    # out, so no field in the reply is always empty. #818: cards have no title.
    if not card["progress"]:
        del card["progress"]
    return card


def _mine_cards(cards: list[dict], owner: str | None) -> list[dict]:
    """todo --mine (#667): the cards the desk holds or that wear its focus label.

    The client still ranks and trims them (focus.order_mine); the wall only stops
    sending every other card on the board.
    """
    desk = _stored(owner or "")
    if not desk:
        return []
    return [r for r in cards if r.get("volunteer") == desk or desk in (r.get("labels") or [])]


def _todo_many(
    c: Book, body: dict[str, Any], want_st: str, with_done: bool, show_fix: bool, owner: str | None = None
) -> dict:
    """Board for several rosters in one read: the cards each per-roster `todo` call
    would list, in the given roster order. {"cards": [...], "rosters": n}.
    With mine, only the sitting desk's cards (#667)."""
    from agent_coord.lib.observe import is_fixture_project
    from agent_coord.server.records import todo as rec_todo

    raw = body.get("rosters")
    names: list[str] = []
    for n in raw if isinstance(raw, list) else []:
        nm = _stored(str(n or ""))
        if nm and nm not in names:
            names.append(nm)
    if len(names) > TODO_ROSTERS_MAX:
        raise CoordError("todo: at most %d rosters in one read" % TODO_ROSTERS_MAX)
    rank = {nm: i for i, nm in enumerate(names)}
    rows = [
        r
        for r in rec_todo.page(c._cn, "", want_st, hide_done=not with_done)
        if _stored(r.get("roster") or "") in rank
    ]
    if not show_fix:
        rows = [r for r in rows if not is_fixture_project(str(r.get("roster") or ""))]
    rows.sort(key=lambda r: rank[_stored(r.get("roster") or "")])
    cards = []
    for r in rows:
        st = r.get("status") or "open"
        fields = rec_todo.unpack(r.get("body") or "", r.get("id"))
        cards.append(_todo_card(r, _stored(r.get("roster") or ""), st, fields))
    if _truthy(body.get("mine")):
        cards = _mine_cards(cards, owner)
    return {"cards": cards, "rosters": len(names)}


def _h_todo(c: Book, body: dict[str, Any], project: str, owner: str | None) -> Any:
    from agent_coord.lib.observe import is_fixture_project
    from agent_coord.server.records import todo as rec_todo

    raw_need = str(body.get("need") or body.get("need_id") or "").strip()
    want = slug(raw_need) if raw_need else ""
    # agent-ux 1215: honor --status and --done like the CLI help says.
    # --status X lists only X; --done adds done cards; default hides done.
    try:
        want_st = rec_todo.require_status(str(body.get("status") or ""), allow_empty=True)
    except ValueError as e:
        raise CoordError(f"todo: {e}") from e
    with_done = _truthy(body.get("done")) or want_st == "done"
    show_fix = _truthy(body.get("fixtures"))
    if "rosters" in body and not raw_need:
        # One read for `mill todo` and `mill todo --all` (was one call per roster).
        return _todo_many(c, body, want_st, with_done, show_fix, owner)
    out = []

    def _visible(rows: list[dict]) -> list[dict]:
        # t-<8 hex> rows stay off the board unless --fixtures, same as the wall.
        if show_fix:
            return rows
        return [r for r in rows if not is_fixture_project(str(r.get("roster") or ""))]

    # The filters run in SQL: a numeric peek reads that card by id first; a plain
    # board leaves done cards in the database unless --done.
    id_hit = False
    rows: list[dict] = []
    if raw_need.isdigit() and int(raw_need) > 0:
        hits = _visible(list(rec_todo.page(c._cn, _stored(project), want_st, card_id=int(raw_need))))
        if hits:
            rows = hits
            id_hit = True
    if not id_hit:
        rows = list(
            rec_todo.page(c._cn, _stored(project), want_st, hide_done=not with_done and not want)
        )
    # A missing project is a refusal. An empty board for a real project stays [] (#226).
    who_proj = _stored(project)
    if who_proj and not rows:
        from agent_coord.server.records import name as rec_name

        known = rec_name.get(c._cn, who_proj, CONST_ROSTER) is not None
        if not known:
            raise CoordError("todo: unknown project %s" % who_proj)
    if not id_hit:
        rows = _visible(rows)
    for r in rows:
        st = r.get("status") or "open"
        if want_st and st != want_st:
            continue
        # A named peek shows a done card. The board list still hides done (#168).
        if st == "done" and not with_done and not want and not id_hit:
            continue
        fields = rec_todo.unpack(r.get("body") or "", r.get("id"))
        if want and not id_hit and slug(str(fields.get("need_id") or "")) != want:
            continue
        out.append(_todo_card(r, project, st, fields))
    # A3 Nest SoR: single-need peek marks nest=1 when card is on a TREE.
    if want and len(out) == 1:
        try:
            from agent_coord.server.records import tree as rec_tree

            tid = int(out[0].get("id") or 0)
            if tid and rec_tree.on_tree(c._cn, "todo", tid):
                out[0]["nest"] = 1
        except Exception:
            pass
    # #186: a peek that names nothing is a refusal, not an empty list.
    if raw_need and not id_hit and not out:
        number = _peek_int(raw_need)
        if number is not None and number >= 0:
            hint = _todo_miss_hint(c, project, number, with_done, want_st, show_fix)
            if not hint:
                hint = _deleted_hint(c, number)
            raise CoordError("todo: no card %s in %s%s" % (number, project, hint))
        if number is not None:
            raise CoordError("todo: no card %s in %s" % (number, project))
        raise CoordError("todo: no card %s in %s" % (raw_need, project))
    if _truthy(body.get("mine")) and not raw_need:
        out = _mine_cards(out, owner)
    return out


def _connected_limit(body: dict[str, Any]) -> int | None:
    """Positive connected_limit, or None when that key was not sent.

    Released clients send limit=10 on every connected call, including history.
    That key is ignored here so a plain connected list stays whole. Below 1
    on the new key is a refusal.
    """
    if "connected_limit" not in body or body.get("connected_limit") in (None, ""):
        return None
    try:
        n = int(body.get("connected_limit"))
    except (TypeError, ValueError):
        raise CoordError("connected: --limit must be at least 1")
    if n < 1:
        raise CoordError("connected: --limit must be at least 1")
    return n


def _heartbeat_rank(view: dict[str, Any]) -> tuple[int, float]:
    """Newest heartbeat first. One key type, so mixed rows still sort."""
    hb = view.get("heartbeat")
    if isinstance(hb, datetime):
        return (0, -hb.timestamp())
    return (1, 0.0)


def _h_session(c: Book, body: dict[str, Any], project: str, owner: str | None) -> Any:
    """`mill connected` (#274 word; RPC session). #818 PR B: what each desk is
    doing, on which item, since when, and who is waiting on it.

    ROSTER is optional (none = desks active in the last day; --all every desk;
    --desk X one desk). --history lists past doing entries instead, a page at a time.
    --limit N (card 647) is the wire key connected_limit: at most N live desks,
    newest heartbeat first. A body that only carries limit (a released client)
    is not capped and is not refused on --history.
    """
    from agent_coord.server.records import doing as rec_doing

    roster = _stored(str(body.get("project") or "").strip())
    desk = _stored(str(body.get("desk") or "").strip())
    if desk:
        from agent_coord.server.records import name as rec_name

        if rec_name.get(c._cn, desk, CONST_DESK) is None:
            raise CoordError(f"connected: no desk {desk[:64]}")
    elif roster:
        _require_live_project(c._cn, roster, "connected")
    limit = _connected_limit(body)
    page = _doing_page(body.get("page"))
    if body.get("history"):
        if limit is not None:
            raise CoordError("connected: --limit is for the live list, not --history")
        return _doing_history(c, body, desk)
    if body.get("since") or page:
        raise CoordError("connected: --since and --page go with --history")
    views = [_desk_view(r, roster, by) for r, by in _doing_rows(
        rec_doing.now(c._cn, desk, roster, bool(body.get("all")))
    )]
    if limit is None:
        return views
    views.sort(key=_heartbeat_rank)
    return views[:limit]


def _doing_rows(rows: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, list]]]:
    """Group mill_doing_now's parts: (desk row, {letters, cards, blocked desks})."""
    extra: dict[str, dict[str, list]] = {}
    desks: list[dict[str, Any]] = []
    for r in rows:
        part = str(r.get("part") or "")
        if part == "desk":
            desks.append(r)
        elif part in ("letter", "card", "blocked"):
            extra.setdefault(str(r.get("desk") or ""), {"letter": [], "card": [], "blocked": []})[part].append(r)
    return [(d, extra.get(str(d.get("desk") or ""), {"letter": [], "card": [], "blocked": []})) for d in desks]


def _age(seconds: Any) -> str:
    try:
        s = max(0, int(seconds))
    except (TypeError, ValueError):
        return ""
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    if s < 86400:
        return f"{s // 3600}h"
    return f"{s // 86400}d"


def _item(typ: Any, nid: Any) -> str | None:
    return f"{typ}-{int(nid)}" if typ and nid is not None else None


def _desk_view(r: dict[str, Any], roster: str, by: dict[str, list]) -> dict[str, Any]:
    from agent_coord.lib.observe import heartbeat_flags

    who = _stored(r.get("desk") or "")
    hb = r.get("heartbeat")
    alive, stale = heartbeat_flags(hb)
    text = str(r.get("text") or "")
    on = _item(r.get("on_type"), r.get("on_id"))
    ended = r.get("ended_at") is not None
    out: dict[str, Any] = {"owner": who, "heartbeat": hb, "alive": alive, "stale": stale}
    if roster:
        out["project_id"] = roster
    if text and not ended:
        # 0.8.0 wall read contract: every doing entry carries its act (a focus row here).
        out.update({"doing": text, "on": on, "age": _age(r.get("age_s")), "act": str(r.get("act") or "focus")})
        head = f'{who}: doing "{text}"' + (f" on {on}" if on else "") + f" ({out['age']})"
        # #822: what this entry is blocked on (fields on its own doing row).
        wait = _waiting_view(r.get("waiting_type"), r.get("waiting_id"), r.get("waiting_name"), r.get("waiting_why"))
        if wait:
            out["waiting_on"] = wait
            target = wait["on"][5:] if wait["on"].startswith("desk-") else wait["on"]
            head += f", waiting on {target}" + (f" ({wait['why']})" if wait["why"] else "")
    else:
        out["doing"] = ""
        if ended and r.get("now") is not None:
            out["idle"] = _age((r["now"] - r["ended_at"]).total_seconds())
        elif r.get("age_s") is not None:
            out["idle"] = _age(r.get("age_s"))
        last_text = str(r.get("last_text") or "")
        if last_text:
            out["last"] = {"doing": last_text, "on": _item(r.get("last_on_type"), r.get("last_on_id")),
                           "age": _age(r.get("last_age_s")), "ended_by": r.get("ended_by"),
                           "act": str(r.get("act") or "focus")}
        head = f"{who}: idle" + (f" {out['idle']}" if out.get("idle") else "")
        if last_text:
            head += f' (last: "{last_text}"' + (f" on {out['last']['on']}" if out["last"]["on"] else "") + ")"
    letters = [
        {"id": f"mail-{int(x['id'])}", "from": _stored(x.get("sender") or ""), "age": _age(x.get("age_s")),
         "asked": bool(x.get("asked"))}  # #820: always true here, a copy never waits
        for x in by["letter"]
    ]
    cards = [
        {"id": f"todo-{int(x['id'])}", "need": str(x.get("need") or ""), "roster": _stored(x.get("roster") or ""),
         "watchers": [w for w in str(x.get("watchers") or "").split(",") if w], "age": _age(x.get("age_s")),
         # #821: when it was claimed, office clock, like the history's at
         "claimed_at": str(x["claimed_at"])[:19] if x.get("claimed_at") is not None else None}
        for x in by["card"]
    ]
    # #822: desks whose current doing is blocked on this one (a read of their rows).
    blocked = [
        {"desk": _stored(x.get("waiter") or ""), "age": _age(x.get("age_s")),
         **(_waiting_view(x.get("waiting_type"), x.get("waiting_id"), who, x.get("waiting_why")) or {})}
        for x in by.get("blocked", [])
    ]
    n_letters = int(by["letter"][0].get("n") or 0) if by["letter"] else 0
    n_cards = int(by["card"][0].get("n") or 0) if by["card"] else 0
    n_blocked = int(by["blocked"][0].get("n") or 0) if by.get("blocked") else 0
    out["waiting_on_it"] = {
        "letters": {"n": n_letters, "newest": letters},
        "cards": {"n": n_cards, "newest": cards},
        "desks": {"n": n_blocked, "newest": blocked},
    }
    bits = []
    if n_letters:
        x = letters[0]
        bits.append(f"{n_letters} unanswered letter{'s' if n_letters != 1 else ''} (newest {x['id']} from {x['from']}, {x['age']})")
    if n_cards:
        x = cards[0]
        bits.append(f"{n_cards} watched card{'s' if n_cards != 1 else ''} it claimed (newest {x['id']} {x['need']}, {x['age']})")
    if n_blocked:
        x = blocked[0]
        bits.append(f"{n_blocked} desk{'s' if n_blocked != 1 else ''} blocked on it (newest {x['desk']} on {x['on']}, {x['age']})")
    out["line"] = head + ". Waiting on it: " + ("; ".join(bits) if bits else "nothing") + "."
    return out


def _doing_history(c: Book, body: dict[str, Any], desk: str, on: tuple[str, int] | None = None) -> dict[str, Any]:
    """`mill connected --history`: past doing entries, newest first, 50 a page.
    on keeps one item's entries (the Wall's card trail, GET /api/v1/doing/history?on=)."""
    from datetime import datetime

    from agent_coord.server.records import doing as rec_doing

    since_raw = str(body.get("since") or "").strip()
    since = None
    if since_raw:
        try:
            since = datetime.fromisoformat(since_raw.replace("T", " "))
        except ValueError:
            raise CoordError(
                f"connected --since: {since_raw[:40]} is not a date; say 2026-10-22 or '2026-10-22 18:00' (office clock)"
            ) from None
    page = _doing_page(body.get("page")) or 1
    size = DOING_PAGE
    rows = rec_doing.history(c._cn, desk, since.isoformat(sep=" ") if since else None, page, size,
                             on[0] if on else "", on[1] if on else None)
    total = int(rows[0].get("total") or 0) if rows else 0
    if not rows and page > 1:
        raise CoordError(f"connected --history --page {page}: past the last page")
    of = max(1, -(-total // size))
    block: dict[str, Any] = {"n": page, "of": of, "size": size, "entries": total}
    if page < of:
        block["next"] = f"--page {page + 1}"
    entries = []
    for r in rows:
        # Whichever came first: its own event (reply, pass or done, drop),
        # clock-out or reset (cleared), or a newer --doing.
        ends = [(r.get("ended_at"), "finished"), (r.get("cleared_at"), "cleared"), (r.get("replaced_at"), "newer")]
        hit = [(at, by) for at, by in ends if at is not None]
        how = min(hit, key=lambda x: x[0])[1] if hit else None
        entry = {
            "id": int(r["id"]),
            "desk": _stored(r.get("desk") or ""),
            "at": str(r.get("created") or "")[:19],
            "doing": str(r.get("text") or ""),
            "on": _item(r.get("on_type"), r.get("on_id")),
            "act": str(r.get("act") or "focus"),
            "roster": _stored(r.get("roster") or ""),
            "ended": how is not None,
            "ended_by": how,
            **({"waiting_on": w} if (w := _waiting_view(r.get("waiting_type"), r.get("waiting_id"),
                                                        r.get("waiting_name"), r.get("waiting_why"))) else {}),
        }
        # 0.8.0 Wall (letter 3227): move rows carry doing.evidence on the card trail.
        if r.get("evidence"):
            entry["evidence"] = str(r["evidence"])
        entries.append(entry)
    return {"history": entries, "page": block}


DOING_PAGE = 50
# 50 a page: five million entries. The book's offset, (page - 1) * 50, is an INT.
DOING_PAGE_MAX = 100000


def _doing_page(raw: Any) -> int:
    """The --history page: 0 when not given (None, "", or the CLI's 0), else an
    int or a string of ASCII digits from 1 to DOING_PAGE_MAX. Anything else
    (a bool, a float, "²" or "１" that str.isdigit() takes, a sign, an
    overflow) is refused, so no page ever reaches the book out of range."""
    if raw is None or raw == "" or (type(raw) is int and raw == 0):
        return 0
    n = -1
    if type(raw) is int:
        n = raw
    elif isinstance(raw, str) and raw.isascii() and raw.isdigit() and len(raw) <= 6:
        n = int(raw)
    if not 1 <= n <= DOING_PAGE_MAX:
        raise CoordError(f"connected --page: N is 1 to {DOING_PAGE_MAX}")
    return n
# #818 PR B: commands whose --doing writes a doing entry on the item they wrote.
DOING_COMMANDS = frozenset(
    {"send", "reply", "mark", "open", "claim", "unclaim", "assign", "pass", "note", "unpark", "hold", "drop", "score"}
)


def _doing_text(command: str, body: dict[str, Any]) -> str:
    """The --doing text this call carries, checked before the command runs.
    A --waiting-on (#822) is checked here too, so a bad one runs nothing."""
    raw = body.get("doing") if command in DOING_COMMANDS else None
    text = " ".join(str(raw).replace("\x00", "").split()) if raw is not None else ""
    if len(text) > 512:
        raise CoordError(f"{command}: --doing must be 1..512 characters; nothing stored")
    _doing_waiting(command, body, text)
    return text


_WAIT_ITEM = re.compile(r"^(mail|todo|hold)-(\d{1,19})$")


def _doing_waiting(command: str, body: dict[str, Any], text: str) -> tuple[str, str, str] | None:
    """#822 --waiting-on "WHAT [WHY]": what this doing is blocked on. WHAT is a
    desk, mail-ID, todo-ID or hold-ID; the rest is the reason. None when absent."""
    raw = " ".join(str(body.get("waiting_on") or "").replace("\x00", "").split())
    if not raw:
        return None
    if command not in DOING_COMMANDS or not text:
        raise CoordError(f"{command}: --waiting-on goes with --doing; nothing was changed")
    what, _, why = raw.partition(" ")
    if len(why) > 200:
        raise CoordError(f"{command}: --waiting-on reason must be 0..200 characters; nothing was changed")
    hit = _WAIT_ITEM.match(what.lower())
    if hit:
        return (hit.group(1), hit.group(2), why)
    if len(what) > 64:
        raise CoordError(f"{command} --doing refused: --waiting-on names no desk or item; nothing was changed")
    return ("desk", what, why)


def _waiting_view(typ: Any, nid: Any, name: Any, why: Any) -> dict[str, Any] | None:
    """{on, why} of a blocked-on: on is desk-NAME or TYPE-ID."""
    if not typ or nid is None:
        return None
    on = f"desk-{_stored(name or '')}" if typ == "desk" else f"{typ}-{int(nid)}"
    return {"on": on, "why": str(why or "")}


def _first_need(raw: Any) -> str:
    return slug(str(raw or "").split(",")[0].strip())


def _doing_item(c: Book, command: str, body: dict[str, Any], out: Any, project: str) -> tuple[str, int] | None:
    """(type, id) of the item this command wrote, or None."""
    res = out if isinstance(out, dict) else {}
    if command == "send":
        return ("mail", int(res["id"])) if res.get("id") else None
    if command == "reply":
        mid = int(body.get("mail_id") or body.get("id") or body.get("parent_id") or 0)
        return ("mail", mid) if mid else None
    if command == "mark":
        ids = res.get("ids") or []
        return ("mail", int(ids[0])) if ids else None
    if command in ("open", "claim", "unclaim", "assign", "pass", "note", "unpark"):
        if command == "open" and res.get("id"):
            return ("todo", int(res["id"]))
        from agent_coord.server.records import todo as rec_todo

        hit = rec_todo.find(c._cn, project, _first_need(body.get("need")))
        return ("todo", int(hit["id"])) if hit else None
    if command in ("hold", "drop"):
        if command == "hold" and not res.get("held"):
            return None
        if res.get("id"):
            return ("hold", int(res["id"]))
        from agent_coord.helpers.bounds import resource_name
        from agent_coord.server.records import hold as rec_hold

        got = rec_hold.peek(c._cn, _stored(project), resource_name(str(body.get("resource") or "")))
        return ("hold", int(got["id"])) if got.get("id") else None
    if command == "score":
        return ("score", int(res["id"])) if res.get("id") and not res.get("retired") else None
    return None


def _doing_finish(c: Book, command: str, body: dict[str, Any], out: Any, owner: str) -> None:
    """A pass (ship) or pass --done of a card, or a drop that frees a hold, without
    --doing ends the desk's own doing on that item. pass --back ends nothing.
    The command already stands; a failure here is logged."""
    from agent_coord.server.records import doing as rec_doing

    res = out if isinstance(out, dict) else {}
    if command == "pass":
        if str(body.get("step") or "ship").strip().lower() not in ("ship", "done"):
            return
        on_type = "todo"
        rows = res.get("results") if isinstance(res.get("results"), list) else [res]
        ids = [r.get("id") for r in rows if isinstance(r, dict) and r.get("ok") and r.get("id")]
    elif command == "drop":
        on_type = "hold"
        ids = [res.get("id")] if res.get("released") and res.get("id") else []
    else:
        return
    for nid in ids:
        try:
            rec_doing.finish(c._cn, _stored(owner), on_type, int(nid))
        except Exception as e:
            try:
                c._cn.rollback()
            except Exception:
                pass
            _log.warning("%s: doing finish not recorded for %s-%s: %s", command, on_type, nid, type(e).__name__)


def _doing_after(c: Book, command: str, body: dict[str, Any], out: Any, project: str, owner: str | None, text: str) -> Any:
    """The doing side of a command, inside the request that ran it.

    Without --doing, a pass or drop may write its finish row (_doing_finish).
    With --doing this runs inside _run_command's transaction: any refusal raises,
    and the command rolls back with its doing row (#818).
    """
    if not owner:
        return out
    if not text:
        if command in ("pass", "drop"):
            _doing_finish(c, command, body, out, owner)
        return out
    from agent_coord.server.records import doing as rec_doing

    res = out if isinstance(out, dict) else {}
    rows = res.get("results") if isinstance(res.get("results"), list) else []
    bad = [r for r in rows if isinstance(r, dict) and r.get("ok") is False]
    if bad:
        # A list command with --doing is all or nothing.
        b = bad[0]
        raise CoordError(f"{b.get('need') or 'an item'}: {str(b.get('error') or 'refused')[:160]}")
    item = _doing_item(c, command, body, out, project)
    if item is None:
        raise CoordError("no item was written, so no doing can be recorded")
    from agent_coord.server.records.db import retryable_db

    waiting = _doing_waiting(command, body, text)
    try:
        got = rec_doing.put(c._cn, _stored(owner), text, item[0], item[1], waiting)
    except CoordError:
        raise
    except Exception as e:
        if retryable_db(e):
            raise  # a deadlock, lock wait or dropped connection: request_tx runs it again
        raise CoordError(_sql_refusal(e) or "the doing could not be stored") from e
    if isinstance(out, dict):
        out = dict(out)
        out["doing_entry"] = {"id": int(got.get("id") or 0), "on": f"{item[0]}-{item[1]}"}
        if waiting:
            w_on = f"desk-{_stored(waiting[1])}" if waiting[0] == "desk" else f"{waiting[0]}-{int(waiting[1])}"
            out["doing_entry"]["waiting_on"] = {"on": w_on, "why": waiting[2]}
    if got.get("id"):
        _poke(c, "doing", got.get("id"), "doing", owner=owner)  # waits for the commit
    return out


def _run_command(c: Book, fn: Any, command: str, body: dict[str, Any], project: str, owner: str | None, text: str) -> Any:
    """Run a handler and its doing side.

    With --doing (#818) the command and its doing row are one transaction: both
    commit, or a refusal of either rolls both back and nothing is written; its
    pokes, letters and webhooks go out only after the commit. A deadlock, lock
    wait or dropped connection runs the whole request once more (request_tx);
    if that fails too the reply is the same "--doing refused ... nothing was
    changed".
    """
    if not (owner and text):
        out = fn(c, body, project, owner)
        return _doing_after(c, command, body, out, project, owner, text)
    from agent_coord.server.records.db import RequestRolledBack, request_tx

    def run() -> Any:
        out = fn(c, body, project, owner)
        return _doing_after(c, command, body, out, project, owner, text)

    from agent_coord.server.records.db import TRANSIENT_ERRNO, retryable_db, transient_errno

    try:
        return request_tx(c._cn, run)
    except RequestRolledBack as e:
        errno = transient_errno(e.cause)
        if errno is not None:
            msg = f"the book was busy ({TRANSIENT_ERRNO[errno]} {errno}) twice; try again"
        elif retryable_db(e.cause):
            msg = "the book connection failed twice; try again"
        else:
            msg = _sql_refusal(e.cause) or str(e.cause).split(":", 1)[-1].strip() or type(e.cause).__name__
        raise CoordError(f"{command} --doing refused: {msg[:160]}; nothing was changed") from e
    except CoordError as e:
        raise CoordError(f"{command} --doing refused: {e}; nothing was changed", sync=getattr(e, "sync", None)) from e


def _h_project(c: Book, body: dict[str, Any], project: str, owner: str | None) -> Any:
    """Read only. A live project returns the live list; anything else refuses (#237).

    dispatch fills an empty project with a default, so this reads the raw body.
    """
    who = _stored(str(body.get("project") or ""))
    command = str(body.get("for") or "connect").strip() or "connect"
    if command not in ("connect", "inbox", "hold"):
        command = "connect"
    _require_live_project(c._cn, who, command)
    return {"ok": True, "project": who, "projects": _live_projects(c._cn)}


def _h_here(c: Book, body: dict[str, Any], project: str, owner: str | None) -> Any:
    return _issue_here(c, body)


def _h_label(c: Book, body: dict[str, Any], project: str, owner: str | None) -> Any:
    from agent_coord.server.records import label as rec_label

    command = slug(str(body.get("verb") or ""))
    from agent_coord.client.outbound import canonical_command

    command = canonical_command(command)
    typ = str(body.get("type") or body.get("kind") or "")
    nid = int(body.get("id") or 0)
    if not nid and body.get("ref"):
        nid = _card_ref_id(c._cn, body, command)
    tag = str(body.get("label") or body.get("tag") or "")
    if command == "label":
        return rec_label.select(c._cn, typ, nid)
    if not typ or not nid or not tag:
        raise CoordError("mill label-add/remove: type id label required")
    # An unknown project refuses before the tag is touched (#245).
    _require_live_project(getattr(c, "_cn", None), project, command)
    if command == "label-add":
        # A new label is created on first use when trust allows (else Admin: mill create label NAME).
        from agent_coord.config import mill_catalog_open
        from agent_coord.server.records import name as rec_name
        from agent_coord.server.records.name import bare as _bare

        tag_b = _bare(tag, CONST_LABEL)
        if (
            0 < len(tag_b) <= 64
            and rec_name.get(c._cn, tag_b, CONST_LABEL) is None
            and mill_catalog_open(CONST_LABEL)
        ):
            rec_name.host_put(c._cn, tag_b, CONST_LABEL)
        rec = rec_label.put(c._cn, typ, nid, tag, body.get("ord"))
    else:
        rec = rec_label.delete(c._cn, typ, nid, tag)
        # A label that is not on the node is a refusal on the call, not ok (#245).
        if rec and str(rec[0].get("op") or "") == "not-removed":
            raise CoordError("label-remove: %s %s has no label %s" % (typ, nid, _stored(tag)))
    _poke(c, typ, nid, command, owner=owner, fresh=True)
    return rec


def _mail_role_admin(c: Book, project: str, owner: str | None, target: str, *, added: bool) -> None:
    """Tell the desk. Same send path as mill send, including the MAIL fanout."""

    text = (
        "You are an Admin on this office."
        if added
        else "You are no longer an Admin on this office."
    )
    _h_send(
        c,
        {"src": owner or "", "project": project, "dst": _stored(target), "body": text},
        project,
        owner,
    )



def _member_row(row: dict[str, Any] | None, *, desk: str, roster: str, op: str) -> dict[str, Any]:
    """Shape a member-add/remove row: desk, roster, op, and members (name.n), never bare n (#914)."""
    raw = dict(row or {})
    n = raw.pop("n", None)
    out: dict[str, Any] = {"desk": desk or _stored(raw.pop("desk", "")), "roster": roster, "op": op}
    raw.pop("op", None)
    for k, v in raw.items():
        if k == "desk":
            continue
        out[k] = v
    if n is not None:
        try:
            out["members"] = int(n)
        except (TypeError, ValueError):
            out["members"] = n
    return out


def _h_member(c: Book, body: dict[str, Any], project: str, owner: str | None) -> Any:
    from agent_coord.server.records import member as rec_member
    from agent_coord.client.outbound import canonical_command
    from agent_coord.server.admin.guard import require_admin

    command = canonical_command(str(body.get("verb") or ""))
    if command == "member":
        return rec_member.select(c._cn, "", owner or "")
    group = str(body.get("group") or "")
    if not group:
        raise CoordError("mill member-add/remove: group required")
    target = _stored(str(body.get("desk") or owner or ""))
    self_desk = _stored(owner or "")
    g = _stored(group)
    # #675: the name table matches any case or accent, so gate on the roster the
    # name resolves to, not the raw string. SQL refuses Admin on the generic path.
    from agent_coord.server.admin.guard import is_admin_roster

    admin_slot = bool(g) and is_admin_roster(getattr(c, "_cn", None), g)
    if admin_slot:
        g = CONST_ADMIN
    if admin_slot and not body.get("host"):
        raise CoordError(f"{CONST_ROSTER} {CONST_ADMIN}: office host only (loopback)")
    if admin_slot and command == "member-remove":
        require_admin(c._cn, owner or "")
    elif not admin_slot and target != self_desk:
        from agent_coord.server.admin.guard import require_admin_if_limited

        require_admin_if_limited(c._cn, owner or "")
    was_admin = False
    if admin_slot:
        from agent_coord.server.admin.guard import is_role_admin

        was_admin = is_role_admin(c._cn, target)
    slot_kind = CONST_ROSTER
    if command == "member-add":
        if admin_slot:
            rows = rec_member.put_admin(c._cn, target)
        else:
            rows = rec_member.put(c._cn, g, target, slot_kind)
        # Name the desk and roster, not only ids (#274).
        rows = [_member_row(r, desk=target, roster=g, op="added") for r in (rows or [])]
        if admin_slot and not was_admin:
            _mail_role_admin(c, project, owner, target, added=True)
    else:
        if admin_slot:
            rows = rec_member.delete_admin(c._cn, target)
        else:
            rows = rec_member.delete(c._cn, g, target, slot_kind)
        # #914: name the roster desk count as members (not bare n).
        rows = [_member_row(r, desk=target, roster=g, op="removed") for r in (rows or [])]
        if admin_slot and was_admin:
            _mail_role_admin(c, project, owner, target, added=False)
    return rows


def _seat_hash(c: Book, project: str, owner: str | None) -> str | None:
    """The acting desk's own seat token hash (0.8.0): sp_name_rename / sp_name_retire let a
    desk act on itself only with it. None when this request carried no bearer token."""
    tok = (getattr(c, "_tokens", None) or {}).get((project, _stored(owner or "")))
    return token_hash(tok) if tok else None


def _h_rename(c: Book, body: dict[str, Any], project: str, owner: str | None) -> Any:
    from agent_coord.server.records import name as rec_name
    from agent_coord.server.admin import catalog as admin_cat

    old = str(body.get("old") or "").strip()
    new = str(body.get("new") or "").strip()
    if body.get("yes"):
        rows = admin_cat.rename(c._cn, owner or "", body)
    else:
        old_d, new_d = _stored(old), _stored(new)
        if _stored(owner or "") != old_d:
            raise CoordError("mill rename: hash owns this desk only")
        rows = rec_name.rename(c._cn, old_d, new_d, "desk", by=old_d, by_hash=_seat_hash(c, project, owner))
    return rows


def _h_retire(c: Book, body: dict[str, Any], project: str, owner: str | None) -> Any:
    from agent_coord.server.records import name as rec_name
    from agent_coord.server.admin import catalog as admin_cat

    if str(body.get("name_type") or "").strip().lower() == "todo":
        return _each_need(body.get("need"), lambda n: _todo_retire_one(c, n, project, owner, back=False))
    raw = str(body.get("slug") or owner or "").strip()
    from agent_coord.server.records import hold as rec_hold

    if body.get("yes"):
        # Admin retire of a desk (or other name): when it is a desk, poke freed holds.
        slug_guess = _stored(str(body.get("slug") or body.get("name") or raw or ""))
        freed: list[int] = []
        if slug_guess:
            freed = [int(r["id"]) for r in (rec_hold.find(c._cn, desk=slug_guess, held=True) or []) if r.get("id")]
        rows = admin_cat.retire(c._cn, owner or "", body)
        _poke_freed_holds(c, freed, owner=owner)
    else:
        slug_s = _stored(raw)
        if _stored(owner or "") != slug_s:
            raise CoordError("mill retire: hash owns this desk only")
        freed = [int(r["id"]) for r in (rec_hold.find(c._cn, desk=slug_s, held=True) or []) if r.get("id")]
        rows = rec_name.retire(c._cn, slug_s, "desk", by=slug_s, by_hash=_seat_hash(c, project, owner))
        _poke_freed_holds(c, freed, owner=owner)
    return rows


def _h_roster(c: Book, body: dict[str, Any], project: str, owner: str | None) -> Any:
    from agent_coord.server.admin import catalog as admin_cat

    return admin_cat.put_roster(c._cn, owner or "", body)


def _h_label_name(c: Book, body: dict[str, Any], project: str, owner: str | None) -> Any:
    from agent_coord.server.admin import catalog as admin_cat

    rows = admin_cat.put_label_name(c._cn, owner or "", body)
    return rows


def _h_reclaim(c: Book, body: dict[str, Any], project: str, owner: str | None) -> Any:
    from agent_coord.server.admin import catalog as admin_cat

    if str(body.get("name_type") or "").strip().lower() == "todo":
        return _each_need(body.get("need"), lambda n: _todo_retire_one(c, n, project, owner, back=True))
    rows = admin_cat.reclaim(c._cn, owner or "", body)
    return rows


def _todo_retire_one(c: Book, raw_need: str, project: str, owner: str | None, *, back: bool) -> dict[str, Any]:
    """#19: mill retire todo ROSTER NEED (soft delete) or mill reclaim todo ROSTER NEED
    (undo). The asker or Admin. The card row, status, plan and history are kept."""
    from agent_coord.server.admin.guard import is_role_admin
    from agent_coord.server.records import todo as rec_todo

    word = "reclaim" if back else "retire"
    need = slug(str(raw_need or ""))
    hit = rec_todo.find_retired(c._cn, project, need) if back else rec_todo.find(c._cn, project, need)
    if hit is None:
        if back and rec_todo.find(c._cn, project, need) is not None:
            raise CoordError(f"{word} todo: {need} is not retired")
        raise CoordError(f"no such need: {project}/{need}")
    who = _stored(owner or "")
    ask = _desk_slug(c._cn, hit, "asker", "creator")
    if not who or (who != ask and not is_role_admin(c._cn, who)):
        raise CoordError(
            f"who-may: {word} todo is the asker ({ask}) or Admin"
            if ask
            else f"who-may: {word} todo is the asker or Admin; the card's asker does not resolve, so only Admin may"
        )
    try:
        if back:
            rec_todo.reclaim(c._cn, int(hit["id"]), who)
        else:
            rec_todo.retire(c._cn, int(hit["id"]), who)
    except CoordError:
        raise
    except Exception as e:
        msg = _sql_refusal(e)
        if msg:
            raise CoordError(msg) from e
        raise
    rec = {
        "ok": True,
        "need": need,
        "id": int(hit["id"]),
        "status": str(hit.get("status") or ""),
        "op": "reclaimed" if back else "retired",
    }
    _poke(c, "todo", rec["id"], word, owner=owner)
    return rec



def _poke_freed_holds(c: Book, hold_ids: list, *, owner: str | None) -> None:
    """Card 881 / H12-H13: when reset or retire frees holds, send the same hold
    hint a drop sends so a desk waiting on `watch hold NAME` wakes."""
    for hid in hold_ids:
        if hid:
            _poke(c, "hold", hid, "drop", owner=owner)


def _h_reset(c: Book, body: dict[str, Any], project: str, owner: str | None) -> Any:
    from agent_coord.server.records import hold as rec_hold
    from agent_coord.server.records import join as rec_join
    from agent_coord.server.admin.guard import require_admin

    require_admin(c._cn, owner or "")
    if body.get("dead") or body.get("prune_dead"):
        return rec_join.prune_dead(c._cn)
    who = str(body.get("desk") or "")
    if not who:
        raise CoordError("reset: desk required (or --dead to count seats with no token_hash)")
    # Card 881: capture hold ids before release so watchers get a drop-shaped hint.
    freed = [int(r["id"]) for r in (rec_hold.find(c._cn, desk=_stored(who), held=True) or []) if r.get("id")]
    rows = rec_join.reset(c._cn, _stored(project), _stored(who))
    _poke_freed_holds(c, freed, owner=owner)
    return {"ok": True, "reset": rows}


def _offline_warning(desks: list[str]) -> str:
    """One line listing desks that were not sitting (#152)."""
    tail = "(not on Hub / no recent join); mail is stored until they connect"
    if len(desks) == 1:
        return f"desk {desks[0]!r} looks offline {tail}"
    listed = ", ".join(repr(name) for name in desks)
    return f"desks {listed} look offline {tail}"


def _offline_dests(c: Book, project: str, resolved, via_roster) -> list[str]:
    """Explicit desk targets that look offline, in send order (#152).

    Not sitting in a push room and no seat touched in the last 10 minutes. One
    seat read for the whole dest list, by desk id (#176, F23). It used to be the
    project's full seat list (activity JSON per seat) scanned in python.
    """
    from datetime import datetime

    from agent_coord.server.records import join as rec_join
    from agent_coord.server.records import name as rec_name

    offline: list[str] = []
    looked: list[tuple[str, int | None]] = []
    for kind_a, to in resolved:
        if kind_a != CONST_DESK or to in via_roster:
            continue
        try:
            from agent_coord.server.push import HUB

            desk_id = rec_name.get(c._cn, to, CONST_DESK)
            room_key = desk_stem(to)
            if desk_id is not None and room_key and room_key in (HUB.rooms or {}):
                continue
            looked.append((to, None if desk_id is None else int(desk_id)))
        except Exception:
            pass
    seats: dict[int, Any] | None = None
    if any(d is not None for _to, d in looked):
        try:
            seats = rec_join.seen(c._cn, _stored(project), [d for _to, d in looked if d is not None])
        except Exception:
            seats = None
    for to, desk_id in looked:
        fresh = False
        if desk_id is not None:
            if seats is None:
                continue
            upd = seats.get(desk_id)
            if upd is not None:
                try:
                    age = (datetime.now() - upd.replace(tzinfo=None)).total_seconds()
                except Exception:
                    age = 99999
                fresh = age <= 600
        if not fresh:
            offline.append(_stored(to))
    return offline


def _h_send(
    c: Book, body: dict[str, Any], project: str, owner: str | None, *, room_only: set[str] | None = None
) -> Any:
    """Speak. Letter body + mail_tos[{deskId}].

    Accept mail_tos in body, or dst (comma To). Top-level roster /
    --roster = sender tag (mail.roster_id); omitted, the letter's
    project (the seat's project when the body names none, #241). A dest roster
    is not stored: mail_to is the dest name, opened, and receipt.
    To is *, a project name, project:role, a desk name, or a session role.
    Host room: body name/tree/room (CLI --name) is the plan name.
    Multi-To alone does NOT open a room. Room cast = sender ∪ mail_tos.

    room_only (#627) is set only by reply: the dests that get this letter as
    room members (reply-all), not by name. A client body cannot set it.
    """

    from agent_coord.client.outbound.addressing import parse_mail_to
    from agent_coord.server.records import mail as rec_mail
    from agent_coord.server.records import name as rec_name
    from agent_coord.server.records import tree as rec_tree

    src = _stored(str(body.get("src") or owner or ""))
    self_desk = _stored(owner or "")
    if self_desk and src and src != self_desk:
        raise CoordError(
            "send: src must be the Bearer desk (cannot forge From)"
        )
    if self_desk:
        src = self_desk
    raw = str(body.get("body") or "").strip()
    if not raw or len(raw) > 4096:
        raise CoordError("body must be 1..4096 chars")
    warnings: list[str] = []
    parent_t = str(body.get("parent_type") or body.get("type_a") or "")
    parent_id = int(body.get("parent_id") or body.get("id_a") or 0)
    # #254 follow-up: send has no --human-required; receipt is never set here.
    receipt = 0
    sender_roster = _stored(body.get("roster"))
    _check_roster(c._cn, "send", sender_roster)
    if not str(body.get("project") or "").strip():
        # #337: the roster named at connect is the default; an explicit --roster wins.
        cr = _stored(body.get("connect_roster"))
        project = _connect_roster(c._cn, src, cr) if cr and not sender_roster else _seat_roster(c._cn, src)

    # resolved: (dst_kind, stored dest name). dst_kind is desk, project, or role.
    resolved: list[tuple[str, str]] = []
    seen_to: set[str] = set()
    unknown = (
        "is not in the name table "
        "(fix the owner name; offline desks still get mail if they exist)"
    )

    raw_tos = body.get("mail_tos")
    if isinstance(raw_tos, list) and raw_tos:
        for item in raw_tos:
            if isinstance(item, str):
                desk_raw = item
            elif isinstance(item, dict):
                desk_raw = (
                    item.get("deskId")
                    or item.get("desk")
                    or item.get("dst")
                    or ""
                )
            else:
                raise CoordError("send: mail_tos items must be deskId or {deskId, roster?}")
            to = _stored(desk_raw)
            if not to:
                raise CoordError("send: mail_tos entry needs deskId")
            said = str(item.get("kind") or "").strip().lower() if isinstance(item, dict) else ""
            if said:
                # send desk|roster NAME: the word must match the name's type (#274).
                if said not in (CONST_DESK, CONST_ROSTER):
                    raise CoordError(f"send: {said!r} is not desk or roster")
                if rec_name.get(c._cn, to, said) is not None:
                    dst_kind = said
                else:
                    other = CONST_ROSTER if said == CONST_DESK else CONST_DESK
                    if rec_name.get(c._cn, to, other) is not None:
                        raise CoordError(f"send: {to} is a {other}, not a {said}; say: send {other} {to}")
                    raise CoordError(f"send: no {said} {to}")
            else:
                dst_kind = _live_dest_kind(c._cn, to)
            if not dst_kind:
                raise CoordError(f"send: the desk {to!r} {unknown}")
            key = f"{dst_kind}:{to}"
            if key in seen_to:
                continue
            seen_to.add(key)
            resolved.append((dst_kind, to))
    else:
        addrs = parse_mail_to(str(body.get("dst") or ""), project_id=project)
        if not addrs:
            raise CoordError("send: To required")
        for addr in addrs:
            d = addr["dst"]
            kind_a = addr.get("kind") or "desk"
            if kind_a == "star":
                dst_kind, to = CONST_ROSTER, _stored(project)
            elif kind_a == CONST_ROSTER:
                dst_kind, to = CONST_ROSTER, _stored(d)
            else:
                to = _stored(d)
                if rec_name.get(c._cn, to, CONST_DESK) is not None:
                    dst_kind = CONST_DESK
                elif rec_name.get(c._cn, to, CONST_ROSTER) is not None:
                    # A bare To that names a live roster (no hardcoded role list, 0.7.0).
                    dst_kind = CONST_ROSTER
                else:
                    raise CoordError(f"send: the desk {to!r} {unknown}")
            key = f"{dst_kind}:{to}"
            if key in seen_to:
                continue
            seen_to.add(key)
            resolved.append((dst_kind, to))

    if not resolved:
        raise CoordError("send: To required")

    # A roster To that holds the sender: mail its other members and say so (#274).
    # mail_to has no roster column, so the member desks are the same rows the roster gives.
    notes: list[str] = []
    via_roster: set[str] = set()
    if src:
        from agent_coord.server.records import member as rec_member

        expanded: list[tuple[str, str]] = []
        seen_desks = {to for k, to in resolved if k == CONST_DESK}
        for dst_kind, to in resolved:
            if dst_kind != CONST_ROSTER:
                expanded.append((dst_kind, to))
                continue
            members = [
                _stored(str(r.get("desk") or ""))
                for r in (rec_member.select(c._cn, to, "", CONST_ROSTER) or [])
                if str(r.get("desk_type") or CONST_DESK) == CONST_DESK
            ]
            members = [m for m in members if m]
            if src not in members:
                # Always say where the sender stands on a roster send (ux12).
                notes.append(f"sender: not a member of roster {to}; it went to its {len(members)} member(s)")
                expanded.append((dst_kind, to))
                continue
            others = [m for m in members if m != src]
            if not others:
                notes.append(f"sender: included; you ({src}) are the only member of roster {to}; the letter goes to you")
                expanded.append((dst_kind, to))
                continue
            notes.append(f"sender: excluded; you ({src}) are on roster {to} and were left out; it went to its {len(others)} other member(s)")
            for m in others:
                if m not in seen_desks:
                    seen_desks.add(m)
                    via_roster.add(m)
                    expanded.append((CONST_DESK, m))
        resolved = expanded

    rec_name.ensure_roster(c._cn, project, CONST_ROSTER)
    for dst_kind, to in resolved:
        if dst_kind == CONST_ROSTER:
            rec_name.ensure_roster(c._cn, to, dst_kind)

    # Room name already taken: refuse before the letter is written, and name the fix.
    if not (parent_t and parent_id):
        _send_room_free(c, body)

    # One mail row; first dest via insert; remaining via mill_mail_to_put.
    first_kind, first_to = resolved[0]
    # #867: the sender roster goes in the insert (no follow-up UPDATE).
    rows = rec_mail.insert(
        c._cn,
        _stored(sender_roster or project),
        _stored(src),
        first_to,
        raw,
        receipt=receipt,
        dst_kind=first_kind,
    )
    mid = int(rows[0]["id"]) if rows else 0
    if not mid:
        raise CoordError("send: mail insert returned no id")
    for dst_kind, to in resolved[1:]:
        rec_mail.to_put(
            c._cn, mid, _stored(project), to, receipt=receipt, dst_kind=dst_kind
        )

    if room_only:
        # #818 D1: store the wake's split. A room member that is not named is copied.
        rec_mail.to_copied(c._cn, mid, room_only)

    if rec_mail.dest_count(c._cn, mid) < 1:
        raise CoordError(f"send: mail {mid} has empty mail_to (orphan refused)")

    dest_rows = rec_mail.to_list(c._cn, mid)

    tree_rows = None
    room = False
    if parent_t and parent_id:
        tree_rows = rec_tree.add(c._cn, parent_t, parent_id, "mail", mid)
    else:
        # Host lock: room only when --name. Multi-To alone = plain mail.
        room_raw = str(
            body.get("name") or body.get("tree") or body.get("room") or ""
        ).strip()
        if room_raw:
            tree_name = slug(room_raw)
            try:
                tree_rows = rec_tree.create(c._cn, tree_name, "mail", mid)
            except Exception as e:
                msg = str(e).lower()
                if "tree exists" in msg:
                    raise CoordError(_room_exists_text(c, tree_name)) from e
                raise
            room = True

    # Offline warn for explicit desk targets. One line for the whole list (#152).
    offline = _offline_dests(c, project, resolved, via_roster)
    if offline:
        warnings.append(_offline_warning(offline))

    crumbs = rec_mail.tree_crumbs(c._cn, mid) if (parent_t and parent_id) or room else {}
    created = None
    if rows:
        created = rows[0].get("updated") or rows[0].get("created")
    rec = rec_mail.public_mail(
        {
            "id": mid,
            "created": created,
            "sender": _stored(src),
            # mill_mail_insert stamps the project when no --roster;
            # echo what the letter carries, not null.
            "sender_roster": sender_roster or _stored(project),
            "body": raw,
        },
        dest_rows,
        crumbs=crumbs or None,
    )
    if room:
        rec["room"] = True
    if warnings:
        rec["warnings"] = warnings
    if notes:
        rec["note"] = "; ".join(notes)
    try:
        from agent_coord.server.mail_push import push_mail

        push_mail(c._cn, int(mid), room_only=room_only)
    except Exception as e:
        try:
            from agent_coord.server.push import mill_admin_alert

            mill_admin_alert(c._cn, f"mail fanout: {e}", command="send")
        except Exception:
            pass
    return rec


def _room_exists_text(c: Book, tree_name: str) -> str:
    """send --room on a taken room: say how to post there (reply to its root)."""
    from agent_coord.server.records import tree as rec_tree

    name = _stored(tree_name)
    nodes = rec_tree.select(c._cn, name) or []
    mails = [n for n in nodes if str(n.get("type") or "") == CONST_MAIL and int(n.get("id") or 0)]
    if mails:
        root = min(mails, key=lambda n: (int(n.get("lft") or 0), int(n.get("id") or 0)))
        return f"send: room '{name}' exists; post in it with: mill reply {int(root['id'])} --body-file PATH"
    return f"send: room '{name}' exists (not a mail room); pick another --room"


def _send_room_free(c: Book, body: dict[str, Any]) -> None:
    from agent_coord.server.records import tree as rec_tree

    room_raw = str(body.get("name") or body.get("tree") or body.get("room") or "").strip()
    if not room_raw:
        return
    name = slug(room_raw)
    if rec_tree.select(c._cn, name):
        raise CoordError(_room_exists_text(c, name))


def _mail_reader(c: Book, mail_id: int, owner: str | None) -> bool:
    """True when this desk is on the letter or its room, or Admin (#sec S-3).

    Gates changing who else is on a letter (mill add|remove mail:ID OTHER).
    Reading is open to every seated desk (#672). Admin, or a room participant:
    any desk that sent or received this letter or (when it is on a room TREE)
    any letter on that room. For an off-tree letter that is exactly its sender
    and its recipients.
    """
    from agent_coord.server.admin.guard import is_role_admin

    me = _stored(owner or "")
    if not me:
        return False
    try:
        if is_role_admin(c._cn, owner or ""):
            return True
    except Exception:
        pass
    from agent_coord.server.records import mail as rec_mail

    return rec_mail.room_participant(c._cn, int(mail_id), me)


def _ends_read(fn):
    """End the read transaction when a read command returns (#672).

    The participant check used to commit as a side effect. With no check left,
    a read command must not leave a snapshot or metadata lock open on a pooled
    connection (a later DDL or migrate would wait on it).
    """
    import functools

    @functools.wraps(fn)
    def run(c, *a, **k):
        try:
            return fn(c, *a, **k)
        finally:
            try:
                from agent_coord.server.records.db import commit as _db_commit

                _db_commit(c._cn)  # #818: not inside a request transaction
            except Exception:
                pass

    return run


def _read_redact(text: str) -> str:
    """Store-policy redaction on a read path (#672, S-3/S-6).

    Writes are scrubbed at the dispatch choke point (#504). Every desk in the
    office now reads every letter, so a read scrubs again: a letter stored
    before #504 never shows a raw secret. Already-redacted text is unchanged.
    """
    from agent_coord.server.redact import redact_text

    return redact_text(text or "")[0] if text else text


def _h_reply(c: Book, body: dict[str, Any], project: str, owner: str | None) -> Any:
    """Nest under mail_id. Default mail_to = reply-all: parent sender U parent mail_tos;
    when the parent is in a room (on a TREE), every room participant (any desk that
    sent or received a letter on that TREE) is added too.

    Exclude the replying desk from dest (no self-To). --to-desk replaces the full
    dest list. Recipients on a letter and below it change with mill add|remove mail:ID.
    Room cast = sender U mail_tos. If parent is not on a TREE, create a room with
    parent as root and this mail as child. Optional --roster overrides the
    replying desk's sender tag (mail.roster_id); the letter always carries one.
    """
    from agent_coord.server.records import mail as rec_mail
    from agent_coord.server.records import name as rec_name
    from agent_coord.server.records import tree as rec_tree

    if body.get("add_to") or body.get("remove_to"):
        raise CoordError(
            "reply: --add-to/--remove-to are gone (#265); use mill add|remove mail:ID WHO"
        )
    mail_id = int(body.get("mail_id") or body.get("id") or body.get("parent_id") or 0)
    if not mail_id:
        raise CoordError("reply: mail_id required")
    raw = str(body.get("body") or body.get("msg") or "").strip()
    if not raw or len(raw) > 4096:
        raise CoordError("body must be 1..4096 chars")

    parent_letter = rec_mail.letter_row(c._cn, mail_id)
    if not parent_letter:
        parent_rows = rec_mail.get(c._cn, mail_id)
        if not parent_rows:
            raise CoordError(f"reply: no such mail {mail_id}")
        parent_letter = parent_rows[0]

    # #672 S-3: nothing is private between desks in an office, so any seated desk
    # may reply to any letter, named room or not. The reply joins it visibly: it
    # is a letter from the Bearer desk (sender binding unchanged, #653).

    dest_aff: dict[str, str | None] = {}
    dest_set: list[str] = []
    seen: set[str] = set()
    self_bare = _stored(_stored(owner or "") or "")

    def _add_dest(bare: str, aff: str | None) -> None:
        if not bare:
            return
        if self_bare and bare == self_bare:
            return  # no self-To
        if bare in seen:
            if aff is not None and dest_aff.get(bare) is None:
                dest_aff[bare] = aff
            return
        seen.add(bare)
        dest_set.append(bare)
        dest_aff[bare] = aff

    def _live_desk(d: str) -> str:
        bare = _stored(_stored(d))
        if not bare or len(bare) > 64 or rec_name.get(c._cn, bare, CONST_DESK) is None:
            raise CoordError(
                f"reply: the desk {bare[:64]!r} is not in the name table "
                "(fix the owner name; offline desks still get mail if they exist)"
            )
        return bare

    _check_roster(c._cn, "reply", _stored(body.get("roster")))
    # #627: who gets this reply only as a room member (reply-all), not by name.
    # --to-desk names every dest; in reply-all only the parent's sender is named.
    named: set[str] = set()
    raw_tos = body.get("mail_tos")
    if isinstance(raw_tos, list) and raw_tos:
        # --to-desk replaces the full dest list
        for item in raw_tos:
            if not isinstance(item, str):
                raise CoordError("reply: --to-desk takes desk names")
            _add_dest(_live_desk(item), None)
        named = set(dest_set)
    else:
        # Default reply-all: parent sender U parent mail_tos, then (in a room)
        # every room participant: sent or received any letter on the TREE.
        parent_from = _stored(parent_letter.get("desk") or "")
        parent_sender_aff_raw = parent_letter.get("sender_roster")
        parent_sender_aff = _stored(parent_sender_aff_raw) if parent_sender_aff_raw else None
        _add_dest(parent_from, parent_sender_aff)
        named = {parent_from}
        for r in rec_mail.to_list(c._cn, mail_id):
            bare = _stored(r.get("desk") or "")
            aff_raw = r.get("roster")
            aff = _stored(aff_raw) if aff_raw else None
            _add_dest(bare, aff)
        if rec_tree.on_tree(c._cn, "mail", mail_id):
            for bare in sorted(rec_mail.room_participants(c._cn, mail_id)):
                _add_dest(bare, None)

    # #918: reply-all skips retired desks (gone from the name table) and names
    # them in skipped; an explicit --to-desk still refuses via _live_desk above.
    skipped: list[str] = []
    if not (isinstance(raw_tos, list) and raw_tos):
        live_dest: list[str] = []
        for bare in dest_set:
            if rec_name.get(c._cn, bare, CONST_DESK) is not None:
                live_dest.append(bare)
            else:
                skipped.append(bare)
        dest_set = live_dest

    if not dest_set:
        # A letter needs a reader other than its sender (no self-To). Name the
        # forms that work instead of the reply-all default (letters 2199/2200).
        if isinstance(raw_tos, list) and raw_tos:
            raise CoordError(
                "reply: --to-desk names only you, and a reply never goes to its sender; "
                f"post to the room with mill reply {mail_id} --body-file PATH (reply-all), "
                "name another desk with --to-desk DESK, or keep a private line with mill note on a card"
            )
        if skipped:
            raise CoordError(
                f"reply: every other desk on it is retired ({', '.join(skipped)}); "
                f"name a live desk with mill reply {mail_id} --to-desk DESK --body-file PATH"
            )
        raise CoordError(
            f"reply: you are the only desk on it, so reply-all reaches no one; "
            f"name a desk with mill reply {mail_id} --to-desk DESK --body-file PATH"
        )

    # If parent is not on a TREE, open a room: parent becomes root, reply nests under it.
    if not rec_tree.on_tree(c._cn, "mail", mail_id):
        tree_name = secrets.token_hex(5)
        rec_tree.create(c._cn, tree_name, "mail", mail_id)

    mail_tos = [{"deskId": d, "roster": dest_aff.get(d)} for d in dest_set]
    b = {
        "src": body.get("src") or owner or "",
        "mail_tos": mail_tos,
        "body": raw,
        "parent_type": "mail",
        "parent_id": mail_id,
        "project": project if str(body.get("project") or "").strip() else "",
        "connect_roster": body.get("connect_roster") or "",
    }
    # Optional override of letter sender roster (--roster)
    if body.get("roster") is not None and str(body.get("roster") or "").strip():
        b["roster"] = body.get("roster")
    rec = _h_send(c, b, project, owner, room_only={d for d in dest_set if d not in named})
    # The parent is handled for the desk who answered it. The new letter is not (#195).
    if self_bare:
        from agent_coord.server.records import opened as rec_opened

        rec_opened.insert(c._cn, int(mail_id), self_bare)
    if isinstance(rec, dict):
        rec["replied_to"] = mail_id
        if skipped:
            rec["skipped"] = skipped
    return rec


def _mail_thread_resolve(c: Book, body: dict[str, Any]) -> tuple[int, bool]:
    """(mail id, by_name). mail id int, or TREE/room name -> root mail id on that forest."""
    from agent_coord.server.records import tree as rec_tree

    tree_raw = body.get("tree") or body.get("room") or ""
    mid_raw = body.get("mail_id") if body.get("mail_id") is not None else body.get("id")
    # Non-numeric mail_id also means room/TREE handle (CLI string path).
    if not tree_raw and mid_raw is not None and str(mid_raw).strip() and not str(mid_raw).strip().isdigit():
        tree_raw = str(mid_raw).strip()
    if tree_raw:
        name = _stored(str(tree_raw).strip())
        if len(name) > MAIL_ROOM_NAME_MAX:
            raise CoordError(
                f"mail-thread: no mail room named {name[:MAIL_ROOM_NAME_MAX]}"
            )
        nodes = rec_tree.select(c._cn, name) or []
        mail_nodes = [
            n
            for n in nodes
            if str(n.get("type") or "") == CONST_MAIL and int(n.get("id") or 0)
        ]
        if not mail_nodes:
            raise CoordError(f"mail-thread: no mail room named {name}")
        root = min(
            mail_nodes,
            key=lambda n: (int(n.get("lft") or 0), int(n.get("id") or 0)),
        )
        return int(root["id"]), True
    try:
        mid = int(mid_raw or 0)
    except (TypeError, ValueError) as e:
        raise CoordError("mail-thread: mail_id or TREE/room name required") from e
    if not mid:
        raise CoordError("mail-thread: mail_id or TREE/room name required")
    return mid, False


def _mail_thread_resolve_mid(c: Book, body: dict[str, Any]) -> int:
    """mail id int, or TREE/room name -> root mail id on that forest."""
    return _mail_thread_resolve(c, body)[0]


# mail-thread read scopes (#148, #155). branch is the default for a mail id
# and is narrowed by the per-desk cursor. full is the whole branch.
# A later branch read skips letters this desk sent (#222).
# a bare room name gives a summary; --after implies room (catch-up).
MAIL_THREAD_SCOPES = ("branch", "full", "subtree", "room", "summary")
MAIL_THREAD_SUMMARY_LATEST = 3
# p_tree is VARCHAR(64). A longer room name must not reach MySQL (#208).
MAIL_ROOM_NAME_MAX = 64


def _branch_since(ordered: list[int], asked: int, last: int) -> list[int]:
    """Letters on this branch this desk has not been served (#190).

    A re-read of a letter already served returns that letter alone.
    Already-served ancestors are not printed again.
    """
    ids = [int(i) for i in ordered]
    newer = [i for i in ids if i > int(last or 0)]
    if newer:
        return newer
    if asked in ids:
        return [int(asked)]
    return [int(asked)] if asked else []


def _omit_own_sent(cn, pick: list[int], asked: int, desk: str) -> list[int]:
    """A later branch read skips letters this desk sent (#222).

    The asked letter stays, so a re-read of your own letter still returns it.
    The first read (cursor still 0) is unchanged and keeps the whole branch.
    """
    if not desk or not pick:
        return pick
    from agent_coord.server.records import mail as rec_mail

    rows = rec_mail.letters_by_id(cn, [int(i) for i in pick])
    kept: list[int] = []
    for i in pick:
        iid = int(i)
        if iid == int(asked):
            kept.append(iid)
            continue
        sender = str((rows.get(iid) or {}).get("desk") or "")
        if sender == desk:
            continue
        kept.append(iid)
    return kept or ([int(asked)] if asked else [])


def _mail_thread_scope(body: dict[str, Any], by_name: bool, after_id: int) -> str:
    raw = str(body.get("scope") or "").strip().lower()
    if raw == "all":
        raise CoordError("mail-thread: --all is not a flag; use --room")
    if raw and raw not in MAIL_THREAD_SCOPES:
        raise CoordError(
            "mail-thread: scope must be branch, full, subtree, room, or summary"
        )
    if raw:
        return raw
    if after_id:
        return "room"
    return "summary" if by_name else "branch"


def _mail_thread_pick(nodes: list[dict], mid: int, scope: str) -> list[int]:
    """Mail ids for one read scope, from room nodes {id, lft, rgt} in lft order."""
    if not nodes:
        return [mid]
    me = next((n for n in nodes if int(n["id"]) == mid), None)
    if me is None:
        return [int(n["id"]) for n in nodes]
    if scope == "room":
        return [int(n["id"]) for n in nodes]
    if scope == "branch":
        return [int(n["id"]) for n in nodes if n["lft"] <= me["lft"] and n["rgt"] >= me["rgt"]]
    if scope == "subtree":
        return [int(n["id"]) for n in nodes if me["lft"] <= n["lft"] <= me["rgt"]]
    # summary: root plus the latest few letters by id, oldest first
    root_id = int(nodes[0]["id"])
    rest = sorted(int(n["id"]) for n in nodes if int(n["id"]) != root_id)
    return [root_id] + rest[-MAIL_THREAD_SUMMARY_LATEST:]


def _ids_in_tree_order(nodes: list[dict], ids: list[int], extra: int = 0) -> list[int]:
    """ids in room lft order. extra is inserted when that letter is on this room."""
    have = {int(i) for i in ids if int(i or 0)}
    if extra:
        have.add(int(extra))
    order = [int(n["id"]) for n in nodes if int(n.get("id") or 0)]
    if not order:
        return [i for i in have]
    return [i for i in order if i in have]


def _mark_shown(c: Book, ids: list[int], desk: str) -> list[int]:
    """Stamp opened on this desk's unread rows among ids; return those ids, in order."""
    from agent_coord.server.records import opened as rec_opened
    from agent_coord.server.records.name import get as name_get

    want = [int(i) for i in ids if int(i or 0)]
    did = name_get(c._cn, desk, CONST_DESK) if desk and want else None
    if not did:
        return []
    marks = ",".join(["%s"] * len(want))
    cur = c._cn.cursor()
    try:
        cur.execute(
            "SELECT id FROM mail_to WHERE type = 'mail' AND desk_id = %s AND opened IS NULL"
            " AND id IN (" + marks + ")",
            (int(did), *want),
        )
        unread = {int(r[0]) for r in cur.fetchall()}
    finally:
        cur.close()
    done = [i for i in want if i in unread]
    for mid in done:
        rec_opened.insert(c._cn, mid, desk)
    return done


@_ends_read
def _h_mail_thread(c: Book, body: dict[str, Any], project: str, owner: str | None) -> Any:
    """Read a room by mail id or TREE/room name. Lean MAIL rows only (no opened).

    Safe single-id fetch.
    Host lock: TREE name = room name handle for agents.
    Scopes (#148): mail id default = branch (the letter plus its parent chain);
    scope=subtree = the letter and every reply under it; scope=room =
    whole TREE; a bare room name = summary (root plus latest few, counts).
    --after <id> keeps catch-up: id > after, and with no scope it means room.
    Read access (#672, S-3): every seated desk reads every letter and room,
    named or opened by reply, participant or not. Nothing is private between
    desks in an office. A read adds no participant, delivers nothing to an inbox
    and wakes no one; a desk joins by replying (#149) or by mill add mail:ID.
    latest_id, room_letters, ids, and hints count the whole room (#206).
    """
    from agent_coord.server.records import mail as rec_mail

    if not owner:
        raise CoordError("mail-thread: owner required")
    mid, by_name = _mail_thread_resolve(c, body)
    rows = rec_mail.get(c._cn, mid)
    if not rows:
        raise CoordError(f"mail-thread: no such mail {mid}")

    after_raw = body.get("after", body.get("after_id", 0))
    if after_raw is None or after_raw == "":
        after_id = 0
    else:
        try:
            after_id = int(after_raw)
        except (TypeError, ValueError) as e:
            raise CoordError("mail-thread: after must be a mail id") from e
    if after_id < 0:
        raise CoordError("mail-thread: after must be a mail id")
    scope = _mail_thread_scope(body, by_name, after_id)

    self_bare = _stored(_stored(owner) or "")
    # One read of the room per request: crumbs, nodes and tree id all come from it.
    room = rec_mail.RoomRead(c._cn, mid)
    nodes = room.nodes
    root_id = int(nodes[0]["id"]) if nodes else mid
    # Read rule (#sec S-3, #672): collaboration by default. Every desk holding
    # minted access to this office (the Bearer desk; the wall refuses a caller
    # with none before this) reads every letter and room, named or opened by
    # reply, whole, at any trust level. A read adds no participant, lands nothing
    # in an inbox and wakes no one. Bodies are redacted when stored (S-6) and
    # again on this read (_read_redact), for letters stored before #504.

    all_ids = [int(n["id"]) for n in nodes] or [mid]
    if after_id and after_id not in set(all_ids):
        raise CoordError(
            f"mail-thread: after {after_id} not on same TREE/chain as mail {mid}"
        )
    pick_scope = "branch" if scope == "full" else scope
    pick = _mail_thread_pick(nodes, mid, pick_scope)
    branch_last = 0
    if after_id:
        pick = [i for i in pick if i > after_id]
    elif scope in ("branch", "full"):
        from agent_coord.server.records import name as rec_name

        did = rec_name.get(c._cn, self_bare, CONST_DESK) if self_bare else None
        # Cursor key is the room's tree (tree.name_id). Off-tree letter: no cursor.
        tree_nid = room.tree_id if did else None
        if did and tree_nid:
            last = rec_mail.read_cursor(c._cn, int(did), int(tree_nid))
            if scope == "branch":
                branch_last = int(last or 0)
                pick = _branch_since(pick, mid, last)
            tip = max([int(last), int(mid)] + [int(i) for i in pick])
            rec_mail.advance_read_cursor(c._cn, int(did), int(tree_nid), tip)
    # #672 S-3: every letter of the room is visible to every seated desk, so the
    # #191/#219 per-cast filter is gone; counts cover the whole room (#206).
    visible = list(all_ids)
    # A letter this desk sent is left out of a later branch read (#222).
    if scope == "branch" and branch_last > 0:
        pick = _omit_own_sent(c._cn, pick, mid, self_bare)
    out = rec_mail.public_mail_chain(c._cn, mid, ids=pick, room=room)
    for letter in out.get("chain") or []:
        if isinstance(letter, dict) and isinstance(letter.get("body"), str):
            letter["body"] = _read_redact(letter["body"])
    # Room-name summary is a list: 256-char bodies, no per-letter mail_tos (#154).
    if scope == "summary":
        for letter in out.get("chain") or []:
            if not isinstance(letter, dict):
                continue
            body, trunc = rec_mail.lean_body(str(letter.get("body") or ""))
            letter["body"] = body
            if trunc:
                letter["body_trunc"] = True
            letter.pop("mail_tos", None)
    # A4 MAIL Threads SoR: mark thread=1 when envelope carries TREE crumbs.
    if isinstance(out, dict) and out.get("tree"):
        out["thread"] = 1
    # latest_id = max this desk can see. Stable under --after and every scope.
    out["latest_id"] = max(visible) if visible else 0
    out["scope"] = scope
    # Card 843: a read that prints letters whole marks them handled for this desk,
    # the same stamp as mill mark (unread = mail_to.opened NULL, receipts too).
    # Short-row --room previews and a room summary print previews; they do not.
    whole = scope in ("branch", "full", "subtree") or (scope == "room" and after_id > 0)
    out["marked"] = _mark_shown(c, pick, self_bare) if whole else []
    total = len(visible)
    out["room_letters"] = total
    seen = set(visible)
    if scope != "room" and total > 1:
        handle = str(out.get("tree") or root_id) if by_name else str(root_id)
        if scope == "summary":
            out["hint"] = (
                f"summary: root + latest {len(pick) - 1} of {total} letters; "
                f"mill mail-thread {handle} --room for all, "
                "mill mail-thread <id> for one branch"
            )
        else:
            under = 0
            me = next((n for n in nodes if int(n["id"]) == mid), None)
            if me is not None:
                under = sum(
                    1
                    for n in nodes
                    if me["lft"] < n["lft"] <= me["rgt"] and int(n["id"]) in seen
                )
            if scope == "branch":
                out["replies_under"] = under
            more = []
            if scope == "branch" and under:
                more.append(f"--subtree for {under} replies under {mid}")
            if scope == "branch":
                more.append("--full for the whole branch")
            more.append(f"mill mail-thread {root_id} --room for all {total}")
            out["hint"] = f"{scope}: {len(out.get('chain') or [])} of {total} letters; " + "; ".join(more)
    return out


# Card 778: the moves states.md draws. claim and assign take an open card (or a
# claimed one, for --take-over and an eta); unclaim releases one. Parked goes
# through unpark (it needs a plan parent); shipped and done move by pass.
_MOVES_FROM = {"claim": ("open", "claimed"), "assign": ("open", "claimed"), "unclaim": ("open", "claimed")}


def _card_moves(c: Book, hit: dict[str, Any], command: str, project: str, need: str) -> None:
    """Refuse a claim, assign or unclaim the card's status does not allow; nothing changes."""
    from agent_coord.server.records import todo as rec_todo
    from agent_coord.server.records import tree as rec_tree

    st = rec_todo.normalize_status(str(hit.get("status") or ""), default="open")
    if st in _MOVES_FROM[command]:
        return
    card = f"{command}: {project}/{need} is {st}; "
    form = f"mill pass {project} {need}"
    if st == "parked":
        unpark = f"mill unpark {project} {need}"
        if not rec_tree.has_parent(c._cn, "todo", int(hit["id"])):
            unpark += " --parent-type T --parent-id N"
        raise CoordError(card + unpark + " first")
    if st == "shipped":
        raise CoordError(card + f"the asker accepts it with {form} --done, or steps it back with {form} --back")
    raise CoordError(card + f"{form} --back steps it back to shipped; for new work file a new card")


def _h_assign(c: Book, body: dict[str, Any], project: str, owner: str | None) -> Any:
    from agent_coord.config import mill_trust
    from agent_coord.server.records import todo as rec_todo
    from agent_coord.server.admin.guard import require_admin

    need = slug(str(body.get("need") or ""))
    desk = _stored(str(body.get("desk") or body.get("dst") or ""))
    hit = rec_todo.find(c._cn, project, need)
    if hit is None:
        raise CoordError(f"no such need: {project}/{need}")
    _card_moves(c, hit, "assign", project, need)
    current = _desk_slug(c._cn, hit, "volunteer", "assigned")
    if current and current != "-":
        raise CoordError("assign: assignee must relinquish first")
    if mill_trust() == "limited":
        require_admin(c._cn, owner or "")
    rec_todo.update(
        c._cn, int(hit["id"]), _stored(owner or ""), status="claimed", volunteer=_stored(desk)
    )
    rec = {"ok": True, "need_id": need, "id": int(hit["id"]), "status": "claimed", "volunteer": desk}
    _poke(c, "todo", rec["id"], "assign", owner=owner)
    return rec


# Card 867: a card guard runs in its SP, in the transaction that moves the card,
# under the card's row lock. The SP's 45000 text is the refusal the desk reads.
EVIDENCE_MAX = 2000
DONE_WHEN_MAX = 1000


def _card_refusal(code: str, roster: str, need: str) -> str:
    """The desk's refusal line for a card SP's code (#867).

    SIGNAL's MESSAGE_TEXT holds at most 128 characters, and the refusal lines name the
    roster, the card and the command to run (up to about 300). So a card SP signals
    `card:<code>[:<arg>]` and the text is written here, word for word as before.
    """
    kind, _, arg = code.partition(":")
    form = f"mill pass {roster} {need}"
    if kind == "moves":  # moves:<command>:<status>[:noparent]
        command, _, rest = arg.partition(":")
        st, _, flag = rest.partition(":")
        head = f"{command}: {roster}/{need} is {st}; "
        if st == "parked":
            unpark = f"mill unpark {roster} {need}"
            if flag == "noparent":
                unpark += " --parent-type T --parent-id N"
            return head + unpark + " first"
        if st == "shipped":
            return head + f"the asker accepts it with {form} --done, or steps it back with {form} --back"
        return head + f"{form} --back steps it back to shipped; for new work file a new card"
    texts = {
        "claimed_by": f"claim: {roster}/{need} is claimed by {arg}; ask {arg} to "
        f"mill unclaim {roster} {need}, or run mill claim {roster} {need} "
        "--take-over to take it (the card records the prior volunteer)",
        "who_may_unclaim": "who-may: unclaim is the volunteer",
        "stale_prior": f"claim: {roster}/{need} changed volunteer while claiming; nothing changed; run it again",
        "already_shipped": f"pass: {need} is already shipped; the asker accepts it with {form} --done",
        "already_done": f"pass: {need} is already done; {form} --back steps it back to shipped",
        "not_shippable": f"pass: {need} is {arg}; only a claimed card ships",
        "claim_first": "claim first: mill claim <project> <need>",
        "who_may_ship": "who-may: pass claimed->shipped is the volunteer",
        "done_not_shipped": f"pass --done: {need} is {arg}, not shipped; nothing changed",
        "who_may_done": f"who-may: pass shipped->done is the asker ({arg}) or Admin"
        if arg
        else "who-may: pass shipped->done is the asker; the card's asker does not resolve, so only the volunteer or Admin may",
        "back_status": f"pass --back: {need} is {arg}; only shipped or done steps back (unclaim releases a claim)",
        "who_may_back": "who-may: pass --back is the asker or the volunteer"
        if arg
        else "who-may: pass --back is the asker or the volunteer; the card's asker does not resolve, so only the volunteer may",
        "who_may_done_when": "who-may: done-when is the asker or Admin",
        "done_when_done": f"done-when: {need} is done; nothing changed",
        "deleted": f"card: {roster}/{need} is retired; reclaim it before moving it",
        "unpark_status": f"unpark: {roster}/{need} is not parked; nothing changed",
        "assign_guard": f"assign: {roster}/{need} must be open with no volunteer",
    }
    return texts.get(kind, f"{kind}: refused")


def _desk_arg(owner: str | None) -> Any:
    """The desk id arg of a card SP: MILL_DESK_ID(name) in the same CALL (#867).
    NULL for no desk (no who-may check), 0 for a name the book does not hold."""
    from agent_coord.server.records.db import Inline
    from agent_coord.server.records.name import bare

    return Inline("MILL_DESK_ID(%s)", bare(_stored(owner or ""), CONST_DESK))


def _card_sp(c: Book, proc: str, args: list, roster: str, need: str) -> dict[str, Any]:
    """Call a card SP; a `card:<code>` refusal is written out for this roster and need."""
    from agent_coord.server.records.db import call

    try:
        rows = call(c._cn, proc, args)
    except CoordError:
        raise
    except Exception as e:
        msg = _sql_refusal(e)
        if msg and msg.startswith("card:"):
            raise CoordError(_card_refusal(msg[5:], roster, need)) from e
        if msg:
            raise CoordError(msg) from e
        raise
    # The SP's answer is its last row (a nested call may send rows of its own first).
    return dict(rows[-1]) if rows else {}


def _card_hit(c: Book, project: str, need: str) -> dict[str, Any]:
    from agent_coord.server.records import todo as rec_todo

    hit = rec_todo.find(c._cn, project, need)
    if hit is None:
        raise CoordError(f"no such need: {project}/{need}")
    return hit


CLAIM_TRIES = 3


def _h_claim(c: Book, body: dict[str, Any], project: str, owner: str | None) -> Any:
    """Claim a card. Refusals come in main's order on the row already read: status,
    msg cap, eta, #325 claimed-by, card budget (Validator letter 2944). cmd_claim is
    the authority: it checks status and volunteer again under the row lock, and
    refuses a take-over whose body names a prior that no longer holds the card
    (then the card is read again and the line rewritten)."""
    need = slug(str(body.get("need") or ""))
    for _ in range(CLAIM_TRIES):
        hit = _card_hit(c, project, need)
        try:
            return _claim_once(c, body, project, need, hit, owner)
        except _StalePrior:
            continue
    raise CoordError(f"claim: {project}/{need} changed volunteer while claiming; nothing changed; run it again")


class _StalePrior(Exception):
    """cmd_claim read another volunteer under the lock than the take-over line names."""


def _claim_once(c: Book, body: dict[str, Any], project: str, need: str, hit: dict[str, Any], owner: str | None) -> Any:
    from agent_coord.server.records import todo as rec_todo

    # Read-only pre-check, main's order (cmd_claim checks the same under the lock).
    _card_moves(c, hit, "claim", project, need)
    # --eta and --msg are stored. A bad eta or an oversize msg refuses
    # before the claim is written (#232).
    eta_raw = str(body.get("eta") or "").strip()
    msg = str(body.get("msg") or "")
    if len(msg) > rec_todo.BODY_MAX:
        raise CoordError("claim: msg would be %s chars (max %s)" % (len(msg), rec_todo.BODY_MAX))
    eta_at = None
    if eta_raw:
        try:
            eta_at = rec_todo.parse_eta(eta_raw)
        except ValueError as e:
            raise CoordError("claim: %s" % e) from e
    take_over = bool(body.get("take_over"))
    who = _stored(owner or "")
    # #325: a card another desk holds is not taken silently. --take-over takes it
    # and the card records the prior volunteer.
    prior = _desk_slug(c._cn, hit, "volunteer", "assigned")
    if prior == "-" or prior == who:
        prior = ""
    if prior and not take_over:
        raise CoordError(_card_refusal("claimed_by:" + prior, project, need))
    fields = rec_todo.unpack(hit.get("body") or "", hit.get("id"))
    payload = fields["payload"] or {
        "slug": fields["need_id"],
        "detail": fields["detail"],
    }
    if eta_at is not None:
        payload["eta_at"] = eta_at.isoformat(sep=" ", timespec="seconds")
    note = msg.strip()
    lines = ([f"took over from {prior}"] if prior else []) + ([note] if note else [])
    if lines:
        # The card's stored column is the only bound, as for note (#360).
        before = dict(payload)
        prev = str(payload.get("detail") or "")
        extra = "\n".join(lines)
        payload["detail"] = extra if not prev.strip() else prev + "\n" + extra
        refusal = rec_todo.over_budget(before, payload, "claim")
        if refusal:
            raise CoordError(refusal)
    body_s = rec_todo.stored_body(payload) if (eta_at is not None or lines) else None
    try:
        got = _card_sp(
            c,
            "cmd_claim",
            [_desk_arg(owner), int(hit["id"]), 1 if take_over else 0, prior, body_s],
            project,
            need,
        )
    except CoordError as e:
        if str(e) == _card_refusal("stale_prior", project, need):
            raise _StalePrior() from e
        raise
    rec = {"ok": True, "need_id": need, "id": int(hit["id"]), "status": "claimed", "volunteer": owner}
    prior = _stored(str(got.get("prior_volunteer") or ""))
    if prior:
        rec["prior_volunteer"] = prior
    if eta_at is not None:
        rec["eta_at"] = payload["eta_at"]
    if note:
        rec["note"] = note
    _poke(c, "todo", rec["id"], "claim", owner=owner)
    return rec


def _require_project(cn, project: str) -> None:
    """create todo files a card on a roster that already exists (#214)."""
    from agent_coord.server.records import name as rec_name
    from agent_coord.server.records import tree as rec_tree

    who = _stored(project)
    if not who:
        raise CoordError("todo: project required")
    if rec_name.get(cn, who, CONST_ROSTER) is not None:
        return
    if rec_name.get(cn, who, CONST_TREE) is not None:
        kind = "tree"
        nodes = rec_tree.select(cn, who) or []
        root = next((n for n in nodes if int(n.get("lft") or 0) == 1), None)
        if root is not None and str(root.get("type") or "") == CONST_MAIL:
            kind = "room"
        raise CoordError("todo: %s is a %s, not a roster" % (who, kind))
    raise CoordError("todo: no project %s" % who)


def _h_open(c: Book, body: dict[str, Any], project: str, owner: str | None) -> Any:
    from agent_coord.server.records import todo as rec_todo

    need = slug(str(body.get("need") or body.get("title") or ""))
    # #818: --doing on create is the desk's doing (written after the call), not card text.
    # #188: same rule as an oversize note. Refuse. Do not keep a silent prefix.
    import json

    detail_raw = str(body.get("detail") or "")
    if len(detail_raw) > rec_todo.BODY_MAX:
        raise CoordError(
            "todo: detail would be %s chars (max %s); refused, nothing stored"
            % (len(detail_raw), rec_todo.BODY_MAX)
        )
    detail = detail_raw
    if len(str(body.get("done_when") or "").strip()) > DONE_WHEN_MAX:
        raise CoordError("done-when would be %s chars (max %s); refused, nothing stored"
                         % (len(str(body.get("done_when")).strip()), DONE_WHEN_MAX))
    # Create accepts parked or open only. An empty status is open (#231).
    raw_status = body.get("status")
    if raw_status is None or str(raw_status).strip() == "":
        st = "open"
    else:
        st = rec_todo.normalize_status(str(raw_status), default="")
        if st not in ("parked", "open"):
            raise CoordError("status must be parked or open")
    body_s = json.dumps({"slug": need, "detail": detail})
    if len(body_s) > rec_todo.BODY_MAX:
        # #292: a long detail is refused, never cut to its tail.
        raise CoordError(
            "todo: stored card is %s chars, over %s (non-ASCII is stored escaped); "
            "refused, nothing stored" % (len(body_s), rec_todo.BODY_MAX)
        )
    from agent_coord.server.records import name as rec_name

    _require_project(c._cn, project)
    rec_name.ensure_roster(c._cn, project, CONST_ROSTER)
    hit = rec_todo.find(c._cn, project, need)
    parent_t = str(body.get("parent_type") or body.get("type_a") or "")
    parent_id = int(body.get("parent_id") or body.get("id_a") or 0)
    if hit:
        # Card 775: create never rewrites a card. It used to reset status and detail.
        tid = int(hit["id"])
        status = rec_todo.normalize_status(str(hit.get("status") or ""), default="open")
        forms = f"add a line with mill note {project} {need} --note TEXT"
        if parent_t and parent_id:
            forms += f"; put it under the parent with mill attach {project} {parent_t} {parent_id} todo {tid}"
        raise CoordError(
            f"create todo: {project}/{need} exists (id {tid}, {status}); nothing changed; {forms}"
        )
    if parent_t and parent_id:
        # New card and its tree place commit together. A 1062 retries inside (#146).
        rows = rec_todo.insert_attached(
            c._cn, _stored(project), _stored(owner or ""), st, body_s, parent_t, parent_id
        )
        tid = int(rows[0]["id"]) if rows else 0
    else:
        rows = rec_todo.insert(c._cn, _stored(project), _stored(owner or ""), st, body_s)
        tid = int(rows[0]["id"]) if rows else 0
    rec = {"project_id": project, "need_id": need, "id": tid, "status": st, "detail": detail}
    if str(body.get("done_when") or "").strip():
        rec["done_when"] = _done_when(c, tid, project, need, body.get("done_when"), owner)["done_when"]
    _poke(c, "todo", tid, "open", owner=owner)
    return rec


def _h_unpark(c: Book, body: dict[str, Any], project: str, owner: str | None) -> Any:
    from agent_coord.server.records import todo as rec_todo
    from agent_coord.server.records import tree as rec_tree

    need = slug(str(body.get("need") or ""))
    hit = rec_todo.find(c._cn, project, need)
    if not hit:
        raise CoordError(f"no such need: {project}/{need}")
    tid = int(hit["id"])
    parent_t = str(body.get("parent_type") or body.get("type_a") or "").strip().lower()
    parent_id = int(body.get("parent_id") or body.get("id_a") or 0)
    if bool(parent_t) != bool(parent_id):
        raise CoordError("unpark: --parent-type and --parent-id go together")
    if parent_t and parent_id:
        # A bad parent is refused before the card moves (#246).
        from agent_coord.server.records.label import _activity_live

        if parent_t not in (CONST_MAIL, CONST_TODO):
            raise CoordError("unpark: --parent-type is mail or todo")
        if parent_t == CONST_TODO and parent_id == tid:
            raise CoordError("unpark: a card cannot be its own parent")
        if not _activity_live(c._cn, parent_t, parent_id):
            raise CoordError(f"unpark: no {parent_t} {parent_id}")
        rec_tree.add(c._cn, parent_t, parent_id, "todo", tid)
    if not rec_tree.has_parent(c._cn, "todo", tid):
        raise CoordError(
            "unpark: todo has no TREE parent; pass --parent-type and --parent-id to attach it"
        )
    st = rec_todo.normalize_status(str(hit.get("status") or ""), default="open")
    if st != "parked":
        # SP also refuses under the card lock (F186); this is the desk-facing line.
        if st == "open":
            return {"ok": True, "need": need, "status": "open"}  # no-op
        raise CoordError(f"unpark: {project}/{need} is {st}; nothing changed")
    rec_todo.update(c._cn, tid, _stored(owner or ""), status="open")
    rec = {"ok": True, "need": need, "status": "open"}
    _poke(c, "todo", tid, "unpark", owner=owner)
    return rec


def _desk_slug(cn, hit: dict[str, Any], *keys: str) -> str:
    """Desk name from string fields or creator_id/assigned_id on a todo row."""
    from agent_coord.server.records.name import by_id as name_by_id

    # agent-ux 1213: only the role asked for. A fixed ("assigned", "creator", ...) order
    # made the asker lookup return the volunteer, so pass shipped->done
    # refused the real asker whenever asker != volunteer.
    for k in (*keys, "desk"):
        raw = str(hit.get(k) or "").strip()
        if raw and not raw.isdigit():
            return _stored(raw)
    id_keys = []
    for k in keys:
        kl = k.lower()
        if kl in ("volunteer", "assigned"):
            id_keys.append("assigned_id")
        elif kl in ("asker", "creator"):
            id_keys.append("creator_id")
        else:
            id_keys.append(f"{k}_id")
    for ik in id_keys:
        nid = hit.get(ik)
        if nid is None or nid == "" or nid == 0:
            continue
        try:
            name = _stored(name_by_id(cn, int(nid)))
        except Exception:
            continue
        if name:
            return _stored(name)
    return ""


def _h_yield(c: Book, body: dict[str, Any], project: str, owner: str | None) -> Any:

    need = slug(str(body.get("need") or ""))
    hit = _card_hit(c, project, need)
    _card_sp(c, "cmd_unclaim", [_desk_arg(owner), int(hit["id"])], project, need)
    rec = {"ok": True, "need": need, "status": "open"}
    _poke(c, "todo", int(hit["id"]), "unclaim", owner=owner)
    return rec


def _each_need(raw: Any, one) -> Any:
    """#19: NEED may be a comma list (a,b,c), the same as `mill add roster NAME d1,d2`.
    One need runs as before (a refusal raises). A list runs every card and returns
    one result row per card; a bad card does not stop the rest."""
    text = str(raw or "")
    if "," not in text:
        return one(text)
    rows: list[dict[str, Any]] = []
    for part in [p.strip() for p in text.split(",")]:
        if not part:
            continue
        try:
            rec = dict(one(part))
            rec["ok"] = True
            rec["need"] = part
            rows.append(rec)
        except CoordError as e:
            rows.append({"need": part, "ok": False, "error": str(e)})
        except Exception as e:
            rows.append({"need": part, "ok": False, "error": _sql_refusal(e) or f"{type(e).__name__}: refused"})
    refused = sum(1 for r in rows if not r["ok"])
    return {"ok": True, "results": rows, "refused": refused}


def _h_pass(c: Book, body: dict[str, Any], project: str, owner: str | None) -> Any:
    """One named step (#615): ship (claimed -> shipped, the volunteer), done
    (shipped -> done, the asker or Admin accepts) or back (done -> shipped -> claimed).
    A step that does not fit the card's status is refused and changes nothing.
    Optional evidence (#867) is kept with a ship or done step. NEED may be a comma list (#19)."""
    step = str(body.get("step") or "ship").strip().lower()
    if step not in ("ship", "done", "back"):
        raise CoordError("pass: step is ship, done or back")
    evidence = str(body.get("evidence") or "").strip()
    if len(evidence) > EVIDENCE_MAX:
        raise CoordError(
            "pass: evidence would be %s chars (max %s); refused, nothing changed" % (len(evidence), EVIDENCE_MAX)
        )
    return _each_need(body.get("need"), lambda n: _pass_one(c, n, step, project, owner, evidence))


def _pass_one(
    c: Book, raw_need: str, step: str, project: str, owner: str | None, evidence: str = ""
) -> dict[str, Any]:

    need = slug(str(raw_need or ""))
    hit = _card_hit(c, project, need)
    got = _card_sp(
        c,
        "cmd_pass",
        [_desk_arg(owner), int(hit["id"]), step, evidence or None],
        project,
        need,
    )
    nxt = str(got.get("status") or "")
    rec = {"ok": True, "need": need, "status": nxt, "was": str(got.get("was") or ""), "id": int(hit["id"])}
    # #867: the card's evidence after the step (a done keeps the ship's; a back step clears it).
    if got.get("evidence"):
        rec["evidence"] = str(got["evidence"])
    _poke(c, "todo", rec["id"], "pass", owner=owner)
    return rec


def _done_when(c: Book, card_id: int, project: str, need: str, raw: Any, owner: str | None) -> dict[str, Any]:
    """Set or clear the card's acceptance line (#867). The SP checks asker or Admin and not done."""

    text = str(raw or "").strip()
    if len(text) > DONE_WHEN_MAX:
        raise CoordError(
            "done-when would be %s chars (max %s); refused, nothing changed" % (len(text), DONE_WHEN_MAX)
        )
    got = _card_sp(c, "cmd_card_accept", [_desk_arg(owner), card_id, text], project, need)
    return {"ok": True, "need": need, "id": card_id, "done_when": got.get("done_when")}


def _h_glance(c: Book, body: dict[str, Any], project: str, owner: str | None) -> Any:
    """The office glance, computed live: one summary row, newest 30 activity rows."""
    from agent_coord.server.beta_client import read_glance

    return read_glance(c._cn)


_NOTE_WITH_DONE_WHEN = ("text", "note", "detail", "supersedes", "eta", "started")


def _h_note(c: Book, body: dict[str, Any], project: str, owner: str | None) -> Any:
    from agent_coord.server.records import todo as rec_todo

    if "done_when" in body and any(body.get(k) not in (None, "", False) for k in _NOTE_WITH_DONE_WHEN):
        # Card 866: the done-when path writes only the done-when; refuse rather than drop the rest.
        raise CoordError("note: --done-when goes alone; send the note in its own mill note. Nothing changed")
    need = slug(str(body.get("need") or ""))
    hit = rec_todo.find(c._cn, project, need)
    if hit is None:
        raise CoordError(f"no such need: {project}/{need}")
    if "done_when" in body:
        return _done_when(c, int(hit["id"]), project, need, body.get("done_when"), owner)
    fields = rec_todo.unpack(hit.get("body") or "", hit.get("id"))
    payload = fields["payload"] or {"slug": fields["need_id"], "detail": fields["detail"]}
    before = dict(payload)
    note_s = str(body.get("note") or body.get("detail") or "").strip()
    # #102: positional text. A progress token (9/12, 75%, done, git <sha>) is
    # progress; anything else (incl. an @file body) is diary like --note.
    text_s = str(body.get("text") or "").strip()
    prog_text = ""
    if text_s:
        if rec_todo.is_progress_token(text_s):
            prog_text = text_s
        else:
            note_s = (note_s + "\n" + text_s) if note_s else text_s

    supersedes = str(body.get("supersedes") or "").strip()
    if "supersedes" in body and not supersedes:
        # A blank OLD_LINE must not fall through to a plain note.
        raise CoordError("note: --supersedes needs the old line; copy it from mill todo")
    if supersedes and not note_s:
        raise CoordError("note: --supersedes needs the new text (--note TEXT)")
    eta_raw = str(body.get("eta") or "").strip()
    started = bool(body.get("started"))
    if not (note_s or prog_text or eta_raw or started):
        raise CoordError(
            "note: nothing to write (give text such as 9/12 or 75%, @file, --note, --eta, or --started)"
        )
    if body.get("replace"):
        # #539: notes are append-only; an overwrite would skip the history F45 keeps.
        raise CoordError(
            "note: notes append; there is no replace (to correct a line: mill note PROJECT NEED --supersedes OLD_LINE --note NEW)"
        )
    if supersedes:
        payload["detail"] = _supersede_line(
            c, hit, project, owner, str(payload.get("detail") or ""), supersedes, note_s
        )
    elif note_s:
        # The card's whole stored body is the bound, checked once below (#360).
        prev = str(payload.get("detail") or "")
        payload["detail"] = note_s if not prev.strip() else prev + "\n" + note_s
    progress = rec_todo.format_progress(prog_text)
    if progress:
        payload["progress"] = progress
    if eta_raw:
        try:
            eta_at = rec_todo.parse_eta(eta_raw)
        except ValueError as e:
            raise CoordError(f"note: {e}") from e
        if eta_at is not None:
            payload["eta_at"] = eta_at.isoformat(sep=" ", timespec="seconds")
    if started:
        from datetime import datetime

        payload["started_at"] = datetime.now().isoformat(sep=" ", timespec="seconds")
    refusal = rec_todo.over_budget(before, payload)
    if refusal:
        raise CoordError(refusal)
    changed = payload != before
    tid = int(hit["id"])
    if changed:
        stored = rec_todo.stored_body(payload)
        rec_todo.update(c._cn, tid, _stored(owner or ""), body=stored)
        kept = rec_todo.unpack(stored, tid)
    else:
        kept = rec_todo.unpack(hit.get("body") or "", tid)
    rec = {
        "need_id": fields["need_id"],
        "id": tid,
        "detail": kept.get("detail") or "",
        "changed": changed,
    }
    if kept.get("progress"):
        rec["progress"] = kept["progress"]
    # #360: the room left on this card, so the cap shows before a note hits it.
    rec["detail_left"] = rec_todo.budget_left(payload if changed else before)
    if supersedes:
        rec["superseded"] = supersedes
    for k in ("eta_at", "started_at"):
        if payload.get(k):
            rec[k] = payload[k]
    if changed:
        # A note that changes nothing does not wake watchers.
        _poke(c, "todo", tid, "note", owner=owner)
    return rec


SUPERSEDED = "[superseded] "


def _supersede_line(
    c: Book, hit: dict, project: str, owner: str | None, detail: str, old: str, new: str
) -> str:
    """note --supersedes (#333): the matching detail line stays, marked, with the new text under it.

    Append-only: nothing is deleted. Asker or Admin. One exact whole-line match
    (spaces at the ends ignored); none or several is refused before any write.
    """
    from agent_coord.server.admin.guard import is_role_admin

    who = _stored(owner or "")
    ask = _desk_slug(c._cn, hit, "asker", "creator")
    if who != ask and not is_role_admin(c._cn, owner or ""):
        raise CoordError("note: --supersedes is for the asker (%s) or Admin" % (ask or "unknown"))
    if old.startswith(SUPERSEDED.strip()):
        raise CoordError("note: that line is already superseded; quote the line that replaced it")
    lines = detail.split("\n")
    hits = [i for i, ln in enumerate(lines) if ln.strip() == old]
    # The errors never echo OLD_LINE: it is not a redacted key and could hold a secret.
    if not hits:
        raise CoordError("note: no detail line matches --supersedes exactly; copy the whole line from mill todo")
    if len(hits) > 1:
        raise CoordError("note: %d detail lines match --supersedes; nothing changed" % len(hits))
    i = hits[0]
    # Ends are ignored only to match; the kept line is the original, unchanged.
    lines[i : i + 1] = [SUPERSEDED + lines[i], new]
    # The card's stored column is the bound, checked once in _h_note (#360).
    return "\n".join(lines)


def _h_hold(c: Book, body: dict[str, Any], project: str, owner: str | None) -> Any:
    from agent_coord.server.records import hold as rec_hold
    from agent_coord.server.records.name import by_id as name_by_id

    from agent_coord.helpers.bounds import resource_name

    # The lock is global. 0.7.x clients send no roster; the record is tagged Office.
    project = project or _office(getattr(c, "_cn", None))
    _require_live_project(getattr(c, "_cn", None), project, "hold")
    # No resource is the lock list, with or without peek (#326).
    if not str(body.get("resource") or "").strip():
        return _hold_list(c, project)
    key = resource_name(str(body.get("resource") or ""))
    # Read path. mill_hold_upsert inserts, takes, and refreshes (#223).
    if body.get("peek"):
        out = rec_hold.peek(c._cn, _stored(project), key)
        if out.get("id") is None:
            # A name never held: say so, so a roster typed here is not a silent free peek.
            from agent_coord.server.records import name as rec_name

            what = " (%s is a roster)" % key if rec_name.get(c._cn, key, CONST_ROSTER) is not None else ""
            out["hint"] = "no hold named %s%s; mill hold --peek lists every lock" % (key, what)
        return out
    rows = rec_hold.upsert(c._cn, _stored(project), _stored(owner or ""), key)
    rec = rows[0] if rows else {}
    ok = int(rec.get("ok") if rec.get("ok") is not None else 1) == 1
    owner_name = _stored(owner or "")
    if not ok:
        try:
            holder_id = int(rec.get("desk_id") or 0)
        except (TypeError, ValueError):
            holder_id = 0
        named = name_by_id(c._cn, holder_id) if holder_id else ""
        owner_name = _stored(named or "")
    out = {
        "ok": ok,
        "resource": _stored(_stored(key)),
        "id": rec.get("id"),
        "owner": owner_name if not ok else owner,
        "held": ok,
        # Card 853: callers dedupe wake holds via refreshed; since stays the take time.
        "refreshed": bool(int(rec.get("refreshed") or 0)) if ok else False,
    }
    if ok and rec.get("since") is not None:
        out["since"] = str(rec.get("since"))[:26]
    # A refused hold is not news. Poking would look like a new lease (#142).
    if ok:
        _poke(c, "hold", rec.get("id"), "hold", owner=owner)
    return out


def _h_drop(c: Book, body: dict[str, Any], project: str, owner: str | None) -> Any:
    from agent_coord.server.records import hold as rec_hold

    from agent_coord.helpers.bounds import resource_name

    project = project or _office(getattr(c, "_cn", None))
    _require_live_project(getattr(c, "_cn", None), project, "drop")
    key = resource_name(str(body.get("resource") or ""))
    out = rec_hold.drop(c._cn, _stored(project), _stored(owner or ""), key)
    if out.get("released"):
        _poke(c, "hold", out.get("id"), "drop", owner=owner)
    return out


def _hold_list(c: Book, project: str) -> Any:
    """hold --peek with no resource: every lock held. Read only (#234)."""
    from agent_coord.server.records import hold as rec_hold
    from agent_coord.server.records import name as rec_name

    who = _stored(project)
    if not who or rec_name.get(c._cn, who, CONST_ROSTER) is None:
        raise CoordError("hold: unknown project %s" % (who or "(empty)"))
    holds = []
    for rec in rec_hold.find(c._cn, held=True) or []:
        desk = _stored(str(rec.get("desk") or ""))
        if not desk:
            continue
        resource = rec.get("resource")
        if resource is None or str(resource) == "":
            continue
        holds.append(
            {
                "resource": str(resource),
                "owner": desk,
                "id": rec.get("id"),
                "since": rec.get("updated"),
                # Roster and labels for --group-by (#274); holds list flat by default.
                "roster": _stored(rec.get("roster") or "") or None,
                "labels": _json_names(rec.get("labels")),
            }
        )
    return {"ok": True, "project": who, "holds": holds}


def _h_score(c: Book, body: dict[str, Any], project: str, owner: str | None) -> Any:
    """#288: NAME VALUE records a point; NAME --target/--better/--unit sets them (#306);
    retire removes the score (#302); NAME reads the series; neither lists the roster."""
    from agent_coord.helpers.errors import CoordError
    from agent_coord.server import score_series as ss
    from agent_coord.server.records import score as rec_score

    name = str(body.get("name") or body.get("kpi") or "").strip()
    raw = body.get("value")
    roster = _stored(project)
    has_value = raw is not None and str(raw).strip() != ""
    at = str(body.get("at") or "").strip() or None
    if body.get("retire"):
        if not name:
            raise CoordError("score: retire needs ROSTER NAME")
        if has_value or at:
            raise CoordError("score: retire takes no VALUE or --at; nothing changed")
        from agent_coord.server.admin.guard import is_role_admin

        try:
            rows = rec_score.retire(
                c._cn, roster, _stored(owner or ""), name, admin=is_role_admin(c._cn, _stored(owner or ""))
            )
        except Exception as e:
            text = str(e)
            if "no such score" in text:
                raise CoordError(f"score: no score {name} on {project}; nothing retired") from e
            if "only a desk" in text:
                raise CoordError(
                    f"score: only a desk that recorded on {name}, or Admin, can retire it; nothing retired"
                ) from e
            raise
        nid = (rows[0] or {}).get("id") if rows else None
        return {"score": name, "id": nid, "retired": True}
    target = body.get("target")
    if target is not None and str(target).strip() != "":
        if ss.number(target) is None:
            raise CoordError(f"score: --target must be a number, got {str(target)[:40]!r}; nothing stored")
        target = str(target).strip()
    else:
        target = None
    better = str(body.get("better") or "").strip() or None
    if better is not None and better not in ("up", "down"):
        raise CoordError("score: --better must be up or down; nothing stored")
    unit = str(body.get("unit") or "").strip() or None
    if unit is not None and len(unit) > 16:
        raise CoordError("score: --unit must be 1..16 characters; nothing stored")
    note = str(body.get("note") or "")
    if len(note) > ss.NOTE_MAX:
        # #707: say the limit, not the book's column error.
        raise CoordError(
            f"score: --note is {len(note)} characters; the most is {ss.NOTE_MAX}, one line; nothing stored"
        )
    if at and not has_value:
        raise CoordError("score: --at needs a VALUE; nothing stored")
    if at and not ss.at_ok(at):
        raise CoordError("score: --at must be YYYY-MM-DD[THH:MM[:SS]] or Nm, Nh, Nd ago; nothing stored")
    if has_value:
        value = ss.number(raw)
        if value is None:
            raise CoordError(f"score: VALUE must be a number, got {str(raw)[:40]!r}; nothing stored")
        try:
            rows = rec_score.point_add(
                c._cn,
                roster,
                _stored(owner or ""),
                name,
                value,
                target=target,
                note=note,
                better=better,
                unit=unit,
                at=at,
            )
        except Exception as e:
            text = str(e)
            if "--at" in text:
                raise CoordError(text[text.index("score:"):] + "; nothing stored") from e
            raise
    elif name and (target is not None or better is not None or unit is not None):
        if str(body.get("note") or "").strip():
            raise CoordError("score: --note goes with a VALUE; nothing stored")
        rows = rec_score.define(c._cn, roster, _stored(owner or ""), name, target=target, better=better, unit=unit)
    else:
        rows = None
    if rows is not None:
        nid = (rows[0] or {}).get("id") if rows else None
        _poke(c, "score", nid, "score", owner=owner)
        got = ss.shape(rec_score.points(c._cn, roster, name, ss.TREND_POINTS), 0) if nid else []
        return got[0] if got else rows
    limit = int(body.get("limit") or 10)
    if name:
        got = ss.shape(rec_score.points(c._cn, roster, name, max(limit, ss.TREND_POINTS)), limit)
        if not got:
            raise CoordError(f"score: no score {name} on {project}; record one with mill score {project} {name} VALUE")
        return got[0]
    return {"roster": project, "scores": ss.shape(rec_score.points(c._cn, roster, "", ss.TREND_POINTS), 0)}


def _poke_tree(c: Book, typ: str, nid: int, *, owner: str | None = None) -> None:
    _poke(c, typ, nid, typ.upper(), owner=owner)
    from agent_coord.server.records.db import after_commit

    after_commit(c._cn, lambda: _poke_tree_rooms(c, typ, nid, owner=owner))


def _poke_tree_rooms(c: Book, typ: str, nid: int, *, owner: str | None = None) -> None:
    try:
        from agent_coord.server.records import tree as rec_tree
        from agent_coord.server.records.name import by_id
        from agent_coord.server.push import HUB, _desk_room_keys

        payload = {"type": typ, "id": int(nid), "hint": typ.upper()}
        me = _desk_room_keys(_stored(owner or "")) if owner else []
        for row in rec_tree.watchers(c._cn, typ, int(nid)) or []:
            desk = _stored(row.get("desk") or "")
            if me and _desk_room_keys(desk) == me:
                continue
            for k in _desk_room_keys(desk):
                if k in HUB.rooms:
                    HUB.notify(k, payload)
    except Exception:
        pass


def _tree_id(c: Book, typ: str, raw: Any, ref: Any, command: str) -> int:
    """A tree command's id, or its todo named ROSTER/NEED resolved to the id (#706, as #274)."""
    nid = int(raw or 0)
    if not nid and ref:
        nid = _card_ref_id(c._cn, {"ref": ref, "type": typ}, command)
    return nid


def _h_attach(c: Book, body: dict[str, Any], project: str, owner: str | None) -> Any:
    from agent_coord.server.records import tree as rec_tree

    parent_t = str(body.get("type_a") or body.get("parent_type") or "")
    parent_id = _tree_id(c, parent_t, body.get("id_a") or body.get("parent_id"), body.get("ref_a"), "attach")
    child_t = str(body.get("type_b") or body.get("type") or "")
    child_id = _tree_id(c, child_t, body.get("id_b") or body.get("id"), body.get("ref_b"), "attach")
    tree = str(body.get("tree") or "")
    rows = rec_tree.add(c._cn, parent_t, parent_id, child_t, child_id, tree=tree)
    _poke_tree(c, child_t, child_id, owner=owner)
    return rows


def _raise_move_plan(
    exc: BaseException,
    c: Book,
    child_t: str,
    child_id: int,
    parent_t: str,
    parent_id: int,
    tree: str,
) -> None:
    """Turn a raw plan signal into a named error (#225)."""
    from agent_coord.server.records import tree as rec_tree

    text = str(exc)
    if "tree parent not found" in text:
        parent_plans = rec_tree.plan_names(c._cn, parent_t, parent_id)
        where = tree or "the named plan"
        if parent_plans:
            raise CoordError(
                "move: parent is on %s, not on %s" % (", ".join(parent_plans), where)
            ) from exc
        raise CoordError("move: tree parent not found on %s" % where) from exc
    plans = rec_tree.plan_names(c._cn, child_t, child_id)
    if len(plans) > 1:
        raise CoordError("move: card is on %s; --tree picks one" % ", ".join(plans)) from exc
    raise CoordError("move: --tree picks one plan") from exc


def _h_move(c: Book, body: dict[str, Any], project: str, owner: str | None) -> Any:
    from agent_coord.server.records import tree as rec_tree

    child_t = str(body.get("type") or body.get("type_b") or "")
    child_id = _tree_id(c, child_t, body.get("id") or body.get("id_b"), body.get("ref"), "move")
    parent_t = str(body.get("parent_type") or body.get("type_a") or "")
    parent_id = _tree_id(c, parent_t, body.get("parent_id") or body.get("id_a"), body.get("parent_ref"), "move")
    tree = str(body.get("tree") or "").strip()
    if not tree:
        plans = rec_tree.plan_names(c._cn, child_t, child_id)
        if len(plans) > 1:
            raise CoordError("move: card is on %s; --tree picks one" % ", ".join(plans))
    try:
        rows = rec_tree.move(c._cn, child_t, child_id, parent_t, parent_id, tree=tree)
    except CoordError:
        raise
    except Exception as exc:
        text = str(exc)
        if "tree parent not found" in text or "more than one plan" in text or "which TREE_" in text:
            _raise_move_plan(exc, c, child_t, child_id, parent_t, parent_id, tree)
        raise
    _poke_tree(c, child_t, child_id, owner=owner)
    return rows


def _h_prune(c: Book, body: dict[str, Any], project: str, owner: str | None) -> Any:
    from agent_coord.server.records import tree as rec_tree

    typ = str(body.get("type") or body.get("type_b") or "")
    nid = _tree_id(c, typ, body.get("id") or body.get("id_b"), body.get("ref"), "prune")
    tree = str(body.get("tree") or "")
    rows = rec_tree.prune(c._cn, typ, nid, tree=tree)
    _poke_tree(c, typ, nid, owner=owner)
    return rows


def _h_detach(c: Book, body: dict[str, Any], project: str, owner: str | None) -> Any:
    from agent_coord.server.records import tree as rec_tree

    typ = str(body.get("type") or body.get("type_b") or "")
    nid = _tree_id(c, typ, body.get("id") or body.get("id_b"), body.get("ref"), "detach")
    tree = str(body.get("tree") or "")
    rows = rec_tree.remove(c._cn, typ, nid, tree=tree)
    _poke_tree(c, typ, nid, owner=owner)
    return rows


def _json_names(raw: Any) -> list[str]:
    """A JSON array of names from a list SP (labels), as a list. NULL or bad text -> []."""
    if not raw:
        return []
    import json

    try:
        got = json.loads(raw if isinstance(raw, str) else bytes(raw).decode("utf-8"))
    except (TypeError, ValueError):
        return []
    return [str(x) for x in got if isinstance(x, str)] if isinstance(got, list) else []


def _card_ref_id(cn, body: dict[str, Any], command: str) -> int:
    """A todo named ROSTER/NEED (body ref) -> its id (#274). 0 when the body has no ref."""
    ref = str(body.get("ref") or "").strip()
    if not ref:
        return 0
    command = {"label-add": "label", "label-remove": "unlabel"}.get(command, command)
    typ = str(body.get("type") or body.get("kind") or "").strip().lower()
    if typ == CONST_HOLD:
        return _hold_ref_id(cn, ref, command)
    if typ != "todo":
        raise CoordError(
            f"{command}: only a todo (ROSTER/NEED) or a hold (its name) goes by name; "
            f"give the {typ or 'activity'} id"
        )
    roster, _, need = ref.partition("/")
    roster, need = _stored(roster.strip()), need.strip()
    if not roster or not need or len(roster) > 64 or len(need) > 64:
        raise CoordError(f"{command}: give the todo as ROSTER/NEED (for example cold-test/fix-login)")
    from agent_coord.server.records import name as rec_name
    from agent_coord.server.records import todo as rec_todo

    if need.isdigit():
        raise CoordError(f"{command}: {need} is a todo id; give the number alone, not {roster}/{need}")
    if rec_name.get(cn, roster, CONST_ROSTER) is None:
        raise CoordError(f"{command}: no roster {roster}")
    row = rec_todo.find(cn, roster, need)
    if not row:
        raise CoordError(f"{command}: no card {need} in {roster} (mill todo {roster} --done lists its cards)")
    return int(row.get("id") or 0)


def _hold_ref_id(cn, name: str, command: str) -> int:
    """A hold named by its resource -> the hold id (#327). A released hold keeps its row."""
    from agent_coord.server.records import hold as rec_hold

    got = rec_hold.peek(cn, "", name)
    if not got.get("id"):
        raise CoordError(f"{command}: no hold named {name[:120]} (mill hold lists every lock)")
    return int(got["id"])


def _add_target(body: dict[str, Any], command: str, cn=None) -> tuple[str, int]:
    """TARGET of mill add/remove: an activity type and a positive id (#265), or a todo ROSTER/NEED (#274)."""
    typ = str(body.get("type") or "").strip().lower()
    try:
        nid = int(body.get("id") or 0)
    except (TypeError, ValueError):
        nid = 0
    if not nid and body.get("ref") and cn is not None:
        nid = _card_ref_id(cn, body, command)
    if typ not in ACTIVITY_TYPES or nid <= 0:
        raise CoordError(
            "%s: TARGET is type:id, type one of %s" % (command, "|".join(ACTIVITY_TYPES))
        )
    return typ, nid


def _add_who(c: Book, body: dict[str, Any], owner: str | None, command: str) -> tuple[str, str, int]:
    """WHO of mill add/remove: (name, kind, name id). Default this desk.

    A desk wins when a desk and a roster share the name. Another desk or any
    roster follows the member-add trust rule.
    """
    from agent_coord.server.admin.guard import require_admin_if_limited
    from agent_coord.server.records import name as rec_name

    self_desk = _stored(owner or "")
    who = _stored(str(body.get("who") or "")) or self_desk
    if not who or len(who) > 64:
        raise CoordError(f"{command}: WHO is a desk or roster name")
    kind = _live_dest_kind(c._cn, who)
    if not kind:
        raise CoordError(f"{command}: no such desk or roster {who}")
    nid = rec_name.get(c._cn, who, kind)
    if nid is None:
        raise CoordError(f"{command}: no such desk or roster {who}")
    if kind != CONST_DESK or who != self_desk:
        require_admin_if_limited(c._cn, self_desk)
    return who, kind, int(nid)


def _sql_refusal(exc: BaseException) -> str | None:
    """A SIGNAL SQLSTATE 45000 is a refusal written for people: its text, no code prefix (#270)."""
    if str(getattr(exc, "sqlstate", "") or "") == "45000":
        msg = str(getattr(exc, "msg", "") or "").strip()
        return msg or None
    # 0.8.0: a kind-checked FK (1452) or a CHECK (3819) refusal, in plain words.
    from agent_coord.server.records.db import fk_refusal

    return fk_refusal(exc)


def _h_add_remove(c: Book, body: dict[str, Any], project: str, owner: str | None) -> Any:
    """mill add|remove TYPE:ID [WHO]: SQL refusals come back as one plain line (#270)."""
    del project  # the target decides, not the seat roster
    try:
        return _add_remove(c, body, owner)
    except CoordError:
        raise
    except Exception as exc:
        msg = _sql_refusal(exc)
        if msg is None:
            raise
        raise CoordError(msg) from exc


def _add_remove(c: Book, body: dict[str, Any], owner: str | None) -> Any:
    """mill add|remove TYPE:ID [WHO] (#265). One pair, branching on the target kind.

    mail: WHO's recipient rows on that letter and every letter under it (node).
    Watchers never watch mail. Every other kind: one watcher row (type, id, WHO);
    a roster row expands to its members when it wakes them. --hint is add-only
    and watcher-only.
    """
    from agent_coord.client.outbound import canonical_command
    from agent_coord.helpers.bounds import bound_watcher_hint
    from agent_coord.server.records import mail as rec_mail
    from agent_coord.server.records import watcher as rec_w
    from agent_coord.server.records.label import _activity_live

    command = canonical_command(str(body.get("verb") or ""))
    if command not in ("add", "remove"):
        raise CoordError("add/remove: command is add or remove")
    typ, nid = _add_target(body, command, c._cn)
    raw_hint = body.get("hint")
    has_hint = raw_hint is not None and str(raw_hint) != ""
    if has_hint and (command != "add" or typ == CONST_MAIL):
        raise CoordError(f"{command}: --hint is for add on a watched kind, not {typ}")
    if not _activity_live(c._cn, typ, nid):
        raise CoordError(f"{command}: no {typ} {nid}")
    who, kind, who_id = _add_who(c, body, owner, command)
    out: dict[str, Any] = {"ok": True, "verb": command, "type": typ, "id": nid, "who": who, "kind": kind}
    if typ == CONST_MAIL:
        # #sec S-3: only a desk that can already read this letter may change who
        # is on it (including adding itself). Admin, sender, recipient, or a
        # participant of its room.
        # #672 S-3: every desk reads every letter, so any seated desk may add
        # itself (a visible join without posting), as a reply would join it.
        # Adding or removing another desk still needs the caller to be the
        # sender, a recipient, a participant of its room, or Admin.
        self_join = command == "add" and kind == CONST_DESK and who == _stored(owner or "")
        if not self_join and not _mail_reader(c, nid, owner):
            raise CoordError(
                f"{command}: not allowed on mail {nid}; "
                "you are not its sender, a recipient, or a participant of its room "
                "(you may add yourself)"
            )
        if command == "add":
            before = {_stored(r.get("desk") or "") for r in rec_mail.to_list(c._cn, nid) or []}
            out.update(rec_mail.to_node_put(c._cn, nid, who_id))
            try:
                from agent_coord.server.mail_push import compact_mail
                from agent_coord.server.push import emit

                letter = rec_mail.letter_row(c._cn, nid)
                dests = rec_mail.to_list(c._cn, nid) or []
                for row in dests:
                    d = _stored(row.get("desk") or "")
                    if d and d not in before and letter:
                        emit(c._cn, d, "mail", compact_mail(letter, dests, d))
            except Exception:
                pass
        else:
            out.update(rec_mail.to_node_delete(c._cn, nid, who_id))
        return out
    if command == "add":
        hint = bound_watcher_hint(str(raw_hint or ""))
        out["rows"] = rec_w.set_hint(c._cn, typ, nid, who_id, hint)
        out["hint"] = hint or None
        return out
    from agent_coord.server.records.db import scalar

    if scalar(c._cn, "SELECT 1 FROM watcher WHERE type = %s AND id = %s AND desk_id = %s",
              (typ, nid, who_id)) is None:
        raise CoordError(f"remove: {who} is not watching {typ}:{nid}")
    rec_w.delete(c._cn, typ, nid, who_id)
    out["removed"] = 1
    return out


def _h_trust(c: Book, body: dict[str, Any], project: str, owner: str | None) -> Any:
    """Office trust. Read is any seated desk. Set is Admin, from anywhere."""
    from agent_coord.config import mill_trust, set_mill_trust
    from agent_coord.server.admin.guard import require_admin

    level = str(body.get("level") or body.get("trust") or "").strip().lower()
    if not level:
        return {"trust": mill_trust()}
    if level not in ("high", "limited"):
        raise CoordError("mill trust: high or limited")
    require_admin(c._cn, owner or "")
    # 0.8.0 (schema-design.md section 9): config.toml first, then b_trust() from it. If the
    # function cannot be re-created, the file goes back, so the two never disagree.
    from agent_coord.config import config_path
    from agent_coord.server.records.trust_fn import init_trust_fn

    path = config_path()
    before = path.read_bytes() if path.is_file() else None
    set_mill_trust(level)
    try:
        init_trust_fn(c._cn, level)
    except Exception:
        if before is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(before)
        raise
    return {"ok": True, "trust": level}



def _h_invite_seat(c: Book, body: dict[str, Any], project: str, owner: str | None) -> Any:
    """Mint one agent seat invite URL (ready). Admin agent Bearer; humans use HTTP.

    Project is body.project (--project) when set; else that desk's one project
    membership. Never the minter's connect project (#252).
    """
    from agent_coord.server.admin.guard import require_invite_seat_mint
    from agent_coord.server.admin.seats import mint_seat

    require_invite_seat_mint(c._cn, owner or "", human_ok=False)
    desk = str(body.get("desk") or body.get("target") or "").strip()
    if not desk:
        raise CoordError("invite-seat: desk required")
    from agent_coord.server.admin.seats import resolve_seat_roster

    proj = resolve_seat_roster(c._cn, desk, str(body.get("project") or ""))
    return mint_seat(
        c._cn,
        desk=desk,
        project=proj,
        created_by=owner or "",
        doing=str(body.get("doing") or "invited")[:64],
    )


def _h_invite(c: Book, body: dict[str, Any], project: str, owner: str | None) -> Any:
    """Invite board lives in the book. The wall runs it; the client does not open MySQL."""
    from agent_coord.server.admin import door as door_mod
    from agent_coord.server.admin.guard import require_admin

    require_admin(c._cn, owner or "")
    lan = body.get("lan_only")
    if lan not in (None, ""):
        from agent_coord.server.netbind import set_lan_only

        on = str(lan).strip().lower() not in ("off", "0", "false", "no")
        return set_lan_only(on)
    if body.get("door"):
        return door_mod.set_door(str(body.get("door") or ""), rotate=bool(body.get("rotate")))
    if body.get("ttl") and body.get("ttl_for"):
        return door_mod.set_key_ttl(str(body.get("ttl_for") or ""), body.get("ttl"))
    if body.get("mint") or body.get("rotate"):
        return door_mod.mint_key(
            label=str(body.get("label") or ""),
            ttl=body.get("ttl") or None,
            created_by=owner or "",
        )
    if body.get("enable"):
        return door_mod.enable_key(str(body.get("enable") or ""))
    if body.get("revoke"):
        return door_mod.revoke_key(str(body.get("revoke") or ""))
    return door_mod.board_packet()


def _note_doing(c: Book, project: str, owner: str | None, command: str) -> None:
    """A command that writes nothing else bumps the seat; doing stays the desk's (#635)."""
    from agent_coord.server.records.doing_stack import BUMP_COMMANDS

    if command not in BUMP_COMMANDS or not owner:
        return
    try:
        from agent_coord.server.records import join as rec_join

        rec_join.touch(c._cn, project, owner)
    except Exception:
        try:
            c._cn.rollback()
        except Exception:
            pass


TRAIL_MAX_NODES = 500
# trail --label stops adding rows once their JSON passes this many bytes (#199).
LABEL_LIST_MAX_BYTES = 8192


def _trail_target(c: Book, body: dict[str, Any]) -> tuple[str, int]:
    """(kind, id) from `mill trail <id>`; mail:N or todo:N when both exist."""
    import re

    if str(body.get("type") or "").strip():
        raise CoordError("trail: --type is not a flag; use mail:N or todo:N")
    raw = str(body.get("node") or body.get("id") or "").strip().lower()
    m = re.fullmatch(r"(?:(mail|todo):)?(\d+)", raw)
    if not m:
        raise CoordError("trail: give a mail id or todo id (mail:N or todo:N when both exist)")
    pre, nid = m.group(1) or "", int(m.group(2))
    kind = pre
    if nid <= 0:
        raise CoordError("trail: id must be positive")
    from agent_coord.server.records.db import scalar

    def _exists(k: str) -> bool:
        return scalar(c._cn, "SELECT 1 FROM activity WHERE type = %s AND id = %s", (k, nid)) is not None

    if kind:
        if not _exists(kind):
            raise CoordError(f"trail: no such {kind} {nid}")
        return kind, nid
    is_mail, is_todo = _exists("mail"), _exists("todo")
    if is_mail and is_todo:
        raise CoordError(f"trail: {nid} is both mail {nid} and todo {nid}; say mail:{nid} or todo:{nid}")
    if is_mail:
        return "mail", nid
    if is_todo:
        return "todo", nid
    raise CoordError(f"trail: no mail or todo {nid}")


def _label_created(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat(sep=" ", timespec="microseconds")
    return str(value)


def _h_trail_label(c: Book, body: dict[str, Any], project: str, owner: str | None, tag: str) -> Any:
    """Mail and todo wearing one label, ord then created (#199).

    Unknown label: empty rows and a hint, not an error. Every seated desk reads
    every labelled mail (#672, S-3). Deleted activity is left out. The row list
    is byte-capped.
    """
    import json

    from agent_coord.const import CONST_LABEL
    from agent_coord.config import mill_catalog_open
    from agent_coord.helpers.label_ord import unused_label
    from agent_coord.helpers.trail_text import clip, first_line
    from agent_coord.server.records import label as rec_label
    from agent_coord.server.records import name as rec_name
    from agent_coord.server.records import todo as rec_todo
    from agent_coord.server.records import tree as rec_tree

    if not owner:
        raise CoordError("trail: owner required")
    stored = rec_name.bare(tag, CONST_LABEL)
    if rec_name.get(c._cn, stored, CONST_LABEL) is None:
        return {
            "label": stored,
            "hint": unused_label(stored, mill_catalog_open(CONST_LABEL)),
            "rows": [],
            "truncated": False,
        }
    found = rec_label.rows_for(c._cn, stored)
    info = rec_tree.trail_details(c._cn, [(str(r["type"]), int(r["id"])) for r in found])
    rows: list[dict[str, Any]] = []
    used = 0
    truncated = False
    for raw in found:
        typ = str(raw["type"])
        nid = int(raw["id"])
        d = info.get((typ, nid)) or {}
        if d.get("deleted_utc") is not None:
            continue
        if typ == "mail":
            text_body = clip(first_line(_read_redact(d.get("mail_body") or "")))
            text_need = ""
        else:
            fields = rec_todo.unpack(d.get("todo_body") or "", nid)
            detail = first_line(fields.get("detail") or "")
            slug = str(fields.get("need_id") or "")
            text_need = clip(detail or slug)
            text_body = ""
        row = {
            "id": nid,
            "type": typ,
            "ord": int(raw.get("ord") or 0),
            "body": text_body,
            "need": text_need,
            "created": _label_created(raw.get("created")),
        }
        blob = json.dumps(row, separators=(",", ":")).encode("utf-8")
        if rows and used + len(blob) > LABEL_LIST_MAX_BYTES:
            truncated = True
            break
        rows.append(row)
        used += len(blob)
    return {"label": stored, "hint": "", "rows": rows, "truncated": truncated}


@_ends_read
def _h_trail(c: Book, body: dict[str, Any], project: str, owner: str | None) -> Any:
    """Read-only branch under a mail or todo: mail + todo children, any depth.

    Structure from mill_tree_subtree; one detail read. Done/shipped/deleted stay
    visible. Last note 'dead-end:' / 'solved:' marks the node.
    --label lists mail and todo wearing that label instead of walking a tree.
    """
    from agent_coord.helpers.ptime import pt_label
    from agent_coord.helpers.trail_text import clip, first_line, last_line, mark_of
    from agent_coord.server.records import todo as rec_todo
    from agent_coord.server.records import tree as rec_tree

    label = str(body.get("label") or "").strip()
    node = str(body.get("node") or body.get("id") or "").strip()
    if label and node:
        raise CoordError("trail: say a node or --label, not both")
    if label:
        return _h_trail_label(c, body, project, owner, label)
    if not owner:
        raise CoordError("trail: owner required")
    kind, nid = _trail_target(c, body)
    tree = rec_tree.node_tree(c._cn, kind, nid)
    if tree:
        struct = rec_tree.subtree(c._cn, tree, kind, nid) or [{"type": kind, "id": nid, "lft": 1, "rgt": 2}]
    else:
        struct = [{"type": kind, "id": nid, "lft": 1, "rgt": 2}]
    # depth over mail/todo ancestors only (join/hold/score nodes are skipped)
    stack: list[tuple[int, bool]] = []
    shaped: list[tuple[str, int, int]] = []
    for r in struct:
        lft, rgt = int(r.get("lft") or 0), int(r.get("rgt") or 0)
        while stack and stack[-1][0] < lft:
            stack.pop()
        typ = str(r.get("type") or "")
        shown = typ in ("mail", "todo")
        depth = sum(1 for _r, s in stack if s)
        if shown:
            shaped.append((typ, int(r.get("id") or 0), depth))
        stack.append((rgt, shown))
    truncated = len(shaped) > TRAIL_MAX_NODES
    shaped = shaped[:TRAIL_MAX_NODES]
    info = rec_tree.trail_details(c._cn, [(t, i) for t, i, _d in shaped])
    # Mail read access = mail-thread rule (#672, S-3): every seated desk reads
    # every letter; the read adds no participant.

    nodes: list[dict[str, Any]] = []
    for typ, i, depth in shaped:
        d = info.get((typ, i)) or {}
        node: dict[str, Any] = {"kind": typ, "id": i, "depth": depth}
        deleted = d.get("deleted_utc") is not None
        if typ == "todo":
            fields = rec_todo.unpack(d.get("todo_body") or "", i)
            st = "deleted" if deleted else str(d.get("todo_status") or ("deleted" if not d else "open"))
            note = last_line(fields.get("detail") or "")
            idea = first_line(fields.get("detail") or "")
            title = fields.get("need_id") or ""
            if idea and idea != note and idea != title:
                title = f"{title}: {idea}"
            when = d.get("todo_updated_utc") or d.get("updated_utc")
            node.update(
                {
                    "need_id": fields.get("need_id") or "",
                    "state": st,
                    "title": clip(title),
                    "last_note": clip(note),
                    "mark": mark_of(note),
                    "who": _stored(d.get("todo_assigned") or d.get("todo_creator") or ""),
                    "asker": _stored(d.get("todo_creator") or ""),
                    "volunteer": _stored(d.get("todo_assigned") or ""),
                }
            )
        else:
            src = str(d.get("mail_src") or d.get("actor") or "")
            when = d.get("mail_created_utc") or d.get("updated_utc")
            first = first_line(_read_redact(d.get("mail_body") or ""))
            node.update(
                {
                    "state": "deleted" if (deleted or d.get("mail_body") is None) else "sent",
                    "title": clip(first),
                    "last_note": "",
                    "mark": mark_of(first),
                    "who": _stored(src),
                }
            )
        node["at_utc"] = when.strftime("%Y-%m-%dT%H:%M:%SZ") if when is not None else ""
        node["at_pt"] = pt_label(when)
        nodes.append(node)
    return {
        "root": {"kind": kind, "id": nid},
        "tree": tree if tree and not rec_tree.is_hidden_tree(tree) else "",
        "on_tree": bool(tree),
        "nodes": nodes,
        "truncated": truncated,
    }


def _h_probe_delete(c: Book, body: dict[str, Any], project: str, owner: str | None) -> Any:
    """Test-only (#160): soft-delete the caller's own t-<8 hex> todo or score."""
    from agent_coord.server import probe_delete

    return probe_delete.handle(c, body, project, owner)


# Handled is the only result. There is no state parameter (#242).


def _mark_ids(body: dict[str, Any]) -> list[int]:
    raw = body.get("ids")
    if isinstance(raw, int):
        raw = [raw]
    elif isinstance(raw, str):
        raw = [part for part in raw.replace(",", " ").split() if part]
    if not isinstance(raw, list) or not raw:
        one = body.get("mail_id") if body.get("mail_id") is not None else body.get("id")
        raw = [one] if one not in (None, "") else []
    if not raw:
        raise CoordError("mark: at least one mail id")
    ids: list[int] = []
    for item in raw:
        try:
            n = int(item)
        except (TypeError, ValueError) as e:
            raise CoordError("mark: mail id required") from e
        if n <= 0:
            raise CoordError("mark: mail id required")
        ids.append(n)
    return ids


def _h_mark(c: Book, body: dict[str, Any], project: str, owner: str | None) -> Any:
    """Mark letters handled for this desk. A fetch does not do this (#195)."""
    from agent_coord.server.records import mail as rec_mail
    from agent_coord.server.records import opened as rec_opened

    if not owner:
        raise CoordError("mark: owner required")
    if "state" in body:
        raise CoordError("mark: --state is not a flag")
    ids = _mark_ids(body)
    who = _stored(owner)
    for mid in ids:
        if not rec_mail.get(c._cn, mid):
            raise CoordError("mark: no such mail %s" % mid)
        dests = rec_mail.to_list(c._cn, mid)
        if who not in {_stored(row.get("desk") or "") for row in dests}:
            raise CoordError("mark: mail %s is not in this desk's mailbox" % mid)
    for mid in ids:
        rec_opened.insert(c._cn, mid, who)
    return {"ok": True, "state": "handled", "ids": ids}


def _h_wake_done(c: Book, body: dict[str, Any], project: str, owner: str | None) -> Any:
    """mill wake-done [--lease ID] [--note TEXT] (F144): the calling desk's woken run is
    finished. Ends that desk's own wake lease, only the one ID names when given
    (F144b: a stale ID ends nothing); held-back items ring once with the note."""
    from agent_coord.server import wake

    if not owner:
        raise CoordError("wake-done: owner required")
    got = wake.lease_done(getattr(c, "_cn", None), owner, note=str(body.get("note") or ""),
                          lease=str(body.get("lease") or ""))
    return {"ok": True, "desk": owner, "wake": got}


HANDLERS = {
    "wake-done": _h_wake_done,
    "inbox": _h_inbox,
    "todo": _h_todo,
    "session": _h_session,
    "project": _h_project,
    "join": _h_here,
    "label": _h_label_name,
    "label-add": _h_label,
    "label-remove": _h_label,
    "member": _h_member,
    "member-add": _h_member,
    "member-remove": _h_member,
    "rename": _h_rename,
    "retire": _h_retire,
    "roster": _h_roster,
    "reclaim": _h_reclaim,
    "reset": _h_reset,
    "send": _h_send,
    "reply": _h_reply,
    "mail-thread": _h_mail_thread,
    "mark": _h_mark,
    "assign": _h_assign,
    "claim": _h_claim,
    "open": _h_open,
    "unpark": _h_unpark,
    "unclaim": _h_yield,
    "pass": _h_pass,
    "glance": _h_glance,
    "note": _h_note,
    "hold": _h_hold,
    "drop": _h_drop,
    "score": _h_score,
    "attach": _h_attach,
    "move": _h_move,
    "prune": _h_prune,
    "detach": _h_detach,
    "add": _h_add_remove,
    "remove": _h_add_remove,
    "invite": _h_invite,
    "invite-seat": _h_invite_seat,
    "trust": _h_trust,
    "trail": _h_trail,
    "probe-delete": _h_probe_delete,
}


JOIN_TYPE_GONE = (
    "{command}: type join is gone; the activity is doing now (mill 0.7.16)."
    " This mill client is older than the office: pip install -U the-mill, then use doing."
)


def _refuse_join_type(command: str, body: dict[str, Any]) -> None:
    """#818: a TYPE of join comes only from a client older than the office.
    Refuse it plainly, before any handler or SQL, and name the upgrade."""
    if command == "join":
        return
    for key in ("type", "type_b", "kind"):
        if str(body.get(key) or "").strip().lower() == "join":
            raise CoordError(JOIN_TYPE_GONE.format(command=command or "mill"))


def dispatch(c: Book, body: dict[str, Any], *, token: str = "") -> Any:
    from agent_coord.client.outbound import WALL, canonical_command

    command = canonical_command(str(body.get("verb") or body.get("cmd") or ""))

    # Trusted-field hardening: a client cannot carry a server-internal key.
    # `host` on the HTTP path is set by guard.mark_host from the socket peer
    # before dispatch, so only `_`-prefixed internals are stripped here.
    for _k in [k for k in body.keys() if isinstance(k, str) and k.startswith("_")]:
        body.pop(_k, None)

    project_raw = str(body.get("project") or "").strip() or "the-mill"
    project = _project_alias(getattr(c, "_cn", None), _stored(project_raw))
    if body.get("project") and project != _stored(project_raw):
        body["project"] = project  # handlers that read the body see id 1's name too
    owner_raw = str(body.get("owner") or "").strip()
    owner = _stored(owner_raw) if owner_raw else None
    if command not in WALL:
        raise CoordError(f"unknown mill command {command}")
    _refuse_join_type(command, body)
    if command not in OPEN_COMMANDS:
        from agent_coord.client.session_errors import (
            SESSION_INVALID_REJOIN,
            SESSION_TOKEN_REQUIRED,
        )

        if not token:
            raise CoordError(SESSION_TOKEN_REQUIRED)

        bearer = c.resolve_bearer(token)
        if not bearer:
            # Cleared token_hash, never connected, or stale local file
            raise CoordError(SESSION_INVALID_REJOIN)
        # Bearer-only: body/env OWNER is a hint. Mismatch does not 400 - force Bearer
        # so stale AGENT_COORD_OWNER cannot block inbox/session (Scout #392).
        # Spoof still impossible: actions run as Bearer desk only.
        owner = _stored(bearer)
        c._tokens[(project, owner)] = token
        c._guard_owner(project, owner, token, must_be_present=True)
        # HTTP desk-acting cut: commands are JSON RPC on the sitting /ws only.
        _require_live_ws(owner)
    else:
        # OPEN_COMMANDS (join) mint a desk with no bearer; gate by the office door.
        _require_join_authorized(c, body, token)
    fn = HANDLERS.get(command)
    if fn is None:
        raise CoordError(f"unknown mill command {command}")
    # #504: redact secrets at mill-wall choke point (CLI cannot bypass)
    from agent_coord.server.redact import WRITE_COMMANDS, scrub_request_body

    if command in WRITE_COMMANDS or canonical_command(command) in WRITE_COMMANDS:
        scrub_request_body(body)
    doing_text = _doing_text(command, body)
    try:
        out = _run_command(c, fn, command, body, project, owner, doing_text)
        try:
            from agent_coord.server import wake_first

            wake_first.note_rpc(owner, command, ok=True)
        except Exception:
            pass
        try:
            from agent_coord.server import commands_to_done

            commands_to_done.note_card(owner, command, out, body=body)
        except Exception:
            pass
        try:
            from agent_coord.server import hold_blocked

            hold_blocked.note_hold(owner, command, out, body=body)
        except Exception:
            pass
        try:
            from agent_coord.server import nest_sor

            nest_sor.note_nest(owner, command, out, body=body)
        except Exception:
            pass
        try:
            from agent_coord.server import mail_sor

            mail_sor.note_mail(owner, command, out, body=body)
        except Exception:
            pass
        _note_doing(c, project, owner, command)
        if owner:
            c.acting_desk = owner
        return out
    except Exception:
        try:
            from agent_coord.server import wake_first

            wake_first.note_rpc(owner, command, ok=False)
        except Exception:
            pass
        raise


_RPC_DONE: OrderedDict[tuple[str, str], Any] = OrderedDict()
_RPC_FLIGHT: dict[tuple[str, str], threading.Event] = {}
_RPC_LOCK = threading.Lock()
_RPC_CAP = 512


def rpc_remembered(desk: str, req_id: str) -> tuple[bool, Any]:
    key = (desk, req_id)
    with _RPC_LOCK:
        if key not in _RPC_DONE:
            return False, None
        _RPC_DONE.move_to_end(key)
        return True, _RPC_DONE[key]


def rpc_claim(desk: str, req_id: str) -> str:
    """owner runs the command. wait means it is in flight. done means the result is cached."""
    key = (desk, req_id)
    with _RPC_LOCK:
        if key in _RPC_DONE:
            return "done"
        if key in _RPC_FLIGHT:
            return "wait"
        _RPC_FLIGHT[key] = threading.Event()
        return "owner"


def rpc_wait(desk: str, req_id: str, timeout: float = 30.0) -> None:
    key = (desk, req_id)
    with _RPC_LOCK:
        ev = _RPC_FLIGHT.get(key)
    if ev is not None:
        ev.wait(timeout)


def rpc_finish(desk: str, req_id: str, result: Any) -> None:
    key = (desk, req_id)
    with _RPC_LOCK:
        _RPC_DONE[key] = result
        _RPC_DONE.move_to_end(key)
        while len(_RPC_DONE) > _RPC_CAP:
            _RPC_DONE.popitem(last=False)
        ev = _RPC_FLIGHT.pop(key, None)
    if ev is not None:
        ev.set()


def rpc_abort(desk: str, req_id: str) -> None:
    key = (desk, req_id)
    with _RPC_LOCK:
        ev = _RPC_FLIGHT.pop(key, None)
    if ev is not None:
        ev.set()


def dispatch_ws(
    c: Book,
    desk: str,
    command: str,
    args: dict[str, Any] | None = None,
    req_id: str | None = None,
    *,
    peer: str = "",
    forwarded: bool = False,
) -> Any:
    """Run a desk-acting command for the sitting /ws desk. Identity is desk, not body owner.

    A repeated req_id returns the first result and does not run the command again (#137).
    """
    from agent_coord.client.outbound import WALL, canonical_command

    v = canonical_command(str(command or ""))
    if not v:
        raise CoordError("ws rpc: command required")
    if v in OPEN_COMMANDS or v == "join":
        raise CoordError("join stays HTTP only; not a /ws RPC command")
    if v not in WALL:
        raise CoordError(f"unknown mill command {v}")
    owner = desk_name(desk)
    if not owner:
        raise CoordError("ws rpc: desk required")
    body = dict(args or {})
    body.pop("owner", None)
    body.pop("--owner", None)
    # Trusted-field hardening (#sec): never trust a server-only key from the
    # client. `host` (the Admin office-host marker) is re-set below only from a
    # verified loopback transport peer, never from the /ws args.
    _strip_server_only(body)
    _refuse_join_type(v, body)
    from agent_coord.server.admin.guard import mark_host

    if peer and not forwarded:
        mark_host(body, peer)
    body["verb"] = v
    project_raw = str(body.get("project") or "").strip() or "the-mill"
    project = _project_alias(getattr(c, "_cn", None), _stored(project_raw))
    if body.get("project") and project != _stored(project_raw):
        body["project"] = project  # handlers that read the body see id 1's name too
    fn = HANDLERS.get(v)
    if fn is None:
        raise CoordError(f"unknown mill command {v}")
    from agent_coord.server.redact import WRITE_COMMANDS, scrub_request_body

    if v in WRITE_COMMANDS or canonical_command(v) in WRITE_COMMANDS:
        scrub_request_body(body)
    rid = str(req_id or "").strip()
    owns_id = False
    if rid:
        remembered, cached = rpc_remembered(owner, rid)
        if remembered:
            return cached
        state = rpc_claim(owner, rid)
        if state == "done":
            remembered, cached = rpc_remembered(owner, rid)
            if remembered:
                return cached
        elif state == "wait":
            rpc_wait(owner, rid, 30.0)
            remembered, cached = rpc_remembered(owner, rid)
            if remembered:
                return cached
            raise CoordError("ws rpc: duplicate request still running")
        else:
            owns_id = True
    try:
        doing_text = _doing_text(v, body)
        out = _run_command(c, fn, v, body, project, owner, doing_text)
        try:
            from agent_coord.server import wake_first

            wake_first.note_rpc(owner, v, ok=True)
        except Exception:
            pass
        try:
            from agent_coord.server import commands_to_done

            commands_to_done.note_card(owner, v, out, body=body)
        except Exception:
            pass
        try:
            from agent_coord.server import hold_blocked

            hold_blocked.note_hold(owner, v, out, body=body)
        except Exception:
            pass
        try:
            from agent_coord.server import nest_sor

            nest_sor.note_nest(owner, v, out, body=body)
        except Exception:
            pass
        try:
            from agent_coord.server import mail_sor

            mail_sor.note_mail(owner, v, out, body=body)
        except Exception:
            pass
        _note_doing(c, project, owner, v)
        if owner:
            c.acting_desk = owner
        if owns_id:
            rpc_finish(owner, rid, out)
        return out
    except Exception:
        if owns_id:
            rpc_abort(owner, rid)
        try:
            from agent_coord.server import wake_first

            wake_first.note_rpc(owner, v, ok=False)
        except Exception:
            pass
        raise
