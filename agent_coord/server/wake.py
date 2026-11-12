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
        "cap_s": int(cap_s()),
        "next": (
            "nothing to do: this is the join test"
            if test
            else f"mill connect -r {desk}: the sync line hands over every waiting hint and letter, "
            "and this desk's routes walk them. A busy answer means another session has the seat "
            "and gets these letters: stop. Last step of the run: mill wake-done --lease LEASE --note TEXT "
            "(LEASE is wake.lease; one wake at a time; letters that came meanwhile ring once after it). "
            "export MILL_LEASE=LEASE first: every mill command then renews the lease, up to cap_s"
        ),
    }
    return stamp_mill(body)


ADDRESSED = "addressed"
# Card 1141: tw.event kinds that ring on an empty queue.
TW_ALERTS = frozenset({"stall", "match"})
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
# #949: only letters actually handed to this run are completed by wake-done.
# Mail arriving after its last sync remains eligible for the trailing wake.
_LEASE_MAIL: dict[str, set[int]] = {}
_DONE_MAIL: dict[str, set[int]] = {}
# Same-letter re-rings: four retries at 1, 2, 4, 8 minutes, then a health signal.
# Like the lease and transport retry state, this is wall-process memory.
_RERINGS: dict[tuple[str, int], dict[str, Any]] = {}
RERING_DELAYS = (60.0, 120.0, 240.0, 480.0)
# Card 1140: desk -> the renewed end of its lease (monotonic), when a command
# carrying the live token pushed it past lease start + lease_s().
_UNTIL: dict[str, float] = {}
# Card 1140: desk -> tokens of leases that lapsed in memory with no record yet;
# the next ring records each as expired.
_LAPSED: dict[str, list[str]] = {}
# Card 1140: desk -> the token of the lease this wall ended last (done or
# lapse), so a second wake-done on it is already_done, not stale.
_ENDED: dict[str, str] = {}


def _live_locked(desk: str, now: float) -> bool:
    """Caller holds _GATE_LOCK. True while the desk's lease runs (renewal counted)."""
    at = _GATE.get(desk)
    if at is None:
        return False
    return now < max(at + lease_s(), _UNTIL.get(desk, 0.0))


def cap_s() -> float:
    """Card 1140: a renewed lease never runs past this many seconds from its ring."""
    from agent_coord.server.wake_lease import CAP_LEASES

    return CAP_LEASES * lease_s()


def _new_lease(desk: str, now: float) -> str:
    """Start a lease and return its id. Caller holds _GATE_LOCK."""
    import uuid

    token = uuid.uuid4().hex[:12]
    old = _EPOCH.get(desk)
    if old:
        _LAPSED.setdefault(desk, []).append(old)
    _UNTIL.pop(desk, None)
    _GATE[desk] = now
    _EPOCH[desk] = token
    _LEASE_MAIL[desk] = set()
    return token


def _gate_take(desk: str, now: float) -> bool:
    """True when this desk may be POSTed now; then the lease starts."""
    with _GATE_LOCK:
        if _live_locked(desk, now):
            return False
        _new_lease(desk, now)
        return True


def _gate_open(desk: str, now: float) -> bool:
    """True when no window is running for this desk. Takes nothing."""
    with _GATE_LOCK:
        return not _live_locked(desk, now)


def gate_clear(desk: str, cn=None) -> None:
    """Drop the desk's lease and held-back items with no trailing POST (an Admin
    reset, a test). A connect sync no longer calls this (F144): mill wake-done does.
    Card 1140: with cn, the lease's record ends cleared."""
    d = str(desk or "").strip()
    with _GATE_LOCK:
        _GATE.pop(d, None)
        token = _EPOCH.pop(d, None)
        _UNTIL.pop(d, None)
        _LAPSED.pop(d, None)
        _TRAIL.pop(d, None)
        _LEASE_MAIL.pop(d, None)
        _DONE_MAIL.pop(d, None)
        for key in [k for k in _RERINGS if k[0] == d]:
            _RERINGS.pop(key, None)
    try:
        from agent_coord.server import wasted_wake

        wasted_wake.clear_lease(d)
    except Exception:
        pass
    if cn is not None:
        try:
            from agent_coord.server import wake_lease

            if not token:  # wall memory lost it (a restart); the book may still have it live
                token = (wake_lease.live_in_book(cn, d, cap_s()) or ("", 0.0))[0]
            if token:
                wake_lease.record_end(cn, token, "cleared")
        except Exception:
            pass


def lease_synced(desk: str, frames=()) -> None:
    """F144: a connect sync handed over the queue. The lease stays held; the
    items it held back so far were delivered, so pending_count starts again."""
    d = str(desk or "").strip()
    with _GATE_LOCK:
        if d in _GATE:
            _LEASE_MAIL.setdefault(d, set()).update(
                int(f["id"]) for f in frames
                if f.get("kind") == "mail" and f.get("id")
            )
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
    if not _live_locked(desk, now):
        return None
    at = _GATE[desk]
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


def _adopt_from_book(cn, desk: str) -> None:
    """Card 1140: wall memory has no lease for this desk (a restart) but the book
    has a live one: take it back into memory, so this item is held under it and
    rings once when it ends, instead of a second live lease (a double wake)."""
    import time

    with _GATE_LOCK:
        if desk in _GATE:
            return
    try:
        from agent_coord.server import wake_lease

        got = wake_lease.live_in_book(cn, desk, lease_s())
    except Exception:
        return
    if not got:
        return
    token, age = got
    with _GATE_LOCK:
        if desk in _GATE:
            return
        _GATE[desk] = time.monotonic() - max(0.0, age)
        _EPOCH[desk] = token
        _LEASE_MAIL[desk] = set()


def _record_ring(cn, desk: str, token: str, wake_id: int) -> None:
    """Card 1140: record the leases that lapsed unrecorded as expired, then this ring."""
    with _GATE_LOCK:
        lapsed = _LAPSED.pop(desk, [])
    try:
        from agent_coord.server import wake_lease

        for old in lapsed:
            wake_lease.record_end(cn, old, "expired")
        wake_lease.record_ring(cn, desk, token, wake_id)
    except Exception as e:
        _bc_log_safe(f"webhook desk={desk} lease=record err={type(e).__name__}")


def lease_renew(cn, desk: str, token: str) -> str:
    """Card 1140 (Auditor 5532 Q3): a command that carries the live lease token
    pushes the lease end to now + lease_s(), never past ring + cap_s().
    renewed | refused (an older or unknown token, or a lapsed lease: renews nothing)."""
    import time

    d = str(desk or "").strip()
    tok = str(token or "").strip()
    now = time.monotonic()
    with _GATE_LOCK:
        if not tok or tok != _EPOCH.get(d) or not _live_locked(d, now):
            return "refused"
        at = _GATE[d]
        _UNTIL[d] = max(_UNTIL.get(d, 0.0), min(now + lease_s(), at + cap_s()))
    return "renewed"


def _coalesced(desk: str, frame: dict[str, Any], hint_id: int | None, reason: str, room: str | None) -> bool:
    """True when a live lease held the item back (recorded in the same lock hold
    as the check, so a wake-done can never land between them; F144a)."""
    return _hold_or_take(desk, frame, hint_id, reason, room, take=False) == ""


def mail_picked_up(cn, desk: str, mid: int) -> bool:
    """One stop rule shared by fresh, leave, trailing and replay wake paths."""
    with _GATE_LOCK:
        if mid in _DONE_MAIL.get(desk, ()):
            return True
    from agent_coord.server.records import opened

    return mid in opened.picked_up_ids(cn, [mid], desk)


def _send_trailing(cn, desk: str, t: dict[str, Any], why: str) -> str:
    """The one trailing POST for a lease's held-back items (F144). none when the
    run's own connect syncs already took every waiting row and no unread mail
    remains (#949). Only letters not already picked up or completed by this
    run can produce another wake; sync-only unread replay is not new mail."""
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
    unread = [f for f in unread if not mail_picked_up(cn, desk, int(f.get("id") or 0))]
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
    import time

    with _GATE_LOCK:
        t = _TRAIL.get(desk)
        if t is None or t.get("at") != at:
            return "none"
        if _GATE.get(desk) == at and _UNTIL.get(desk, 0.0) > time.monotonic():
            # Card 1140: renewed; check again at the renewed end.
            _schedule(_UNTIL.get(desk, 0.0) - time.monotonic(), trail, desk, at)
            return "renewed"
        _TRAIL.pop(desk, None)
        if _GATE.get(desk) != at:
            return "none"
        _GATE.pop(desk, None)  # this lease is over; post_desk takes the next one
        token = _EPOCH.pop(desk, None)
        _UNTIL.pop(desk, None)
        if token:
            _ENDED[desk] = token
    cn = None
    try:
        cn = _book()
        if token:
            try:
                from agent_coord.server import wake_lease

                wake_lease.record_end(cn, token, "expired")
            except Exception:
                pass
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
    pending_count and the note. sent | error | none | sitting when it ended the
    lease; already_done | stale when it ended nothing. sitting (#889): the desk
    still has a live /ws, so no trailing POST; the connect or ring-on-leave covers
    the rows.

    lease (F144b, card 888): the wake.lease token the run was woken with. Card 1140
    (Auditor 5532 change C), three outcomes for a token:
      ended  - it is the live lease: ends it, records lease_live -> done.
      already_done - that lease already ended (a second wake-done, the automatic
               wake-done, or it lapsed): records nothing, sends nothing.
      stale  - another lease is live, or the token is unknown: ends nothing (I2);
               the note waits for the next wake, unless a newer one waits.
    A live lease the book has but wall memory lost (a restart) ends as done.
    No token (an older client, the automatic wake-done) ends the live lease."""
    import time

    from agent_coord.server import wake_lease

    d = str(desk or "").strip()
    text = _clean_note(note)
    token = str(lease or "").strip()
    now = time.monotonic()
    at = None
    t = None
    with _GATE_LOCK:
        cur = _EPOCH.get(d)
        live = _live_locked(d, now)
        # This wall's lease: a no-token done ends it even when it lapsed (older
        # clients, the automatic done); a token done ends only its own lease.
        mine = d in _GATE and (not token or token == cur)
        lapsed = mine and not live
        if mine:
            at = _GATE.pop(d, None)
            _EPOCH.pop(d, None)
            _UNTIL.pop(d, None)
            t = _TRAIL.pop(d, None)
            if at is not None:
                _DONE_MAIL.setdefault(d, set()).update(_LEASE_MAIL.pop(d, set()))
            if text:
                _NOTE[d] = text
            _ENDED[d] = cur or ""
        last = _ENDED.get(d, "")
    ended = cur if mine else ""
    if not mine:
        row = None
        if token and cn is not None:
            try:
                row = wake_lease.ring_row(cn, token)
            except Exception:
                row = None
        if not token:
            got = "already_done"
        elif live or (row is None and token != last):
            got = "stale"
        elif row is None:
            got = "already_done"  # this wall ended it; no book row to read
        elif row["end"] or token == cur:
            got = "already_done"  # ended, or lapsed in memory (the next ring records it expired)
        else:
            # The book has it live and wall memory lost it (a restart).
            from datetime import datetime, timezone

            rung = row["at"]
            age_s = (datetime.now(timezone.utc).replace(tzinfo=None) - rung).total_seconds()
            if age_s < lease_s():
                ended = token
                got = ""
            else:
                try:
                    wake_lease.record_end(cn, token, "expired", {"late_s": int(age_s - lease_s())})
                except Exception:
                    pass
                got = "already_done"
        if got:
            if got == "stale" and text:
                with _GATE_LOCK:
                    _NOTE.setdefault(d, text)  # the note rides the next wake
            _bc_log_safe(f"webhook desk={d} wake=done {got}=yes note={'yes' if text else 'no'}")
            return got
    held = len((t or {}).get("keys") or ())
    if t is not None and t.get("at") != at:
        t = None
        held = 0
    age = f"{now - at:.0f}" if at is not None else "none"
    _bc_log_safe(f"webhook desk={d} wake=done held_s={age} queued={held} note={'yes' if text else 'no'}")
    stamp = None
    try:
        from agent_coord.server import wasted_wake

        stamp = wasted_wake.finish_lease(d)
    except Exception:
        stamp = None
    if ended and cn is not None:
        try:
            if lapsed:
                wake_lease.record_end(cn, ended, "expired")
            else:
                wake_lease.record_end(cn, ended, "done", (stamp or {}).get("meta"),
                                      desk=d, wake_id=int((stamp or {}).get("wake_id") or 0))
        except Exception:
            pass
    if not t:
        # A token done after its lease lapsed ended nothing that was still running.
        return "already_done" if lapsed and token else "none"
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


def auto_done(cn, desk: str, command: str = "") -> str:
    """Card 1098 item 5: end the lease when mark/answer cleared its waiting work.

    Fires only when the desk has a live lease, every letter in that lease is
    picked up, nothing addressed waits, and no unopened receipt remains.
    Tags W9 meta auto=1. command is the RPC that triggered this (reply, mark);
    note_rpc must run before finish_lease so an action command is not scored
    wasted (card 1090). Returns lease_done's result, or "" when not applicable.
    """
    d = str(desk or "").strip()
    if not d:
        return ""
    with _GATE_LOCK:
        if d not in _GATE:
            return ""
        mails = set(_LEASE_MAIL.get(d) or ())
    for mid in mails:
        if not mail_picked_up(cn, d, int(mid)):
            return ""
    try:
        from agent_coord.server import mail_push as mp
        from agent_coord.server.records import push as rec_push

        if rec_push.pending_addressed(cn, d):
            return ""
        if mp.has_unopened_receipt(cn, d):
            return ""
    except Exception:
        return ""
    try:
        from agent_coord.server import wasted_wake

        wasted_wake.tag_auto(d)
        if command:
            wasted_wake.note_rpc(d, command, ok=True)
    except Exception:
        pass
    return lease_done(cn, d, note="", lease="")


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
    """True when this desk's push queue is empty and no unread mailbox mail remains.

    Card 1005: a short connect can drain push rows without opening the letter.
    Retry must keep going while unread mail alone still needs a wake.
    """
    cn = None
    try:
        from agent_coord.server.records import push as rec_push

        cn = _book()
        if rec_push.pending(cn, desk) > 0:
            return False
        try:
            from agent_coord.server.push import unread_mail_frames

            if unread_mail_frames(cn, desk, limit=1):
                return False
        except Exception:
            pass
        return True
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
    cn=None,
    wake_id: int = 0,
) -> None:
    """Schedule the next POST off the caller. One line when the budget runs out."""
    _record_wake_retry(cn, desk, wake_id)
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
        if frame.get("kind") == "mail":
            cn = None
            try:
                cn = _book()
                if mail_picked_up(cn, desk, int(frame.get("id") or 0)):
                    state["alive"] = False
                    return True
            except Exception:
                pass
            finally:
                if cn is not None:
                    try:
                        cn.close()
                    except Exception:
                        pass
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


def _rering_wait(desk: str, mid: int, frame: dict[str, Any], **kw) -> str:
    """Delay repeated pending mail without delaying a different, NEW letter."""
    import time

    key = (desk, mid)
    with _GATE_LOCK:
        state = _RERINGS.get(key)
        if state is None:
            return ""
        if state["n"] >= len(RERING_DELAYS):
            if not state.get("stuck"):
                state["stuck"] = True
                _wake_log(desk, frame, mid, "stuck-ring attempts=4 reason=no-new-mail")
            return "none"
        delay = state["next"] - time.monotonic()
        if delay <= 0:
            return ""
        if state.get("timer"):
            return "deferred"
        state["timer"] = True

    def once():
        with _GATE_LOCK:
            if _RERINGS.get(key) is not state:
                return
            state["timer"] = False
        cn = None
        try:
            cn = _book()
            post_desk(cn, desk, frame, **kw)
        except Exception as e:
            _wake_log(desk, frame, mid, f"fail err={type(e).__name__} reason=rering")
        finally:
            if cn is not None:
                cn.close()

    _schedule(delay, once)
    return "deferred"



def _fail_why(status: int | None, err: str) -> str:
    """Short why token for W9-style meta: no host, url, or receiver text."""
    if status is not None:
        return "http"
    e = str(err or "").lower()
    if "timeout" in e:
        return "timeout"
    if "connect" in e or "refused" in e:
        return "conn"
    return "error"


def _wake_row_for_fail(cn, desk: str, wake_id: int) -> tuple[int, str, int] | None:
    """(id, state, desk_id) for the named wake row, or None.

    A POST with no wake row (wake_id=0: tw.event stall/exit/crash, trailing)
    writes no row state. desk is kept so callers can pass the woken desk.
    """
    if cn is None:
        return None
    wid = int(wake_id or 0)
    if wid <= 0 or not str(desk or "").strip():
        return None
    cur = cn.cursor()
    try:
        cur.execute(
            "SELECT id, state, desk_id FROM wake WHERE id = %s AND type = 'wake'",
            (wid,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return int(row[0]), str(row[1] or ""), int(row[2] or 0)
    finally:
        cur.close()


def _record_wake_fail(
    cn, desk: str, wake_id: int, status: int | None, err: str, *, retry: int
) -> None:
    """missed|queued -> error / wake_fail (card 1111). Best-effort; never raises."""
    try:
        from agent_coord.server import transition as tr
        from agent_coord.server.transition_enums import ActivityType, Reason, State

        got = _wake_row_for_fail(cn, desk, wake_id)
        if not got:
            return
        wid, state, did = got
        if state not in ("queued", "missed"):
            return
        frm = State.queued if state == "queued" else State.missed
        meta = {
            "status": None if status is None else int(status),
            "why": _fail_why(status, err),
            "retry": 1 if int(retry or 0) else 0,
        }
        tr.put(
            cn,
            activity_type=ActivityType.wake,
            activity_id=wid,
            from_state=frm,
            to_state=State.error,
            reason=Reason.wake_fail,
            desk_id=did,
            role="office",
            meta=meta,
        )
        cur = cn.cursor()
        try:
            cur.execute(
                "UPDATE wake SET state = 'error' WHERE id = %s AND type = 'wake'"
                " AND state IN ('queued', 'missed')",
                (wid,),
            )
        finally:
            cur.close()
        try:
            from agent_coord.server.records.db import commit as db_commit

            db_commit(cn)
        except Exception:
            pass
    except Exception:
        return


def _record_wake_retry(cn, desk: str, wake_id: int) -> None:
    """error -> retry_armed / wake_retry (card 1111). Best-effort; never raises."""
    try:
        from agent_coord.server import transition as tr
        from agent_coord.server.transition_enums import ActivityType, Reason, State

        got = _wake_row_for_fail(cn, desk, wake_id)
        if not got:
            return
        wid, state, did = got
        if state != "error":
            return
        tr.put(
            cn,
            activity_type=ActivityType.wake,
            activity_id=wid,
            from_state=State.error,
            to_state=State.retry_armed,
            reason=Reason.wake_retry,
            desk_id=did,
            role="office",
        )
        cur = cn.cursor()
        try:
            cur.execute(
                "UPDATE wake SET state = 'retry_armed' WHERE id = %s AND type = 'wake'"
                " AND state = 'error'",
                (wid,),
            )
        finally:
            cur.close()
        try:
            from agent_coord.server.records.db import commit as db_commit

            db_commit(cn)
        except Exception:
            pass
    except Exception:
        return


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
    wake_id: int = 0,
) -> str:
    """Wake an armed desk that is not sitting.

    sent | coalesced | skipped | error | off | none (picked up) | deferred (backoff).

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
    mid = int(frame.get("id") or 0) if frame.get("kind") == "mail" else 0
    if mid and mail_picked_up(cn, desk, mid):
        _wake_log(desk, frame, hint_id, "none reason=picked-up")
        return "none"
    # Card 1098 item 5c: skip empty wakes before they spend an LLM turn.
    # counts_as_waiting / has_unopened_receipt live in mail_push (card 1093).
    # Card 1141: only tw stall and match (mid-run alerts, no queue row) are
    # exempt. A tw exit or crash is the desk's own run ending; it rings only
    # when something waits, like every other wake.
    if not (frame.get("watch_id") and frame.get("kind") in TW_ALERTS):
        try:
            from agent_coord.server import mail_push as mp
            from agent_coord.server.records import push as rec_push
            from agent_coord.server.push import unread_mail_frames

            pending0 = rec_push.pending(cn, desk)
            unread = [
                f
                for f in unread_mail_frames(cn, desk)
                if not mail_picked_up(cn, desk, int(f.get("id") or 0))
            ]
            if not mp.counts_as_waiting(
                pending=pending0,
                unread=bool(unread),
                unopened_receipt=mp.has_unopened_receipt(cn, desk),
            ):
                _wake_log(desk, frame, hint_id, "skipped reason=empty")
                return "skipped"
        except Exception:
            pass
    if reason == ROOM and rec_join.wake_state(cn, desk).get("wake_on") == ADDRESSED:
        # #628: this desk wakes for addressed items only. Receipt dests arrive
        # as reason=addressed via mail_push.wake_reason_for_dest (card 1093),
        # so they never hit this room-only skip.
        _wake_log(desk, frame, hint_id, "skipped reason=room-only")
        return "skipped"
    _adopt_from_book(cn, desk)
    if _coalesced(desk, frame, hint_id, reason, room):
        # A wake already went out and its lease is live: skip the checks and the DNS
        # lookup. Checked and recorded in one lock hold (F144a, card 887).
        _wake_log(desk, frame, hint_id, "coalesced reason=lease")
        return "coalesced"
    if mid and (trailing or ring or frame.get("outcome") == "missed"):
        wait = _rering_wait(desk, mid, frame, hint_id=hint_id, reason=reason, room=room,
                            trailing=trailing, ring=ring, pending_count=pending_count)
        if wait:
            return wait
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
    _record_ring(cn, desk, lease, wake_id)
    with _GATE_LOCK:
        if mid:
            _LEASE_MAIL.setdefault(desk, set()).add(mid)
            old = _RERINGS.get((desk, mid))
            n = old["n"] + 1 if old else 0
            _RERINGS[(desk, mid)] = {
                "n": n, "next": time.monotonic() + RERING_DELAYS[min(n, len(RERING_DELAYS) - 1)],
            }
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
            kind_s = "tw" if frame.get("watch_id") else str(frame.get("kind") or "hint").strip().lower()
            if kind_s not in ("mail", "hint", "receipt", "tw"):
                kind_s = "hint"
            wasted_wake.mark_lease(
                desk,
                trigger=tag_name,
                wake_id=int(wake_id or 0),
                pending0=int(pending or 0),
                addressed=1 if reason == ADDRESSED else 0,
                kind=kind_s,
            )
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

    # Card 1005: arm retry when push is empty but mailbox unread remains
    # (short connect drained push without opening the letter).
    has_unread = False
    try:
        from agent_coord.server.push import unread_mail_frames

        has_unread = bool(unread_mail_frames(cn, desk, limit=1))
    except Exception:
        has_unread = False
    retry = bool(
        (pending > 0 or has_unread)
        and _retryable(status)
        and str((body or {}).get(FIELD) or "").strip()
    )
    _record_wake_fail(cn, desk, wake_id, status, err, retry=1 if retry else 0)
    if retry:
        _arm_retry(
            url, body, key=key, desk=desk, hint_id=hint_id, frame=frame,
            status=status, err=err, note=note, tag=tag,
            cn=cn, wake_id=wake_id,
        )
    return "error"
