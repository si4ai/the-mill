"""Optional mill wake-hook URL + fire-and-forget POST, and desk webhook wake (#618).

A desk picks webhook delivery at mill join: the URL and the desk's own key live
on its join row. The key is read only at POST time (mill_join_wake_target) and is
never returned by a read, a log line or an error. The URL is https only, on a
host in this wall's wake_hosts allowlist, never an IP literal, and every address
it resolves to must be public. Redirects are never followed.

A POST is a doorbell, and it takes a wake lease for that desk (F144): one
woken run at a time. A connect sync does not end the lease (a routine run
connects once per shell call); the run ends it with `mill wake-done [--note TEXT]`,
or it lapses after lease_s() seconds (wake_lease_s, default 900) when the run
crashed or its client predates done. While it is held, new items post nothing.
Every hint and letter stays in the desk's push queue as missed either way, so
a woken desk's mill connect sync hands over all of them and its redirector
chain walks each one there (the same walk as a /ws hint). Items held back by
the lease ring exactly once more when it ends (#669, the trailing POST) with
pending_count and the run's note, unless the run already read them all, so a
burst is never left asleep and never starts overlapping runs. The queue-until-
done design follows the grokbot-wake-relay repo.
"""
from __future__ import annotations

import json
import os
import threading
import urllib.request
from typing import Any


def wake_url() -> str:
    """Optional mill wake hook URL. Empty = no POST (fail soft)."""
    try:
        from agent_coord.config import settings

        return str(settings().get("wake_url") or "").strip()
    except Exception:
        return (os.environ.get("AGENT_COORD_WAKE_URL") or "").strip()


def _log_hook_fail(desk: str, hint_id: int | None, *, status: int | None = None, exc_type: str = "", why: str = "") -> None:
    """One failure line. Desk and hint id when the caller has them. Never the endpoint URL."""
    parts = ["webhook fail"]
    if desk:
        parts.append(f"desk={desk}")
    if hint_id is not None:
        parts.append(f"id={hint_id}")
    if status is not None:
        parts.append(f"status={int(status)}")
        if why:
            parts.append(f'why="{why}"')
    else:
        parts.append(f"err={exc_type or 'Exception'}")
    line = " ".join(parts)
    try:
        from agent_coord.server.push import _bc_log

        _bc_log(line)
    except Exception:
        return


_WHY_KEYS = ("error", "message", "detail", "reason")
WHY_MAX = 120


def _why(raw: bytes, *, url: str = "", key: str | None = None) -> str:
    """#838: the receiver's short reason for a non-2xx answer, safe for a log line or
    a letter: the error/message/detail/reason field of a JSON body, else the text;
    one line, at most WHY_MAX chars, no URL, no key, no quotes."""
    import re

    try:
        text = (raw or b"").decode("utf-8", "replace")
    except Exception:
        return ""
    try:
        got = json.loads(text)
        while isinstance(got, dict):
            nxt = next((got[k] for k in _WHY_KEYS if got.get(k) not in (None, "")), None)
            if nxt is None:
                break
            got = nxt
        if isinstance(got, (str, int, float)):
            text = str(got)
    except ValueError:
        pass
    secret = (key or "").strip()
    if secret:
        text = text.replace(secret, "<key>")
    if url:
        text = text.replace(url, "<url>")
        # A receiver may echo only the path (with its query): drop that too.
        from urllib.parse import urlsplit

        path = urlsplit(url).path
        if len(path) > 1:
            text = re.sub(re.escape(path) + r"\S*", "<path>", text)
    text = re.sub(r"https?://\S+", "<url>", text)
    try:
        from agent_coord.server.redact import redact_secrets

        text = redact_secrets(text)
    except Exception:
        pass
    text = " ".join(text.replace('"', "'").split())
    return text[:WHY_MAX]


def _open(req, timeout: float):
    """One request through the shared opener that refuses redirects (a 3xx is a failure, #654)."""
    from agent_coord.helpers.nofollow import open_no_redirect

    return open_no_redirect(req, timeout=timeout)


def _post_status(
    url: str,
    payload: dict[str, Any],
    *,
    timeout: float,
    key: str | None,
    desk: str,
    hint_id: int | None,
    quiet: bool = False,
) -> tuple[int | None, str]:
    """One HTTP POST. Never raises. (status, "") or (None, error type).
    quiet: the caller logs the outcome itself (a desk wake logs one line, #625)."""
    u = (url or "").strip()
    if not u:
        return None, "NoURL"
    try:
        import urllib.error
        import urllib.request

        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        secret = (key or "").strip()
        if secret:
            headers["Authorization"] = "Bearer " + secret
            headers["X-Automation-Key"] = secret
        req = urllib.request.Request(
            u,
            data=raw,
            headers=headers,
            method="POST",
        )
        # urllib capitalizes custom header names. Keep the contract spelling.
        mangled = "X-automation-key"
        if secret and mangled in req.headers:
            req.headers["X-Automation-Key"] = req.headers.pop(mangled)
        with _open(req, timeout) as resp:
            got = resp.read(256)
            status = getattr(resp, "status", None)
            if status is None:
                status = getattr(resp, "code", None)
            status = 200 if status is None else int(status)
            if 200 <= status <= 299:
                return status, ""
            why = _why(got if isinstance(got, bytes) else b"", url=u, key=secret)
            if not quiet:
                _log_hook_fail(desk, hint_id, status=status, why=why)
            return status, why
    except urllib.error.HTTPError as e:
        # #838: keep the receiver's reason (it was dropped, so 168 x 400 said nothing).
        try:
            why = _why(e.read(512) or b"", url=u, key=(key or "").strip())
        except Exception:
            why = ""
        if not quiet:
            _log_hook_fail(desk, hint_id, status=int(e.code), why=why)
        return int(e.code), why
    except Exception as e:
        if not quiet:
            _log_hook_fail(desk, hint_id, exc_type=type(e).__name__)
        return None, type(e).__name__


def _fire(
    url: str,
    payload: dict[str, Any],
    *,
    timeout: float,
    key: str | None,
    desk: str,
    hint_id: int | None,
    quiet: bool = False,
) -> tuple[int | None, str]:
    """POST once; a body that carries idem retries a failure once. The last (status, error)."""
    from agent_coord.server.poke_key import FIELD

    status, err = _post_status(url, payload, timeout=timeout, key=key, desk=desk, hint_id=hint_id, quiet=quiet)
    if status is not None and 200 <= status <= 299:
        return status, err
    if not str((payload or {}).get(FIELD) or "").strip() or not (url or "").strip():
        return status, err
    return _post_status(url, payload, timeout=timeout, key=key, desk=desk, hint_id=hint_id, quiet=quiet)


def fire_wake_hook(
    url: str,
    payload: dict[str, Any],
    *,
    timeout: float = 2.0,
    key: str | None = None,
    desk: str = "",
    hint_id: int | None = None,
) -> bool:
    """HTTP POST JSON. Never raises. True only when the response is 2xx.

    A key adds Authorization Bearer and X-Automation-Key. An empty key adds neither.
    Timeout, connection error, or non-2xx returns False and logs status or error type.
    A body that already carries idem retries that failure once. A body without it
    does not retry.
    """
    status, _err = _fire(url, payload, timeout=timeout, key=key, desk=desk, hint_id=hint_id)
    return status is not None and 200 <= status <= 299


# --- desk webhook wake (#618) ------------------------------------------------

WAKE_HOSTS_DEFAULT = "api2.cursor.sh/automations/webhook/"
# F144: the default wake lease. One POST per desk until its run says done or
# this many seconds pass (wake_lease_s or AGENT_COORD_WAKE_LEASE_S overrides).
WAKE_WINDOW_S = 900.0
NOTE_MAX = 500
WAKE_TIMEOUT_S = 8.0
KEY_MAX = 512
URL_MAX = 512


class WakeRefused(ValueError):
    """A wake input refused before anything is stored. The text never holds the key."""


def lease_s() -> float:
    """F144: seconds a wake lease lasts without a done. wake_lease_s in the wall
    config, else AGENT_COORD_WAKE_LEASE_S, else WAKE_WINDOW_S. A bad value is the default."""
    raw: Any = None
    try:
        from agent_coord.config import settings

        raw = settings().get("wake_lease_s")
    except Exception:
        raw = None
    if raw in (None, ""):
        raw = os.environ.get("AGENT_COORD_WAKE_LEASE_S") or ""
    try:
        got = float(raw)
    except (TypeError, ValueError):
        return WAKE_WINDOW_S
    return got if got > 0 else WAKE_WINDOW_S


def wake_hosts() -> list[tuple[str, str]]:
    """(host, path prefix) pairs from the wall's wake_hosts setting (comma list)."""
    try:
        from agent_coord.config import settings

        raw = str(settings().get("wake_hosts") or "")
    except Exception:
        raw = os.environ.get("AGENT_COORD_WAKE_HOSTS") or ""
    raw = raw.strip() or WAKE_HOSTS_DEFAULT
    out: list[tuple[str, str]] = []
    for part in raw.split(","):
        item = part.strip().lower()
        if not item:
            continue
        if "://" in item:
            item = item.split("://", 1)[1]
        host, _, path = item.partition("/")
        if host:
            out.append((host, "/" + path))
    return out


def _allow_text(allow: list[tuple[str, str]]) -> str:
    return ", ".join(h + p for h, p in allow) or "none"


def allow_step(host: str, allow: list[tuple[str, str]]) -> str:
    """The exact host-Admin step that adds HOST/<prefix>/ to wake_hosts (#619).

    Names where this wall reads the setting: the env var when it is set (it wins
    over the file, and the service reads it at start), else the config file
    (read on every join, no restart). Never a real path, never the URL path.
    """
    listed = ",".join(h + p for h, p in allow)
    value = (listed + "," if listed else "") + f"{host}/<webhook path prefix>/"
    if (os.environ.get("AGENT_COORD_WAKE_HOSTS") or "").strip():
        return (
            f"the host Admin sets AGENT_COORD_WAKE_HOSTS={value} in the mill-wall service "
            "environment on the wall host and must restart mill-wall, then this mill join runs again"
        )
    where = (
        "the file named by AGENT_COORD_CONFIG"
        if (os.environ.get("AGENT_COORD_CONFIG") or "").strip()
        else "~/.mill/config.toml of the account mill-wall runs as"
    )
    return (
        f'the host Admin puts the line wake_hosts = "{value}" in {where} on the wall host '
        "(read on the next join, no restart), then this mill join runs again"
    )


def _ip_literal(host: str) -> bool:
    import ipaddress

    h = host.strip("[]")
    try:
        ipaddress.ip_address(h)
        return True
    except ValueError:
        pass
    # Integer, hex and dotted-octal spellings that resolvers still accept as an address.
    import re

    labels = h.split(".")
    return all(re.fullmatch(r"(?i)0x[0-9a-f]+|[0-9]+", lab or "x") for lab in labels)


def _climbs(path: str) -> bool:
    """True when a URL path could leave its prefix: a . or .. segment, a backslash,
    or an encoded slash or backslash, at any depth of percent-encoding."""
    import re
    from urllib.parse import unquote

    p = path
    for _ in range(5):
        if re.search(r"(?i)%(?:2f|5c)", p) or "\\" in p:
            return True
        if any(seg in (".", "..") for seg in p.split("/")):
            return True
        q = unquote(p)
        if q == p:
            return False
        p = q
    return True  # still encoded after five layers: refuse rather than guess


def looks_like_key(text: str) -> bool:
    t = str(text or "").strip()
    return bool(t) and "/" not in t and (
        t.lower().startswith(("bearer ", "authorization", "crsr_")) or (" " not in t and "." not in t and len(t) >= 16)
    )


def check_url(raw: str, *, allow_only: bool = True) -> tuple[str, str]:
    """(url, host) for a wake URL this wall may POST to, or WakeRefused naming the fix.

    https only, no user or password, default port, host and path prefix on the
    wake_hosts allowlist, never an IP literal. The message never repeats the path.
    """
    from urllib.parse import urlsplit

    url = str(raw or "").strip().strip("'\"").strip()
    if not url:
        raise WakeRefused("join: URL required: --webhook-url URL or --webhook-url-file PATH (the routine's webhook URL)")
    if looks_like_key(url):
        raise WakeRefused(
            "join: that looks like the key, not the URL; the URL starts with https://. "
            "Put the key in --webhook-key-file, --webhook-key-env or --webhook-key-stdin"
        )
    if len(url) > URL_MAX or any(ord(ch) <= 32 or ord(ch) > 126 for ch in url):
        raise WakeRefused(f"join: URL must be one line of plain ASCII up to {URL_MAX} characters")
    parts = urlsplit(url)
    scheme = (parts.scheme or "").lower()
    if scheme != "https":
        raise WakeRefused(
            f"join: https only (got {scheme or 'no scheme'}); copy the https:// webhook URL from the routine"
        )
    if parts.username or parts.password or "@" in parts.netloc:
        raise WakeRefused("join: a URL with a user or password is refused; the key goes in --webhook-key-file")
    host = (parts.hostname or "").lower().rstrip(".")
    try:
        port = parts.port
    except ValueError:
        port = -1
    if not host or _ip_literal(host):
        raise WakeRefused("join: the URL must name a host, not an IP address")
    if port not in (None, 443):
        raise WakeRefused("join: the URL must use the default https port")
    if parts.fragment:
        raise WakeRefused("join: drop the #fragment from the URL")
    if _climbs(parts.path or "/"):
        # Before the prefix check: /allowed/prefix/../../elsewhere must not pass as the prefix.
        raise WakeRefused(
            "join: the URL path has a dot segment (. or ..), or an encoded slash, backslash or dot "
            "that hides one; copy the webhook URL from the routine again"
        )
    if not allow_only:
        # The desk side checks the shape; only the wall knows its allowlist.
        return url, host
    allow = wake_hosts()
    path = parts.path or "/"
    if not any(host == h and path.startswith(p) for h, p in allow):
        step = allow_step(host, allow)
        mine = [p for h, p in allow if h == host]
        if mine:
            raise WakeRefused(
                f"join: that path on {host} is not a webhook path this wall allows "
                f"(allowed on {host}: {', '.join(mine)}); copy the webhook URL from the routine again. "
                f"If it is a new webhook path, {step}"
            )
        raise WakeRefused(
            f"join: host {host} is not on this wall's wake allowlist (allowed: {_allow_text(allow)}). "
            f"To allow it, {step}"
        )
    return url, host


def normalize_key(raw: str) -> str:
    """The bare key from what a person copies: the key, Bearer KEY, or a whole header line.

    WakeRefused for an empty value, a URL, or text that is not one plain token.
    """
    import re

    text = str(raw or "").strip().strip("'\"").strip()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) > 1:
        raise WakeRefused("join: the key is one line; put only the key (or its Authorization line) in the file")
    text = lines[0] if lines else ""
    text = re.sub(r"(?i)^(?:authorization|x-automation-key)\s*:\s*", "", text).strip()
    text = re.sub(r"(?i)^bearer(?:\s+|$)", "", text).strip().strip("'\"").strip()
    if not text:
        raise WakeRefused("join: key required: --webhook-key-file PATH, --webhook-key-env NAME or --webhook-key-stdin (the routine's key)")
    if text.lower().startswith(("http://", "https://")):
        raise WakeRefused("join: that is a URL, not the key; the URL goes in --webhook-url or --webhook-url-file")
    if len(text) > KEY_MAX or len(text) < 8 or not re.fullmatch(r"[!-~]+", text):
        raise WakeRefused("join: the key must be one plain token (8 to 512 visible ASCII characters, no spaces)")
    return text


def _addrs(host: str) -> list[str]:
    import socket

    return sorted({str(info[4][0]) for info in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)})


def public_host(host: str) -> bool:
    """True when the host resolves and every address is public (no private, loopback, link-local)."""
    import ipaddress

    try:
        got = _addrs(host)
    except Exception:
        return False
    if not got:
        return False
    for a in got:
        try:
            ip = ipaddress.ip_address(a.split("%", 1)[0])
        except ValueError:
            return False
        if not ip.is_global:
            return False
    return True


# The frame keys a receiver's walk reads (client.dispatch public_frame), and no others.
FRAME_KEYS = ("kind", "type", "id", "hint", "detail", "idem")


def wake_body(
    desk: str,
    frame: dict[str, Any],
    *,
    pending: int,
    test: bool = False,
    roster: str = "",
    reason: str | None = None,
    room: str | None = None,
    pending_count: int = 0,
    last_note: str | None = None,
    lease: str | None = None,
) -> dict[str, Any]:
    """The POST body: the same frame a sitting desk gets on /ws (with its poke key, idem),
    trimmed to the keys the redirector walk reads, plus one wake block. No letter or card text.

    #627: roster sits next to desk, so a receiver that routes many desks (a room
    barker) knows the target. wake.reason is addressed or room (null on the join
    test); wake.room is the room name, or null off a room.

    F144: pending_count is how many items the last lease held back (0 on a
    fresh wake); last_note is the note the last run left with mill wake-done, or null.
    """
    from agent_coord.server.mill_json import stamp_mill

    body: dict[str, Any] = {k: frame[k] for k in FRAME_KEYS if frame.get(k) not in (None, "")}
    if test:
        # #669: a join test POST has its own id, so a receiver can log and dedupe it.
        # It never takes or counts toward the window (test_fire posts directly).
        import uuid

        body = {"kind": "wake-test", "id": f"wake-test-{uuid.uuid4().hex[:12]}"}
    body["desk"] = desk
    body["roster"] = str(roster or "") or None
    body["wake"] = {
        "reason": None if test else (reason or ADDRESSED),
        "room": None if test else (room or None),
        "pending": int(pending),
        "pending_count": 0 if test else int(pending_count),
        "last_note": None if test else (last_note or None),
        "lease": None if test else (lease or None),
        "window_s": int(lease_s()),
        "next": (
            "nothing to do: this is the join test"
            if test
            else f"mill connect -r {desk}: the sync line hands over every waiting hint and letter, "
            "and this desk's routes walk them. A busy answer means another session has the seat "
            "and gets these letters: stop. Last step of the run: mill wake-done --lease LEASE --note TEXT "
            "(LEASE is wake.lease; one wake at a time; letters that came meanwhile ring once after it)"
        ),
    }
    return stamp_mill(body)


ADDRESSED = "addressed"
ROOM = "room"
# #628: the desk's choice at join. addressed: a room-only item does not POST.
WAKE_ON_ALL = "all"
WAKE_ON = (WAKE_ON_ALL, ADDRESSED)


def desk_roster(cn, desk: str) -> str:
    """The roster a wake names next to the desk (#627): the desk's one roster
    other than Office, else Office. The same rule a send uses for its sender roster."""
    try:
        from agent_coord.server.api.mill.rpc import _seat_roster

        return str(_seat_roster(cn, desk) or "")
    except Exception:
        return ""


def _fix_for(status: int | None, err: str, host: str) -> str:
    if status is None:
        return f"could not reach {host} ({err or 'error'}); check the URL and that the routine exists, then run it again"
    if status in (401, 403):
        return f"{host} refused the key ({status}); copy the key from the routine again and re-run mill join with it"
    if status == 404:
        return f"{host} has no webhook at that URL (404); copy the URL from the routine again"
    if 300 <= status <= 399:
        return f"{host} answered with a redirect ({status}); a wake never follows one; use the routine's final URL"
    return f"{host} answered {status}; try again, or check the routine"


def test_fire(url: str, key: str, desk: str, *, roster: str = "") -> dict[str, Any]:
    """One test POST. {ok, status, host, fix?}. Never the URL path or the key."""
    try:
        url, host = check_url(url)
    except WakeRefused as e:
        return {"ok": False, "status": None, "host": "", "fix": str(e)}
    if not public_host(host):
        return {"ok": False, "status": None, "host": host,
                "fix": f"{host} does not resolve to a public address from this wall"}
    status, err = _post_status(url, wake_body(desk, {}, pending=0, test=True, roster=roster),
                               timeout=WAKE_TIMEOUT_S, key=key, desk=desk, hint_id=None)
    ok = status is not None and 200 <= status <= 299
    out: dict[str, Any] = {"ok": ok, "status": status, "host": host}
    if not ok:
        out["fix"] = _fix_for(status, err, host)
    return out


# F144: desk -> the time its wake lease started. This wall serves one office
# (one book), so a seat in two offices holds two independent leases.
_GATE: dict[str, float] = {}
_GATE_LOCK = threading.Lock()
# #669: desk -> the lease its held-back items belong to (the gate time), the
# latest of them and the distinct item keys, for the one trailing POST.
_TRAIL: dict[str, dict[str, Any]] = {}
# F144: desk -> the note its last run left with mill wake-done, for the next wake.
_NOTE: dict[str, str] = {}
# F144b (card 888): desk -> the token of its current lease, sent as wake.lease;
# mill wake-done --lease TOKEN ends only that lease.
_EPOCH: dict[str, str] = {}


def _new_lease(desk: str, now: float) -> str:
    """Start a lease and return its id. Caller holds _GATE_LOCK."""
    import uuid

    token = uuid.uuid4().hex[:12]
    _GATE[desk] = now
    _EPOCH[desk] = token
    return token


def _gate_take(desk: str, now: float) -> bool:
    """True when this desk may be POSTed now; then the lease starts."""
    with _GATE_LOCK:
        last = _GATE.get(desk)
        if last is not None and now - last < lease_s():
            return False
        _new_lease(desk, now)
        return True


def _gate_open(desk: str, now: float) -> bool:
    """True when no window is running for this desk. Takes nothing."""
    with _GATE_LOCK:
        last = _GATE.get(desk)
        return last is None or now - last >= lease_s()


def gate_clear(desk: str) -> None:
    """Drop the desk's lease and held-back items with no trailing POST (an Admin
    reset, a test). A connect sync no longer calls this (F144): mill wake-done does."""
    d = str(desk or "").strip()
    with _GATE_LOCK:
        _GATE.pop(d, None)
        _EPOCH.pop(d, None)
        _TRAIL.pop(d, None)
    try:
        from agent_coord.server import wasted_wake

        wasted_wake.clear_lease(d)
    except Exception:
        pass


def lease_synced(desk: str) -> None:
    """F144: a connect sync handed over the queue. The lease stays held; the
    items it held back so far were delivered, so pending_count starts again."""
    d = str(desk or "").strip()
    with _GATE_LOCK:
        t = _TRAIL.get(d)
        if t is not None:
            t["keys"] = set()


def _schedule(delay: float, fn, *args) -> None:
    """Run fn(*args) once after delay seconds on a daemon timer thread."""
    t = threading.Timer(max(0.0, float(delay)), fn, args=args)
    t.daemon = True
    t.start()


def _book():
    """A book connection of the timer's own (the caller's has gone by window end)."""
    from agent_coord.server.records.db import connect

    return connect()


def _item_key(frame: dict[str, Any], hint_id: int | None) -> str:
    """One key per item, so a repeated item counts once in pending_count (F144)."""
    idem = str(frame.get("idem") or "").strip()
    if idem:
        return idem
    ident = hint_id if hint_id is not None else frame.get("id")
    return f"{frame.get('kind') or ''}:{frame.get('type') or ''}:{ident}"


def _hold_locked(desk: str, now: float, frame: dict[str, Any], hint_id: int | None,
                 reason: str, room: str | None) -> float | None:
    """Caller holds _GATE_LOCK. When a live lease is held, record the item under
    it and return the lease start if this is its first held-back item (the
    caller schedules the lease-end check), else -1.0. None: no live lease."""
    at = _GATE.get(desk)
    if at is None or now - at >= lease_s():
        return None
    t = _TRAIL.get(desk)
    first = t is None or t.get("at") != at
    if first:
        t = _TRAIL[desk] = {"at": at, "reason": reason, "keys": set()}
    elif reason == ADDRESSED:
        t["reason"] = ADDRESSED  # #627: the burst is addressed when any item is
    t["keys"].add(_item_key(frame, hint_id))
    t.update(frame=dict(frame), hint_id=hint_id, room=room)
    return at if first else -1.0


def _hold_or_take(desk: str, frame: dict[str, Any], hint_id: int | None, reason: str, room: str | None,
                  *, take: bool) -> str | None:
    """One lock hold (F144a, card 887). A live lease: record the item it holds back
    and return "" (the first one in a lease schedules the lease-end check, #669).
    No live lease: None, or with take=True start a lease in the same hold and
    return its id, which the caller puts on its POST as is (F144b: never read
    _EPOCH again, a done or a newer take may have changed it since)."""
    import time

    now = time.monotonic()
    with _GATE_LOCK:
        first = _hold_locked(desk, now, frame, hint_id, reason, room)
        if first is None:
            return _new_lease(desk, now) if take else None
    if first >= 0:
        _schedule(first + lease_s() - time.monotonic(), trail, desk, first)
    return ""


def _coalesced(desk: str, frame: dict[str, Any], hint_id: int | None, reason: str, room: str | None) -> bool:
    """True when a live lease held the item back (recorded in the same lock hold
    as the check, so a wake-done can never land between them; F144a)."""
    return _hold_or_take(desk, frame, hint_id, reason, room, take=False) == ""


def _send_trailing(cn, desk: str, t: dict[str, Any], why: str) -> str:
    """The one trailing POST for a lease's held-back items (F144). none when the
    run's own connect syncs already took every waiting row and no unread mail
    remains (#949). A short connect that drained the push queue without opening
    the letter still gets one trailing wake for the unread mailbox."""
    from agent_coord.server.poke_key import FIELD, letter_key
    from agent_coord.server.records import push as rec_push

    waiting = rec_push.pending(cn, desk)
    if waiting > 0:
        return post_desk(cn, desk, t["frame"], hint_id=t.get("hint_id"),
                         reason=t.get("reason") or ADDRESSED, room=t.get("room"),
                         trailing=why, pending_count=len(t.get("keys") or ()) or waiting)
    # Push drained: still wake when mailbox letters stay unopened (#949).
    try:
        from agent_coord.server.push import unread_mail_frames

        unread = unread_mail_frames(cn, desk)
    except Exception:
        unread = []
    if not unread:
        _bc_log_safe(f"webhook desk={desk} wake=none reason=drained held={len(t.get('keys') or ())}")
        return "none"
    frame = dict(unread[0])
    mid = int(frame.get("id") or 0)
    frame[FIELD] = letter_key(mid, desk)
    return post_desk(cn, desk, frame, hint_id=mid,
                     reason=ADDRESSED, room=None,
                     trailing=why, pending_count=len(unread))


def trail(desk: str, at: float) -> str:
    """Lease end with no done (#669, F144): one trailing POST when items were held
    back in the lease that started at `at`. sent | error | none.

    none: the run said done (lease_done sent the trailing POST), a later POST
    already took a new lease, or the run read every item itself. The trailing
    POST takes a lease of its own, so items after it get at most one more POST.
    """
    with _GATE_LOCK:
        t = _TRAIL.get(desk)
        if t is None or t.get("at") != at:
            return "none"
        _TRAIL.pop(desk, None)
        if _GATE.get(desk) != at:
            return "none"
        _GATE.pop(desk, None)  # this lease is over; post_desk takes the next one
        _EPOCH.pop(desk, None)
    cn = None
    try:
        cn = _book()
        return _send_trailing(cn, desk, t, "lease-expired")
    except Exception as e:
        _wake_log(desk, t.get("frame") or {}, t.get("hint_id"), f"fail err={type(e).__name__} reason=lease-expired")
        return "error"
    finally:
        if cn is not None:
            try:
                cn.close()
            except Exception:
                pass


def _clean_note(raw: Any) -> str:
    """One line, at most NOTE_MAX characters, secrets redacted."""
    text = " ".join(str(raw or "").split())
    try:
        from agent_coord.server.redact import redact_secrets

        text = redact_secrets(text)
    except Exception:
        pass
    return text[:NOTE_MAX]


def lease_done(cn, desk: str, note: str = "", lease: str = "") -> str:
    """mill wake-done (F144): the woken run is finished. Ends this desk's lease; when
    items were held back and still wait, sends exactly one trailing wake with
    pending_count and the note. sent | error | none | stale | sitting. A second
    done is a no-op. sitting (#889): the desk still has a live /ws, so no trailing
    POST; the connect or ring-on-leave covers the rows.

    lease (F144b, card 888): the wake.lease token the run was woken with. A token
    that is not the current lease's is a stale done (a run that outlived its
    lease): it keeps its note for the next wake, unless a newer one waits, and
    ends nothing. No token (an older client) ends the current lease."""
    import time

    d = str(desk or "").strip()
    text = _clean_note(note)
    token = str(lease or "").strip()
    now = time.monotonic()
    with _GATE_LOCK:
        if token and token != _EPOCH.get(d):
            if text and d not in _NOTE:
                _NOTE[d] = text
            stale = True
        else:
            stale = False
            at = _GATE.pop(d, None)
            _EPOCH.pop(d, None)
            t = _TRAIL.pop(d, None)
            if text:
                _NOTE[d] = text
    if stale:
        _bc_log_safe(f"webhook desk={d} wake=done stale=yes note={'yes' if text else 'no'}")
        return "stale"
    if t is not None and t.get("at") != at:
        t = None
    held = len((t or {}).get("keys") or ())
    age = f"{now - at:.0f}" if at is not None else "none"
    _bc_log_safe(f"webhook desk={d} wake=done held_s={age} queued={held} note={'yes' if text else 'no'}")
    try:
        from agent_coord.server import wasted_wake

        wasted_wake.finish_lease(d, cn=cn)
    except Exception:
        pass
    if not t:
        return "none"
    # #889: wake-done inside an open connect must not POST a trailing wake to a
    # still-sitting desk; the live connect (or ring-on-leave) covers the rows.
    try:
        from agent_coord.server.push import desk_sitting
        sitting = desk_sitting(d)
    except Exception:
        sitting = False
    if sitting:
        _bc_log_safe(f"webhook desk={d} wake=done sitting=yes held={held} reason=no-trailing")
        return "sitting"
    try:
        return _send_trailing(cn, d, t, "trailing")
    except Exception as e:
        _wake_log(d, t.get("frame") or {}, t.get("hint_id"), f"fail err={type(e).__name__} reason=trailing")
        return "error"


def _wake_log(desk: str, frame: dict[str, Any], hint_id: int | None, outcome: str) -> None:
    """One line per desk per wake attempt (#625). Never the URL, its host, or the key
    (the same rule as the webhook fail line; mill connect shows the host)."""
    kind = str(frame.get("kind") or "").strip()
    item = f"kind={kind}" if kind and kind != "hint" else f"type={frame.get('type') or 'hint'}"
    ident = hint_id if hint_id is not None else frame.get("id")
    try:
        from agent_coord.server.push import _bc_log

        _bc_log(f"webhook desk={desk} {item} id={ident} wake={outcome}")
    except Exception:
        return


# #838: desk -> its current run of failed wakes {n, since, status, why, host}.
# Server memory only: a restart forgets it, and the next failing wake starts again.
_FAILS: dict[str, dict[str, Any]] = {}
_FAILS_LOCK = threading.Lock()
FAIL_ALERT_N = 3


def _fail_run(cn, desk: str, status: int | None, err: str, host: str) -> None:
    """Count one failed wake. At FAIL_ALERT_N in a row: one Admin letter for this run."""
    import datetime as _dt

    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    with _FAILS_LOCK:
        run = _FAILS.setdefault(desk, {"n": 0, "since": now})
        run["n"] += 1
        run.update(status=status, err=err)
        n = run["n"]
        since = run["since"]
    if n != FAIL_ALERT_N:
        return
    answer = _answer(status, err)
    _bc_log_safe(f"webhook desk={desk} failing n={n} since={since}")
    try:
        from agent_coord.server.push import mill_admin_alert

        mill_admin_alert(
            cn,
            f"Webhook wakes for desk {desk} are failing: {n} in a row since {since}, last answer {answer}. "
            f"Its letters stay queued and reach it on its next mill connect. {_fix_for(status, err, host)}.",
            command="wake",
        )
    except Exception:
        return


def _answer(status: int | None, err: str) -> str:
    """'400 (reason)' for an HTTP answer, else the error type."""
    if status is None:
        return err or "error"
    return f"{status} ({err})" if err else f"{status}"


def _fail_clear(desk: str) -> None:
    with _FAILS_LOCK:
        _FAILS.pop(desk, None)


def fail_note(desk: str) -> str:
    """'' or the desk's failing run, for its connect sync wake line (#838)."""
    with _FAILS_LOCK:
        run = dict(_FAILS.get(str(desk or "").strip()) or {})
    if not run:
        return ""
    last = _answer(run.get("status"), str(run.get("err") or ""))
    n = int(run["n"])
    return (f"failing: {n} wake{'' if n == 1 else 's'} in a row since {run['since']}, last {last}; "
            "letters wait for mill connect")


def _bc_log_safe(line: str) -> None:
    try:
        from agent_coord.server.push import _bc_log

        _bc_log(line)
    except Exception:
        return


# Card 827. A failed desk wake retries off the request that queued it. Full jitter
# starts at 5s and doubles, never past 10 min, and the waits stop at about 1 h.
# Every retry posts the same body, so the idempotency key and the lease stay one
# wake, not a new window. A 4xx other than 408 or 429 does not retry. The retry
# stops when the desk connects and the queue drains, or a newer wake for that
# desk succeeds. The timer is process memory: a restart drops it.
RETRY_BASE_S = 5.0
RETRY_CAP_S = 600.0
RETRY_BUDGET_S = 3600.0
RETRY_MAX = 64


def _roll() -> float:
    import random

    return random.random()


def retry_delay(attempt: int, roll: float | None = None) -> float:
    """Full jitter for one retry. Attempt 1 waits up to 5s, then double, never past 10 min.

    roll is 0..1. Omit it to draw one. 1 waits the whole span; 0 waits nothing.
    """
    n = max(1, int(attempt))
    span = min(RETRY_CAP_S, RETRY_BASE_S * (2 ** (n - 1)))
    got = _roll() if roll is None else float(roll)
    if got < 0.0:
        got = 0.0
    elif got > 1.0:
        got = 1.0
    return got * span


def _retryable(status: int | None) -> bool:
    """Timeout, connection error, 408, 429, and 5xx. Any other 4xx or a redirect is not."""
    if status is None:
        return True
    code = int(status)
    if code in (408, 429):
        return True
    return 500 <= code <= 599


# Desk -> how many of its wakes have succeeded. A retry stores the value at arm
# time and stops when a later success moves it.
_OK_GEN: dict[str, int] = {}
_OK_LOCK = threading.Lock()


def _wake_ok(desk: str) -> None:
    """A wake for this desk succeeded. Older retries stop."""
    d = str(desk or "").strip()
    if not d:
        return
    with _OK_LOCK:
        _OK_GEN[d] = int(_OK_GEN.get(d, 0)) + 1


def _ok_gen(desk: str) -> int:
    with _OK_LOCK:
        return int(_OK_GEN.get(str(desk or "").strip(), 0))


def _queue_drained(desk: str) -> bool:
    """True when this desk's push queue is empty: it connected and took the rows."""
    cn = None
    try:
        from agent_coord.server.records import push as rec_push

        cn = _book()
        return rec_push.pending(cn, desk) <= 0
    except Exception:
        return False
    finally:
        if cn is not None:
            try:
                cn.close()
            except Exception:
                pass


def _arm_retry(
    url: str,
    body: dict[str, Any],
    *,
    key: str | None,
    desk: str,
    hint_id: int | None,
    frame: dict[str, Any],
    status: int | None,
    err: str,
    note: str | None,
    tag: str,
) -> None:
    """Schedule the next POST off the caller. One line when the budget runs out."""
    state: dict[str, Any] = {
        "attempts": 0,
        "spent": 0.0,
        "status": status,
        "err": err,
        "gen": _ok_gen(desk),
        "alive": True,
    }

    def _stopped() -> bool:
        if not state["alive"]:
            return True
        if _ok_gen(desk) != state["gen"]:
            state["alive"] = False
            return True
        if _queue_drained(desk):
            state["alive"] = False
            return True
        return False

    def _exhaust() -> None:
        if not state["alive"]:
            return
        state["alive"] = False
        st = state["status"]
        if st is None:
            outcome = f"retry-exhausted attempts={state['attempts']} err={state['err'] or 'Exception'}"
        else:
            outcome = f"retry-exhausted attempts={state['attempts']} status={int(st)}"
        _wake_log(desk, frame, hint_id, outcome)

    def pump() -> None:
        if not state["alive"]:
            return
        if state["attempts"] >= RETRY_MAX or state["spent"] >= RETRY_BUDGET_S:
            _exhaust()
            return
        remain = RETRY_BUDGET_S - float(state["spent"])
        state["attempts"] = int(state["attempts"]) + 1
        delay = min(retry_delay(int(state["attempts"])), remain)

        def once() -> None:
            state["spent"] = float(state["spent"]) + delay
            if _stopped():
                return
            st, er = _post_status(
                url, body, timeout=WAKE_TIMEOUT_S, key=key, desk=desk, hint_id=hint_id, quiet=True,
            )
            state["status"], state["err"] = st, er
            if st is not None and 200 <= st <= 299:
                state["alive"] = False
                _wake_ok(desk)
                if note is not None:
                    with _GATE_LOCK:
                        if _NOTE.get(desk) == note:
                            _NOTE.pop(desk, None)
                _fail_clear(desk)
                _wake_log(desk, frame, hint_id, f"sent status={st} reason=retry{tag}")
                return
            if not _retryable(st):
                state["alive"] = False
                return
            pump()

        _schedule(delay, once)

    pump()


def post_desk(
    cn,
    desk: str,
    frame: dict[str, Any],
    *,
    hint_id: int | None = None,
    reason: str = ADDRESSED,
    room: str | None = None,
    trailing: str = "",
    ring: str = "",
    pending_count: int = 0,
) -> str:
    """Wake an armed desk that is not sitting. sent | coalesced | skipped | error | off.

    ring (#832): why a wake with no new item went out (leave: the last socket left
    with rows it never got live; unsent: a live frame found no socket). The log
    line ends reason=RING.

    trailing (#669, F144): trailing (after mill wake-done) or lease-expired: the one
    POST for items the lease held back; every item is already in the queue, so
    pending is the queue size, pending_count the distinct items held back, and
    the log line ends reason=TRAILING.

    skipped (#628): a room-only item for a desk armed with --wake-on addressed.

    coalesced: a wake already went out and its lease is held (no done, not timed
    out); the item waits in the push queue like every other one.
    Every outcome but off logs one line (#625): sent with the status, coalesced
    or skipped with the reason, fail with the status or error type.
    """
    import time

    from agent_coord.server.records import join as rec_join

    target = rec_join.wake_target(cn, desk)
    if not target:
        return "off"
    url, key = target
    if reason == ROOM and rec_join.wake_state(cn, desk).get("wake_on") == ADDRESSED:
        # #628: this desk wakes for addressed items only. The item still waits in
        # the queue for its next connect; no window is taken.
        _wake_log(desk, frame, hint_id, "skipped reason=room-only")
        return "skipped"
    if _coalesced(desk, frame, hint_id, reason, room):
        # A wake already went out and its lease is live: skip the checks and the DNS
        # lookup. Checked and recorded in one lock hold (F144a, card 887).
        _wake_log(desk, frame, hint_id, "coalesced reason=lease")
        return "coalesced"
    try:
        url, host = check_url(url)
    except WakeRefused:
        _wake_log(desk, frame, hint_id, "skipped reason=not-allowed")
        return "error"
    if not public_host(host):
        _wake_log(desk, frame, hint_id, "skipped reason=not-public")
        return "error"
    # The window starts only for a POST that is actually attempted: a refused or
    # unresolvable target takes no gate, so it never blocks the next valid wake.
    # Taken here (not peeked) so two threads racing past the peek send one POST;
    # the loser is recorded under the winner's lease in the same hold (card 887).
    lease = _hold_or_take(desk, frame, hint_id, reason, room, take=True)
    if not lease:
        _wake_log(desk, frame, hint_id, "coalesced reason=lease")
        return "coalesced"
    from agent_coord.server.records import push as rec_push

    # #832: every item is queued before this call, so pending is the queue size.
    pending = rec_push.pending(cn, desk)
    # #627: a coalesced burst is addressed when any waiting item is addressed.
    if reason != ADDRESSED and rec_push.pending_addressed(cn, desk):
        reason = ADDRESSED
    with _GATE_LOCK:
        note = _NOTE.get(desk)
    body = wake_body(desk, frame, pending=pending, roster=desk_roster(cn, desk), reason=reason, room=room,
                     pending_count=pending_count, last_note=note, lease=lease)
    # One POST on this call. A retryable failure is the same wake again, later,
    # off this request (card 827). _fire's immediate second try stays on the
    # hook path only.
    status, err = _post_status(
        url, body, timeout=WAKE_TIMEOUT_S, key=key, desk=desk, hint_id=hint_id, quiet=True,
    )
    tag = f" reason={trailing}" if trailing else (f" reason={ring}" if ring else "")
    if status is not None and 200 <= status <= 299:
        _wake_ok(desk)
        if note is not None:
            with _GATE_LOCK:
                if _NOTE.get(desk) == note:
                    _NOTE.pop(desk, None)  # the note rode this wake
        _fail_clear(desk)
        _wake_log(desk, frame, hint_id, f"sent status={status}{tag}")
        try:
            from agent_coord.server import wasted_wake

            opened = False
            if str(frame.get("kind") or "") == "mail" and hint_id is not None:
                try:
                    from agent_coord.server.records import opened as rec_opened

                    opened = int(hint_id) in rec_opened.read_ids(cn, [int(hint_id)], desk)
                except Exception:
                    opened = False
            tag_name = wasted_wake.classify_trigger(
                frame=frame, reason=reason, opened=opened, ring=ring, trailing=trailing
            )
            wasted_wake.mark_lease(desk, trigger=tag_name, wake_id=int(hint_id) if hint_id is not None else 0)
        except Exception:
            pass
        try:
            if str(frame.get("kind") or "") == "mail" and hint_id is not None:
                from agent_coord.server import mail_activity as ma

                did = ma.desk_id_for(cn, desk) or 0
                ma.emit_delivered(cn, mail_id=int(hint_id), desk_id=int(did))
                ma.emit_woken(cn, mail_id=int(hint_id), desk_id=int(did))
        except Exception:
            pass
        return "sent"
    why = f"status={status}" if status is not None else f"err={err or 'Exception'}"
    if status is not None and err:
        why += f' why="{err}"'
    _wake_log(desk, frame, hint_id, f"fail {why}{tag}")
    _fail_run(cn, desk, status, err, host)
    from agent_coord.server.poke_key import FIELD

    if pending > 0 and _retryable(status) and str((body or {}).get(FIELD) or "").strip():
        _arm_retry(
            url, body, key=key, desk=desk, hint_id=hint_id, frame=frame,
            status=status, err=err, note=note, tag=tag,
        )
    return "error"
