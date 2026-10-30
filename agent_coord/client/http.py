# -*- coding: utf-8 -*-
"""mill CLI over HTTPS. GitLab-style access token: Authorization: Bearer.

mill here mints the token (like creating a GitLab PAT / PyPI token).
Stored in ~/.mill/session/<owner>.token only. Never AGENT_COORD_TOKEN - agents share env.
Never print the token.
"""
from __future__ import annotations

import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from agent_coord.config import mill_home, settings
from agent_coord.helpers.errors import CoordError
from agent_coord.helpers.ident import slug
from agent_coord.client.tokens import (
    read_session_token,
    resolve_desk_owner,
    write_session_token,
)


def mill_url() -> str:
    from agent_coord.client.offices import office_mill_url

    try:
        office = office_mill_url()
    except ValueError as exc:
        raise CoordError(str(exc)) from exc
    if office:
        return office
    s = settings()
    u = str(s.get("mill_url") or os.environ.get("AGENT_COORD_MILL_URL") or "").strip().rstrip("/")
    if u:
        return u
    bind = str(s.get("dashboard_bind") or "127.0.0.1")
    if bind in ("0.0.0.0", "::", "*"):
        bind = "127.0.0.1"
    port = int(s.get("dashboard_port") or 8765)
    return f"http://{bind}:{port}"


def mill_ca_file() -> Path:
    from agent_coord.client.offices import office_ca_file

    try:
        office = office_ca_file()
    except ValueError as exc:
        raise CoordError(str(exc)) from exc
    if office is not None:
        return office
    return Path.home() / ".mill" / "ssl" / "ca.crt"


def mill_ssl_context() -> ssl.SSLContext:
    ca = mill_ca_file()
    if ca.is_file():
        return ssl.create_default_context(cafile=str(ca))
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


REDIRECT_REFUSED = (
    "redirect refused: the mill client never follows a 3xx while it carries a "
    "credential; join the wall's final https URL"
)


def _open(req, *, context: ssl.SSLContext, timeout: float):
    """Command call and CA fetch: one request, never a redirect (#654)."""
    from agent_coord.helpers.nofollow import open_no_redirect

    return open_no_redirect(req, timeout=timeout, context=context)


def mill_api_key(owner: str = "") -> str:
    """Bearer for the sitting desk only. Never AGENT_COORD_TOKEN (shared env).

    The sitting desk is the connect bridge that shares this process parent pid.
    A hint for any other desk is refused so a command cannot load that token.
    The secret is never in env.
    """
    from agent_coord.helpers.ident import desk as desk_stem

    sitting = (resolve_desk_owner("") or "").strip()
    if not sitting:
        return ""
    hint = (owner or "").strip()
    if hint and desk_stem(hint) != desk_stem(sitting):
        return ""
    try:
        return (read_session_token(sitting) or "").strip()
    except ValueError:
        return ""


def mill_http_call(body: dict[str, Any]) -> Any:
    url = mill_url()
    if not url:
        raise CoordError("mill_url unset; mill join https://wall/")
    command = slug(str(body.get("verb") or body.get("cmd") or ""))
    if not command:
        raise CoordError("mill command required")
    owner = str(body.get("owner") or "")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    from agent_coord.client.offices import read_office_invite

    saved_invite = read_office_invite()
    if saved_invite:
        headers["X-Mill-Invite"] = saved_invite
    payload = dict(body)
    from agent_coord.client.outbound import canonical_command

    command_s = canonical_command(str(payload.get("verb") or payload.get("cmd") or command))
    if command_s == "join":
        # Reconnect only with THIS owner's session file. Never inject AGENT_COORD_TOKEN
        # from another desk into join (Scout #391).
        own = ""
        if owner:
            try:
                own = (read_session_token(owner) or "").strip()
            except ValueError:
                own = ""
        # Caller-supplied token on a join is the seat from a welcome link
        # (offices.join_office). It is not read from AGENT_COORD_TOKEN here.
        explicit = str(payload.get("token") or "").strip()
        if own:
            # Reconnect: this owner's stored session token.
            payload["token"] = own
            key = own
        elif explicit:
            # Cold join: present the seat so the office door can authorize it.
            payload["token"] = explicit
            key = explicit
        else:
            # Open-house (door=path) mint with no credential.
            payload.pop("token", None)
            key = ""
    else:
        payload.pop("token", None)
        # JSON RPC on the sitting connect that shares this process parent pid.
        # Not the host active file. Not argv owner. Not another desk token.
        from agent_coord.client.session_errors import (
            SESSION_TOKEN_REQUIRED,
            SESSION_WS_BRIDGE_REQUIRED,
        )
        from agent_coord.client.ws import mill_ws_call, wait_for_sitting_desk

        # Sitting miss: one short wait, or up to 10s while this parent's connect
        # is still in the handshake (#121, #210).
        who = (resolve_desk_owner("") or "").strip()
        if not who:
            who = (wait_for_sitting_desk() or "").strip()
        if not who:
            from agent_coord.client.ws import busy_for_parent

            # Card 834: this shell's connect was refused as busy; say so, not "no connect".
            raise CoordError(busy_for_parent() or SESSION_WS_BRIDGE_REQUIRED)
        key = mill_api_key(who)
        if not key:
            raise CoordError(SESSION_TOKEN_REQUIRED)
        return mill_ws_call(payload, token=key, desk=who)
    if key:
        headers["Authorization"] = "Bearer " + key
    data = json.dumps(payload).encode("utf-8")
    from agent_coord.client.outbound import command_path

    path = command_path(command)
    try:
        from agent_coord.config import mill_debug

        if mill_debug():
            print({"DEBUG": "http", "path": path, "verb": command_s}, flush=True)
    except Exception:
        pass
    req = urllib.request.Request(
        url + path,
        data=data,
        method="POST",
        headers=headers,
    )
    try:
        with _open(req, context=mill_ssl_context(), timeout=5) as resp:
            raw = resp.read().decode("utf-8")
            if command_s == "join":
                hdrs = getattr(resp, "headers", None)
                warn_wall_version(hdrs.get("X-Mill-Version") if hdrs else "")
            try:
                from agent_coord.config import mill_debug

                if mill_debug():
                    print({"DEBUG": "http", "path": path, "status": getattr(resp, "status", 200)}, flush=True)
            except Exception:
                pass
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", "replace")[:400]
        try:
            from agent_coord.config import mill_debug

            if mill_debug():
                print({"DEBUG": "http", "path": path, "status": e.code, "error": err[:160]}, flush=True)
        except Exception:
            pass
        if 300 <= int(e.code or 0) < 400:
            raise CoordError(f"mill-wall {e.code}: {REDIRECT_REFUSED}") from e
        low = err.lower()
        if owner and key and ("spoof" in low or "bad token" in low or "desk live" in low):
            raise CoordError(f"token/desk mismatch for {owner}") from e
        raise CoordError(f"mill-wall {e.code}: {err}") from e
    except urllib.error.URLError as e:
        raise CoordError(f"mill-wall unreachable: {e}") from e
    try:
        row = json.loads(raw)
    except json.JSONDecodeError as e:
        raise CoordError("mill-wall bad json") from e
    if canonical_command(command) == "join" and isinstance(row, dict):
        tok = str(row.get("token") or "")
        who = slug(str(row.get("owner") or owner))
        if tok and who:
            try:
                write_session_token(who, tok, desk_id=row.get("desk_id"))
            except (OSError, ValueError):
                pass
    return row


def warn_wall_version(server: str) -> None:
    """Join keeps going. stderr only, so the JSON reply stays machine-readable."""
    from agent_coord.install.packver import package_version

    wall = (server or "").strip()
    client = package_version()
    if wall and wall != client:
        print(f"warning: mill client {client} != wall {wall}", file=sys.stderr, flush=True)


def invite_on_url(url: str) -> str:
    """Invite query on a join URL. Empty when the URL has none."""
    from urllib.parse import parse_qs, urlparse

    text = (url or "").strip()
    if not text:
        return ""
    if "://" not in text:
        text = "https://" + text
    return ((parse_qs(urlparse(text).query).get("invite") or [""])[0] or "").strip()


def seat_on_url(url: str) -> str:
    """Seat query on a join URL. Empty when the URL has none."""
    from urllib.parse import parse_qs, urlparse

    text = (url or "").strip()
    if not text:
        return ""
    if "://" not in text:
        text = "https://" + text
    return ((parse_qs(urlparse(text).query).get("seat") or [""])[0] or "").strip()


def desk_on_url(url: str) -> str:
    """desk= on a seat welcome URL. Empty when the URL has none."""
    from urllib.parse import parse_qs, urlparse

    text = (url or "").strip()
    if not text:
        return ""
    if "://" not in text:
        text = "https://" + text
    return ((parse_qs(urlparse(text).query).get("desk") or [""])[0] or "").strip()


def parse_mill_ca_pem(raw: str) -> str | None:
    """Normalize a CA PEM (or base64 of one). None when the body is not a certificate."""
    import base64

    text = (raw or "").strip()
    if not text:
        return None
    if "BEGIN CERTIFICATE" not in text:
        try:
            text = base64.b64decode(text, validate=True).decode("utf-8").strip()
        except Exception:
            return None
    if "BEGIN CERTIFICATE" not in text or "END CERTIFICATE" not in text:
        return None
    if not text.endswith("\n"):
        text += "\n"
    return text


def pem_on_url(url: str) -> str:
    """CA PEM from pem= (base64 of the PEM). Empty when absent or not a certificate."""
    from urllib.parse import parse_qs, urlparse

    text = (url or "").strip()
    if not text:
        return ""
    if "://" not in text:
        text = "https://" + text
    raw = ((parse_qs(urlparse(text).query).get("pem") or [""])[0] or "").strip()
    if not raw:
        return ""
    return parse_mill_ca_pem(raw) or ""


def ca_fingerprint(pem: str) -> str:
    """SHA-256 hex of the certificate DER (empty when PEM cannot be decoded)."""
    import base64
    import hashlib
    import re

    text = parse_mill_ca_pem(pem) or (pem or "")
    m = re.search(
        r"-----BEGIN CERTIFICATE-----(.*?)-----END CERTIFICATE-----",
        text,
        re.DOTALL,
    )
    if not m:
        return ""
    try:
        der = base64.b64decode("".join(m.group(1).split()), validate=True)
    except Exception:
        return ""
    return hashlib.sha256(der).hexdigest()


def ca_fp_on_url(url: str) -> str:
    """Optional ca= fingerprint pin on an invite/join URL."""
    from urllib.parse import parse_qs, urlparse

    text = (url or "").strip()
    if not text:
        return ""
    if "://" not in text:
        text = "https://" + text
    return ((parse_qs(urlparse(text).query).get("ca") or [""])[0] or "").strip().lower()


def fetch_mill_ca(
    url: str,
    dest: Path | None = None,
    invite: str = "",
    *,
    expect_fp: str = "",
) -> Path | None:
    """GET mill CA. Validates PEM like materialize_mill_ca; writes nothing on bad body/fp mismatch."""
    from urllib.parse import urlparse

    base = (url or "").strip()
    if not base:
        return None
    if "://" not in base:
        base = "https://" + base
    parsed = urlparse(base)
    token = (invite or "").strip() or invite_on_url(base)
    if not token:
        token = seat_on_url(base)
    pin = (expect_fp or "").strip().lower() or ca_fp_on_url(base)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    target = dest or mill_ca_file()
    headers = {"X-Mill-Invite": token} if token else {}
    # nginx proxies /api -> mill-wall. /ca.crt is mill-wall or www (often 404 if missing).
    for path in ("/api/ca.crt", "/ca.crt"):
        ca_url = f"{parsed.scheme}://{parsed.netloc}{path}"
        req = urllib.request.Request(ca_url, headers=headers)
        try:
            with _open(req, context=ctx, timeout=15) as resp:
                body = resp.read()
                hdrs = getattr(resp, "headers", None)
                warn_wall_version(hdrs.get("X-Mill-Version") if hdrs else "")
        except (urllib.error.URLError, OSError):
            continue
        try:
            raw = body.decode("utf-8")
        except UnicodeDecodeError:
            return None
        pem = parse_mill_ca_pem(raw)
        if pem is None:
            return None
        if pin:
            got = ca_fingerprint(pem)
            if not got or got.lower() != pin:
                return None
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(pem, encoding="utf-8")
        return target
    return None


def materialize_mill_ca(raw: str, dest: Path | None = None) -> Path | None:
    """Write a mint CA PEM to dest. Does not GET /ca.crt."""
    text = parse_mill_ca_pem(raw)
    if text is None:
        return None
    target = dest or mill_ca_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target


def _unwrap_cli_raw(row: Any) -> Any:
    """Old mill_ws_call unwrap: lean result; attach sync only when non-empty."""
    if not (isinstance(row, dict) and row.get("ok") is True and "result" in row):
        return row
    result = row.get("result")
    sync = row.get("sync") if isinstance(row.get("sync"), list) else list(row.get("sync") or [])
    if sync and isinstance(result, dict):
        out = dict(result)
        out["sync"] = sync
        return out
    if sync:
        return {"result": result, "sync": sync}
    return result


def inbox_room_pointers(result: Any) -> list[dict[str, Any]]:
    """One catch-up pointer per room (TREE) seen in an inbox page (#79, #153).

    catch_up names the newest letter on this page. mail-thread of that id
    reads the branch. Whole-room catch-up stays mail-thread with --room.
    Read only: no mark-read change, no extra host call.
    """
    if not isinstance(result, list):
        return []
    seen: dict[int, dict[str, Any]] = {}
    for letter in result:
        if not isinstance(letter, dict):
            continue
        tree = str(letter.get("tree") or "").strip()
        try:
            root = int(letter.get("root_id") or 0)
        except (TypeError, ValueError):
            root = 0
        if not tree or root <= 0:
            continue
        try:
            mid = int(letter.get("id") or 0)
        except (TypeError, ValueError):
            mid = 0
        hit = seen.get(root)
        if hit is None:
            seen[root] = {
                "tree": tree,
                "root_id": root,
                "letters": 1,
                "_latest": mid,
            }
        else:
            hit["letters"] += 1
            if mid > int(hit.get("_latest") or 0):
                hit["_latest"] = mid
    out: list[dict[str, Any]] = []
    for key in sorted(seen):
        row = seen[key]
        latest = int(row.pop("_latest") or 0) or int(row["root_id"])
        row["catch_up"] = f"mill mail-thread {latest}"
        out.append(row)
    return out


def _room_desk(desk: str) -> str:
    """Bare desk name safe as a stash filename. Empty means do not touch disk."""
    who = str(desk or "").strip()
    if not who or len(who) > 64:
        return ""
    ok = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-"
    if any(ch not in ok for ch in who):
        return ""
    return who


def inbox_rooms_file(desk: str) -> Path | None:
    """Per-desk room stash. None when desk is empty so tests do not write ~/.mill (#147)."""
    who = _room_desk(desk)
    if not who:
        return None
    return mill_home() / "inbox-rooms" / f"{who}.json"


def load_inbox_rooms(desk: str) -> list[dict[str, Any]]:
    path = inbox_rooms_file(desk)
    if path is None or not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    return [row for row in raw if isinstance(row, dict)]


def save_inbox_rooms(desk: str, rooms: list[dict[str, Any]]) -> None:
    path = inbox_rooms_file(desk)
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rooms, separators=(",", ":")), encoding="utf-8")


def merge_inbox_rooms(
    prior: list[dict[str, Any]], page: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Rooms on this page replace their row. Rooms absent from this page stay (#147)."""
    by_root: dict[int, dict[str, Any]] = {}
    for row in list(prior) + list(page):
        if not isinstance(row, dict):
            continue
        try:
            root = int(row.get("root_id") or 0)
        except (TypeError, ValueError):
            continue
        if root <= 0:
            continue
        try:
            letters = int(row.get("letters") or 0)
        except (TypeError, ValueError):
            letters = 0
        tree = str(row.get("tree") or "")
        catch = str(row.get("catch_up") or "").strip()
        if not catch:
            try:
                point = int(row.get("latest_id") or 0)
            except (TypeError, ValueError):
                point = 0
            catch = f"mill mail-thread {point or root}"
        by_root[root] = {
            "tree": tree,
            "root_id": root,
            "letters": letters,
            "catch_up": catch,
        }
    return [by_root[k] for k in sorted(by_root)]


def _refused_hold(args: Any, row: dict[str, Any]) -> bool:
    """A hold that did not take exits 1. The JSON stays on stdout, like drop (#193).

    A peek is a read. Free or held, it exits 0 (#223).
    """
    from agent_coord.client.outbound import canonical_command

    if canonical_command(str(getattr(args, "cmd", "") or "")) != "hold":
        return False
    if bool(getattr(args, "peek", False)):
        return False
    res = row.get("result") if "result" in row else row
    if isinstance(res, dict) and res.get("peek") is True:
        return False
    return isinstance(res, dict) and res.get("held") is False


def _hold_refusal(row: dict[str, Any]) -> dict[str, Any]:
    res = row.get("result") if isinstance(row.get("result"), dict) else row
    owner = str((res or {}).get("owner") or "someone")
    out = dict(row)
    result = dict(res or {})
    result["held"] = False
    result["reason"] = f"held by {owner}, not you"
    out["result"] = result
    return out


def _refused_drop(args: Any, row: dict[str, Any]) -> bool:
    """A drop that released nothing exits 1. Top-level ok is false (#227)."""
    from agent_coord.client.outbound import canonical_command

    if canonical_command(str(getattr(args, "cmd", "") or "")) != "drop":
        return False
    res = row.get("result") if "result" in row else row
    return isinstance(res, dict) and res.get("released") is False


def _todo_rosters(args: Any, body: dict) -> list[str] | None:
    """Rosters a plain `mill todo` reads: yours, or every live roster with --all. None = no change."""
    if str(getattr(args, "cmd", "") or "") != "todo":
        return None
    if str(getattr(args, "project", "") or "").strip() or str(getattr(args, "need", "") or "").strip():
        return None
    owner = body.get("owner")
    try:
        if bool(getattr(args, "all", False)):
            got = mill_http_call({"verb": "project", "cmd": "project", "project": "Office", "for": "connect", "owner": owner})
            res = got.get("result") if isinstance(got, dict) else None
            names = list((res or {}).get("projects") or []) if isinstance(res, dict) else []
        else:
            got = mill_http_call({"verb": "member", "cmd": "member", "owner": owner})
            res = got.get("result") if isinstance(got, dict) else None
            names = [str(r.get("slot") or "") for r in (res or []) if isinstance(r, dict) and r.get("slot")]
    except CoordError:
        return None
    seen: list[str] = []
    for n in names:
        if n and n not in seen:
            seen.append(n)
    return seen or None


TODO_ROSTERS_PER_READ = 200  # matches the wall's TODO_ROSTERS_MAX


def _todo_call(args: Any, body: dict) -> Any:
    """Plain `mill todo`: your rosters in one read (--all = every roster).

    The wall answers {"cards": [...]} (0.7.4+). More than TODO_ROSTERS_PER_READ
    rosters are read in chunks of that size. A refused read is returned as is;
    any other answer shape is an error (alpha: no per-roster fallback).
    """
    rosters = _todo_rosters(args, body)
    if rosters is None:
        return mill_http_call(body)
    rows: list = []
    last: Any = {"ok": True}
    for at in range(0, len(rosters), TODO_ROSTERS_PER_READ):
        part = list(rosters[at : at + TODO_ROSTERS_PER_READ])
        last = mill_http_call({**body, "project": part[0], "rosters": part})
        if not isinstance(last, dict) or last.get("ok") is not True:
            return last
        res = last.get("result")
        if not isinstance(res, dict) or not isinstance(res.get("cards"), list):
            raise CoordError("todo: the wall did not answer {cards} for a roster read; update the wall to 0.7.4 or later")
        rows.extend(res["cards"])
    out = dict(last) if isinstance(last, dict) else {"ok": True}
    out["ok"] = True
    out["result"] = rows
    if bool(getattr(args, "all", False)):
        out["note"] = "every roster (%d)" % len(rosters)
    else:
        out["note"] = "your rosters only (%s); mill todo --all lists every roster" % ", ".join(rosters)
    return out


def todo_find_text(args: Any) -> str:
    """todo --find TEXT, checked up front: 1..64 chars, not blank (#274)."""
    raw = getattr(args, "find", "")
    if raw is None or str(getattr(args, "cmd", "") or "") != "todo":
        return ""
    text = str(raw)
    if text == "":
        return ""
    text = text.strip()
    if not text or len(text) > 64:
        raise CoordError("todo --find: TEXT is 1..64 characters")
    return text


FIND_SNIPPET = 120
# Lower rank lists first: a need-name hit, then the roster, then the body (#818: cards have no title).
_FIND_RANK = (("need_id", 0, "need"), ("project_id", 1, "roster"), ("detail", 2, "detail"))


def _find_snippet(text: str, needle: str) -> str:
    """A short one-line piece of text around the first hit (or its head)."""
    flat = " ".join(str(text or "").split())
    if not flat:
        return ""
    at = flat.lower().find(needle)
    if at < 0 or len(flat) <= FIND_SNIPPET:
        lo = 0
    else:
        lo = max(0, min(at - FIND_SNIPPET // 3, len(flat) - FIND_SNIPPET))
    piece = flat[lo : lo + FIND_SNIPPET]
    return ("..." if lo else "") + piece + ("..." if lo + FIND_SNIPPET < len(flat) else "")


def _find_card(r: dict, needle: str, match: str) -> dict:
    """The card as --find prints it: the body becomes a short snippet (ux12)."""
    out = {k: v for k, v in r.items() if k not in ("detail", "progress")}
    out["match"] = match
    out["snippet"] = _find_snippet(str(r.get("detail") or ""), needle)
    return out


def _todo_find(row: Any, text: str) -> Any:
    """Keep the cards whose need, roster or detail holds text (any case).

    Need-name hits list first, then roster, then body-only hits; each
    card carries a short snippet instead of its whole body (ux12).
    """
    if not text or not isinstance(row, dict) or not isinstance(row.get("result"), list):
        return row
    needle = text.lower()
    ranked: list[tuple[int, int, dict]] = []
    for i, r in enumerate(row["result"]):
        if not isinstance(r, dict):
            continue
        for key, rank, match in _FIND_RANK:
            if needle in str(r.get(key) or "").lower():
                ranked.append((rank, i, _find_card(r, needle, match)))
                break
    ranked.sort(key=lambda t: (t[0], t[1]))
    keep = [c for _, _, c in ranked]
    out = dict(row)
    out["result"] = keep
    out["note"] = f"{len(keep)} card(s) match {text!r}" + (
        "" if keep else "; add --all for every roster, --done for finished cards"
    )
    return out


def _said_command(row: Any, said: str) -> Any:
    """watch/unwatch ride add/remove; the reply and refusal name the typed command (ux12)."""
    if said not in ("watch", "unwatch") or not isinstance(row, dict):
        return row
    rpc = "add" if said == "watch" else "remove"
    out = dict(row)
    res = out.get("result")
    if isinstance(res, dict) and res.get("verb") == rpc:
        out["result"] = {**res, "verb": said}
    elif out.get("verb") == rpc:
        out["verb"] = said
    err = out.get("error")
    if isinstance(err, str) and err.startswith(rpc + ":"):
        out["error"] = said + err[len(rpc):]
    return out


def mill_http_from_args(args: Any) -> int:
    from agent_coord.client.outbound import body_from_args

    find = todo_find_text(args)
    from agent_coord.client import todo_rows

    # #295: the board lists short rows, paged; --full keeps today's reply.
    short_rows = todo_rows.applies(args, find)
    page_block: dict | None = None
    from agent_coord.client import mail_rows

    # #295 follow-ups: inbox, mail-thread --room and the note reply.
    inbox_short = mail_rows.inbox_applies(args)
    room_short = mail_rows.room_applies(args)
    note_short = mail_rows.note_applies(args)
    mail_block: dict | None = None
    # Lock: never let argv --owner rewrite session active / Bearer.
    body = body_from_args(args)
    mine = todo_rows.mine_applies(args)
    row = _todo_call(args, body)
    if mine and isinstance(row, dict) and row.get("ok") is True:
        # #373: only the sitting desk's cards, before --find and paging cut the list.
        from agent_coord.client import focus as _focus

        desk = todo_rows.sitting_desk(body)
        rank: list = []
        if _focus.wears(row.get("result") or [], desk):
            # #374: one label read for the rank, only when a listed card wears the desk's label.
            rank = _focus.label_rank(lambda b: mill_http_call(dict(b, owner=desk)), desk)
        row = todo_rows.keep_mine(row, desk, rank, str(getattr(args, "status", "") or "").strip())
    if find:
        row = _todo_find(row, find)
    if short_rows and isinstance(row, dict) and row.get("ok") is True and isinstance(row.get("result"), list):
        part, page_block = todo_rows.cut(row["result"], int(getattr(args, "page", 0) or 0))
        row = dict(row, result=part)
    row = _said_command(row, str(getattr(args, "said_command", "") or ""))
    if bool(getattr(args, "raw", False)):
        row = _unwrap_cli_raw(row)
    elif (
        str(getattr(args, "cmd", "") or "") == "inbox"
        and isinstance(row, dict)
        and row.get("ok") is True
    ):
        page = inbox_room_pointers(row.get("result"))
        desk = str((body or {}).get("owner") or "").strip()
        # Empty desk: page only, no disk. A named desk keeps rooms after unread is gone (#147).
        if inbox_rooms_file(desk) is None:
            rooms = page
        else:
            rooms = merge_inbox_rooms(load_inbox_rooms(desk), page)
            save_inbox_rooms(desk, rooms)
        if rooms:
            row = dict(row)
            row["rooms"] = rooms
        if inbox_short and isinstance(row.get("result"), list):
            # Room pointers above cover every fetched letter; the page is cut after.
            part, mail_block = mail_rows.cut(row["result"], int(getattr(args, "page", 0) or 0))
            row = dict(row, result=part)
    if (
        room_short
        and isinstance(row, dict)
        and row.get("ok") is True
        and isinstance(row.get("result"), dict)
        and isinstance(row["result"].get("chain"), list)
    ):
        part, mail_block = mail_rows.cut_newest(row["result"]["chain"], int(getattr(args, "page", 0) or 0))
        row = dict(row, result=mail_rows.short_room(dict(row["result"], chain=part)))
        row["page"] = mail_block
        mail_block = None
    if note_short and isinstance(row, dict) and row.get("ok") is True:
        row = dict(row, result=mail_rows.short_note(row.get("result")))
    if (
        str(getattr(args, "cmd", "") or "") == "trail"
        and not bool(getattr(args, "as_json", False))
        and not bool(getattr(args, "raw", False))
        and isinstance(row, dict)
        and row.get("ok") is True
        and isinstance(row.get("result"), dict)
    ):
        from agent_coord.helpers.trail_text import render

        print(render(row["result"]), flush=True)
        return 0
    cmd_now = str(getattr(args, "cmd", "") or "")
    if (
        cmd_now in ("todo", "inbox", "hold")
        and not bool(getattr(args, "raw", False))
        and isinstance(row, dict)
        and row.get("ok") is True
        and "result" in row
        and not (cmd_now == "hold" and str(getattr(args, "resource", "") or ""))
        and not (cmd_now == "todo" and str(getattr(args, "need", "") or ""))
        # --find keeps its ranked flat list unless a --group-by was asked (ux12).
        and not (find and not str(getattr(args, "group_by", "") or ""))
        # --mine keeps focus rank order unless a --group-by was asked (#374).
        and not (mine and not str(getattr(args, "group_by", "") or ""))
    ):
        from agent_coord.client.grouping import apply as _group

        res, note = _group(cmd_now, row["result"], str(getattr(args, "group_by", "") or ""))
        row = dict(row)
        row["result"] = res
        if note:
            row["note"] = note
    if page_block is not None:
        row = dict(row, result=todo_rows.short(row["result"], str(page_block.get("roster") or "")))
        row["page"] = page_block
    if mail_block is not None:
        row = dict(row, result=mail_rows.short_inbox(row["result"]))
        row["page"] = mail_block
    refused_hold = isinstance(row, dict) and _refused_hold(args, row)
    if refused_hold:
        row = _hold_refusal(row)
        # Envelope ok matches result.ok. The holder name stays on stdout (#207, #193).
        row["ok"] = False
    refused_drop = isinstance(row, dict) and _refused_drop(args, row)
    if refused_drop:
        row = dict(row)
        row["ok"] = False
    if isinstance(row, dict):
        public = {k: v for k, v in row.items() if k != "token"}
        if "bytes" in public:
            # #329: --find, grouping and room pointers reshape the reply here, so
            # bytes is the size of the line printed. When the wall sent more
            # (--find filters on the desk), wire_bytes keeps what the read cost.
            from agent_coord.server.mill_json import with_bytes

            wire = public.pop("bytes")
            printed, n = with_bytes(public)
            if isinstance(wire, int) and wire != n:
                printed, n = with_bytes(dict(public, wire_bytes=wire))
            public = printed
        # Error JSON goes to stderr. A refused hold or drop stays on stdout
        # with ok false and exit 1 (#193, #227).
        failed = (
            (row.get("ok") is False or bool(row.get("error")))
            and not refused_hold
            and not refused_drop
        )
        print(json.dumps(public, default=str), file=sys.stderr if failed else sys.stdout, flush=True)
        if failed or refused_hold or _refused_drop(args, row):
            return 1
        return 0
    print(json.dumps(row, default=str), flush=True)
    return 0


def seat_then_focus(who: str, project: str, stop: Any, outcome: dict) -> None:
    """Project check, then, still seated, the desk's focus line (#374).

    The focus line is one JSON row after the ready and sync lines, only when
    the desk has a focus card it can work on. A failed focus read prints one
    stderr line naming the cause (#536); focus never fails or stops a connect.
    """
    check_project_on_socket(who, project, stop, outcome)
    if stop.is_set() or outcome.get("exit"):
        return
    from agent_coord.client import ws as _ws
    from agent_coord.client.focus import connect_block

    def call(body: dict) -> Any:
        return _ws.own_bridge_call(who, body, timeout_s=20.0)

    try:
        block = connect_block(call, who)
    except Exception as e:
        # #536: never fail or stop the connect, but say why the focus line is missing.
        if not stop.is_set():
            why = " ".join(str(e).split()) or type(e).__name__
            print("connect: focus not shown: " + why[:300], file=sys.stderr, flush=True)
        return
    if block and not stop.is_set():
        print(json.dumps(block, default=str), flush=True)


def check_project_on_socket(who: str, project: str, stop: Any, outcome: dict) -> None:
    """Ask the server, over this connect's own /ws, whether project is live (#237).

    Refused: print the reason, set exit 1, stop the socket. The held sync line
    is dropped, so a refused connect never reports a sync.
    An older server without the check: say so and keep sitting.
    """
    import time as _time

    from agent_coord.client.ws import drop_sync_lines, own_bridge_call, release_sync_lines

    body = {"verb": "project", "project": project, "for": "connect"}
    reply: dict | None = None
    while not stop.is_set():
        try:
            reply = own_bridge_call(who, body)
            break
        except CoordError as e:
            if str(e) == "socket not ready":
                _time.sleep(0.1)
                continue
            reason = str(e)
        except OSError as e:
            reason = "socket error: %s" % (e,)
        print("connect: could not check project %s: %s" % (project or "(empty)", reason), file=sys.stderr, flush=True)
        drop_sync_lines()
        outcome["exit"] = 1
        stop.set()
        return
    if reply is None:
        drop_sync_lines()
        return
    if reply.get("ok") is True:
        release_sync_lines()
        return
    err = str(reply.get("error") or "project check failed")
    if err.startswith("unknown mill command"):
        print(
            "connect: this office does not check projects yet; project %s not checked" % (project or "(empty)"),
            file=sys.stderr,
            flush=True,
        )
        release_sync_lines()
        return
    if not err.startswith("connect:"):
        err = "connect: could not check project %s: %s" % (project or "(empty)", err)
    print(err, file=sys.stderr, flush=True)
    drop_sync_lines()
    outcome["exit"] = 1
    stop.set()


def mill_here_over_http(args: Any) -> int:
    """Sit on /ws until Ctrl+C. Does not POST join.

    mill join writes the seat, token hash, memberships, and lan_ip.
    This process only presents that token on the socket. Hub PING is keep-alive.
    """
    try:
        from agent_coord.client import ws as _ws

        _ws.READY_ROSTER["roster"] = str(getattr(args, "project", "") or "")
    except Exception:
        pass

    from agent_coord.client.tokens import read_session_token
    from agent_coord.helpers.ident import desk_name

    # Positional desk only. Do not publish or read host active as the sender.
    desk = str(
        getattr(args, "desk", "")
        or getattr(args, "owner", "")
        or getattr(args, "owner_pos", "")
        or ""
    ).strip()
    who = desk_name(desk)
    if not who:
        print(
            json.dumps(
                {"ok": False, "error": "mill connect: desk required", "desk": ""},
                default=str,
            ),
            flush=True,
        )
        return 1
    tok = read_session_token(who).strip()
    if not tok:
        from agent_coord.client.offices import current_office

        err = (
            "no seat token for this desk here; mill join --link-file PATH first"
            if current_office()
            else "no session token; mill join first"
        )
        print(
            json.dumps(
                {"ok": False, "error": err, "desk": who},
                default=str,
            ),
            flush=True,
        )
        return 1
    print(json.dumps({"desk": who, "mode": "ws"}, default=str), flush=True)
    import threading

    from agent_coord.client.ws import start_ws_thread

    vendor = str(getattr(args, "vendor", "") or os.environ.get("AGENT_COORD_VENDOR") or "").strip()
    if vendor:
        os.environ["AGENT_COORD_VENDOR"] = vendor
        print(json.dumps({"vendor": vendor, "desk": who}, default=str), flush=True)
    sid = str(getattr(args, "session", "") or os.environ.get("AGENT_COORD_GROK_SESSION") or "").strip()
    if sid:
        os.environ["AGENT_COORD_GROK_SESSION"] = sid
        try:
            from agent_coord.client.connectors.grok_build import bind_session

            bind_session(who, sid)
            print(json.dumps({"grok_session": sid, "desk": who}, default=str), flush=True)
        except Exception:
            pass
    from agent_coord.client.ws import _shell_ppid
    from agent_coord.lib.proc import parent_gone

    parent = _shell_ppid()
    refuse = bool(getattr(args, "refuse", False))
    if bool(getattr(args, "foreground", False)):
        # Foreground: this process waits for ONE work HINT, prints it, exits.
        # No HintBuf drain / mill route spawn. Break-out = KeyboardInterrupt.
        from agent_coord.client.ws import wait_one_hint

        try:
            # An empty queue keeps the socket until the next hint, as the docs
            # say; a non-empty queue prints and exits (card #278).
            got = wait_one_hint(
                who, tok, skip_ping=True, timeout_s=None, parent_pid=parent, hold_empty_sync=True,
                refuse=refuse,
            )
        except KeyboardInterrupt:
            print(
                json.dumps(
                    {"ok": False, "mode": "foreground", "error": "interrupted", "desk": who},
                    default=str,
                ),
                flush=True,
            )
            return 130
        print(json.dumps(got, default=str), flush=True)
        if got.get("ok"):
            return 0
        return int(got["exit"]) if "exit" in got else 1  # busy exits 0 (card 834)
    stop = threading.Event()
    outcome: dict = {}
    from agent_coord.client.ws import clear_connect_starting, write_connect_starting

    write_connect_starting(who, pid=os.getpid(), parent_pid=parent)
    # Unknown, retired, or empty project: the server refuses on this socket and
    # connect exits 1 before any sync line (#237).
    from agent_coord.client.ws import hold_sync_lines

    project = str(getattr(args, "project", "") or "").strip()
    hold_sync_lines()
    start_ws_thread(who, tok, stop, outcome, refuse=refuse)
    threading.Thread(
        target=seat_then_focus,
        args=(who, project, stop, outcome),
        name="mill-connect-project-%s" % who,
        daemon=True,
    ).start()
    try:
        try:
            while not stop.is_set():
                # Start-Process leaves this process up after the script exits (#192).
                if parent_gone(parent):
                    stop.set()
                    from agent_coord.client.session_errors import parent_exited_notice

                    print(json.dumps(parent_exited_notice(who), default=str), flush=True)
                    return 0
                stop.wait(1.0)
        except KeyboardInterrupt:
            stop.set()
            return 0
        return int(outcome.get("exit") or 0)
    finally:
        clear_connect_starting(who, pid=os.getpid())
