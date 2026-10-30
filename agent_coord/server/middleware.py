"""Mill HTTP protocol (middleware). The only process that opens the book.

Sits on TLS/HTTP. Agents and humans speak this API. HTML pages are a visual
client of the same commands. Does not acquire product-line locks. Does not clock
in as a mill session. Coding agents do not serve_forever in a chat.

Security: door (private bind / LAN / VPN + HTTPS) for who can open a socket.
Look (GET standup) is the door. Writes: human badge+device, or mill session
token when mill commands are on HTTP. Never mill token in a browser. 3306 stays
on this host.
"""

from __future__ import annotations

import hashlib
import html
import re
import json
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from agent_coord.server.redact import err_text
from urllib.parse import parse_qs, urlparse

from agent_coord.const import (
    CONST_DESK,
    CONST_MAIL,
    CONST_OFFICE,
    CONST_TODO,
)
from agent_coord.helpers.errors import CoordError
from agent_coord.server.book import Book
from agent_coord.lib.observe import parse_roots

# Wall floor scope kinds (not name types): rows tagged with a roster, or rows by
# the desks on a roster. Renaming these scope tokens is a separate Wall change.
SCOPE_PROJECT = "project"
SCOPE_ROLE = "role"


def _stored(value) -> str:
    return str(value or "").strip()



_PKG = Path(__file__).resolve().parent.parent


def _note_wall_api(path: str, t0: float) -> None:
    """Park the office rollup. The request does not wait on the book (#220)."""
    try:
        from agent_coord.server.score_system import enqueue_wall

        enqueue_wall(path, (time.perf_counter() - t0) * 1000.0)
    except Exception:
        pass
WALL_UI_DIR = _PKG / "web" / "wall_ui"
WALL_UI_COMPONENTS = WALL_UI_DIR / "components"
WALL_UI_LIB = WALL_UI_DIR / "lib"
WALL_UI_DEFAULT = WALL_UI_DIR / "default"
BOARD_HTML = WALL_UI_DEFAULT / "board.html"
# Legacy path kept for any caller still pointing at static/; install syncs both.
STATIC_DIR = _PKG / "web" / "static"
_floor_lock = threading.Lock()
# stored_at, body, expire_at. expire_at None stays until the key changes.
_floor_cache: dict[str, tuple[float, bytes, float | None]] = {}
_floor_flight: dict[str, threading.Event] = {}
# Rail (station, project, role) and the big reads. The wall polls every 15s,
# so 30s covers that next poll and every browser open at the same time.
# Floor panes pass ttl=None and put a table version in the key (#220).
_FLOOR_TTL = 30.0
_FLOOR_CAP = 128


def cached_read(key: str, produce, ttl: float | None = _FLOOR_TTL) -> tuple[bytes, bool]:
    """One shared JSON body for this key.

    ttl is seconds. None keeps the body until the key changes. The default
    is 30s for readers other than the floor panes. Browsers that miss
    together wait on the single in-flight read. A failure is not stored.
    The map keeps the newest 128 keys.
    """
    while True:
        with _floor_lock:
            now = time.monotonic()
            hit = _floor_cache.get(key)
            if hit is not None and (hit[2] is None or now < hit[2]):
                return hit[1], True
            flight = _floor_flight.get(key)
            if flight is None:
                flight = threading.Event()
                _floor_flight[key] = flight
                leader = True
            else:
                leader = False
        if not leader:
            flight.wait()
            continue
        try:
            body = produce()
        except BaseException:
            with _floor_lock:
                if _floor_flight.get(key) is flight:
                    _floor_flight.pop(key, None)
            flight.set()
            raise
        with _floor_lock:
            now = time.monotonic()
            expire_at = None if ttl is None else now + float(ttl)
            _floor_cache[key] = (now, body, expire_at)
            if len(_floor_cache) > _FLOOR_CAP:
                expired = [
                    k for k, (_ts, _b, exp) in _floor_cache.items()
                    if exp is not None and time.monotonic() >= exp
                ]
                for k in expired:
                    _floor_cache.pop(k, None)
            while len(_floor_cache) > _FLOOR_CAP:
                oldest = min(_floor_cache, key=lambda k: _floor_cache[k][0])
                _floor_cache.pop(oldest, None)
            if _floor_flight.get(key) is flight:
                _floor_flight.pop(key, None)
        flight.set()
        return body, False


def _activity_cut(qs: dict, project: str) -> tuple[str, str] | None:
    """scope, id for one project, role, or station. None when the cut is unusable."""

    scope = (qs.get("scope") or [SCOPE_PROJECT])[0].strip().lower() or SCOPE_PROJECT
    if scope in ("station", "workstation", "ip"):
        scope = "lan"
    ident = (qs.get("id") or [""])[0].strip()
    if scope == SCOPE_PROJECT:
        return scope, _stored(ident or project)
    if scope == SCOPE_ROLE:
        return scope, _stored(ident)
    if scope == "lan" and ident:
        return scope, ident
    return None


def wall_ui_default_board() -> Path:
    """OOTB Wall HTML. Prefer wall_ui/default; fall back to static/board.html."""
    if BOARD_HTML.is_file():
        return BOARD_HTML
    legacy = STATIC_DIR / "board.html"
    return legacy


def wall_asset_id(path: Path | None = None) -> str:
    """Short content hash of the served Wall bundle (refresh-needed cue)."""
    p = path or wall_ui_default_board()
    try:
        raw = p.read_bytes()
    except OSError:
        return ""
    return hashlib.sha256(raw).hexdigest()[:16]


def wall_prefs_path() -> Path:
    """Office-local mill prefs JSON (Cut 6: office_default + per-desk)."""
    from agent_coord.install import office_dir

    return office_dir() / "wall_prefs.json"


def load_wall_prefs(*, desk: str | None = None) -> dict[str, Any]:
    """Cut 6 wire: resolve office_default + desk (desk wins) for Wall boot.

    Fail closed: missing/corrupt prefs -> pack defaults via resolve_prefs_doc({}).
    """
    from agent_coord.web.wall_logic.knobs import (
        mark_schema_migrated,
        migrate_wall_prefs,
        prefs_file_cut6,
        resolve_prefs_doc,
    )

    path = wall_prefs_path()
    doc: dict[str, Any] = {}
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                doc = raw
        except Exception:
            doc = {}
    out = resolve_prefs_doc(doc, desk=desk or None)
    if prefs_file_cut6(path) or int(out.get("version") or 0) >= 6:
        mark_schema_migrated(True)
        out["schema_migrated"] = True
    # keep a short note for humans glancing /api/wall-prefs
    out["note"] = "Cut 6 wire: office_default+desk (desk wins); knobs do not replace pack"
    return out


def save_wall_prefs_stub(data: dict[str, Any]) -> dict[str, Any]:
    """Write Cut 6 mill prefs (office_default / desks[desk]); returns load_wall_prefs."""
    from agent_coord.web.wall_logic.knobs import (
        CUT6_PREFS_VERSION,
        migrate_wall_prefs,
        sanitize_css_vars,
        sanitize_keyboard_overrides,
    )

    path = wall_prefs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    cur: dict[str, Any] = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                cur = loaded
        except Exception:
            cur = {}
    cur = migrate_wall_prefs(cur)
    desk = str(data.get("desk") or "").strip()

    def _fold_knobs(src: dict[str, Any], into: dict[str, Any]) -> dict[str, Any]:
        out = dict(into or {})
        # accept either nested prefs={} or flat knobs on payload
        blob = src.get("prefs") if isinstance(src.get("prefs"), dict) else src
        if not isinstance(blob, dict):
            return out
        for k in (
            "pane_order",
            "land_tab",
            "density",
            "css_vars",
            "chrome_flags",
            "mail_default_view",
            "score_default_filter",
            "pack_id",
            "keyboard_profile",
            "keyboard_overrides",
        ):
            if k in blob:
                out[k] = blob[k]
        if "css_vars" in out:
            out["css_vars"] = sanitize_css_vars(out.get("css_vars"))  # type: ignore[arg-type]
        if "keyboard_overrides" in out:
            out["keyboard_overrides"] = sanitize_keyboard_overrides(out.get("keyboard_overrides"))  # type: ignore[arg-type]
        return out

    if desk:
        desks = cur.get("desks") if isinstance(cur.get("desks"), dict) else {}
        row = desks.get(desk) if isinstance(desks.get(desk), dict) else {}
        row = _fold_knobs(data, row)
        if "pack" in data:
            # pack pointer may set pack_id
            pack = data.get("pack")
            if isinstance(pack, str) and pack:
                row["pack_id"] = pack
            elif isinstance(pack, dict) and pack.get("id"):
                row["pack_id"] = str(pack.get("id"))
        desks[desk] = row
        cur["desks"] = desks
    else:
        office = cur.get("office_default") if isinstance(cur.get("office_default"), dict) else {}
        office = _fold_knobs(data, office)
        if "office_default" in data and isinstance(data.get("office_default"), dict):
            office = _fold_knobs({"prefs": data["office_default"]}, office)
        if "pack" in data:
            pack = data.get("pack")
            if isinstance(pack, str) and pack:
                office["pack_id"] = pack
        if "settled_pack" in data and "pack_id" not in office:
            sp = data.get("settled_pack")
            if isinstance(sp, str) and sp:
                office["pack_id"] = sp
        cur["office_default"] = office
    cur["version"] = CUT6_PREFS_VERSION
    cur["cut6"] = True
    cur["prefs"] = None
    path.write_text(json.dumps(cur, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return load_wall_prefs(desk=desk or None)


def _office(**kw) -> Book:
    return Book(**kw)


_STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
}


_PIN_RE = re.compile(r"[A-Za-z0-9._-]{1,64}")
STATIC_CACHE_PINNED = "public, max-age=31536000, immutable"
STATIC_CACHE_SHORT = "public, max-age=60"
# The board page sits behind the door: browser cache only, keyed on the session cookie.
BOARD_CACHE = "private, max-age=60"

# Sent on every response. The Wall has one inline onload handler and inline
# style attributes, so script-src and style-src keep 'unsafe-inline' until
# those move into files; everything else is same-origin only.
WALL_CSP = (
    "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; "
    "form-action 'self'; frame-ancestors 'none'"
)
SECURITY_HEADERS = (
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "same-origin"),
    ("Content-Security-Policy", WALL_CSP),
)


def _static_cache_control(path_with_query: str, _ctype: str) -> str:
    """A ?v= pinned asset never changes at that URL, so cache it for a year.

    The page and unpinned files stay short (one minute, then an ETag recheck),
    so a new pin or an edited unpinned file is picked up (#712).
    """
    query = urlparse(path_with_query or "").query
    pins = parse_qs(query, keep_blank_values=True).get("v") or []
    if len(pins) == 1 and _PIN_RE.fullmatch(pins[0]):
        return STATIC_CACHE_PINNED
    return STATIC_CACHE_SHORT


def _static_roots() -> tuple[str, ...]:
    """Real directory prefixes a static file may be read from (see _safe_static)."""
    dirs = (WALL_UI_DIR, STATIC_DIR, _PKG.parent / "docs" / "protocol")
    return tuple(os.path.join(os.path.realpath(d), "") for d in dirs)


def _read_static(found: Path) -> bytes | None:
    """Read a file _safe_static found, only when it really sits under a static root."""
    real = os.path.realpath(found)
    if not real.startswith(_static_roots()):
        return None
    with open(real, "rb") as fh:
        return fh.read()


def _static_etag(body: bytes) -> str:
    return '"%s"' % hashlib.sha256(body).hexdigest()[:16]




def _safe_static(name: str) -> Path | None:
    """Serve static/, wall_ui/default/, wall_ui/components/, or wall_ui/lib/.

    Basename lookup (legacy) plus nested paths under wall_ui/default/ for pack
    domain modules (cut 5: mail/mail.js, score/score.js, floor/floor.js).
    """
    rel = str(name or "").replace("\\", "/").lstrip("/")
    if not rel or any(part in ("", ".", "..") for part in rel.split("/")):
        return None
    # Nested pack path under default (and components) - cut 5 domain folders
    if "/" in rel:
        # board.html href="lib/data.js" -> wall_ui/lib/data.js (not .../lib/lib/data.js)
        if rel.startswith("lib/"):
            under = rel[len("lib/") :]
            if under and ".." not in under.split("/"):
                cand = (WALL_UI_LIB / under).resolve()
                try:
                    if cand.is_file() and cand.relative_to(WALL_UI_LIB.resolve()):
                        return cand
                except ValueError:
                    pass
        for folder in (WALL_UI_DEFAULT, WALL_UI_COMPONENTS, WALL_UI_LIB, STATIC_DIR):
            cand = (folder / rel).resolve()
            try:
                cand.relative_to(folder.resolve())
            except ValueError:
                continue
            if cand.is_file():
                return cand
        return None
    base = Path(rel).name
    if not base or base in (".", ".."):
        return None
    for folder in (STATIC_DIR, WALL_UI_DEFAULT, WALL_UI_COMPONENTS, WALL_UI_LIB):
        cand = (folder / base).resolve()
        try:
            cand.relative_to(folder.resolve())
        except ValueError:
            continue
        if cand.is_file():
            return cand
    if base.lower() == "usecases.md":
        cand = (_PKG.parent / "docs" / "protocol" / "usecases.md").resolve()
        if cand.is_file():
            return cand
    return None


def _json(obj: Any) -> bytes:
    """Serialize JSON with top-level mill version stamp."""
    from agent_coord.server.mill_json import dumps_mill_bytes

    return dumps_mill_bytes(obj)


_DOING_ITEM = re.compile(r"(mail|todo|hold|score)-([1-9][0-9]{0,18})")


def _doing_read(path: str, qs: dict[str, list[str]]) -> tuple[int, Any]:
    """#818 GET /api/v1/doing and /api/v1/doing/history: the `mill connected`
    views, read-only, for the Wall (PR C). Behind the same door and on the same
    office book as every other Wall GET; the Wall computes nothing itself.

    /api/v1/doing takes exactly one of all=1, desk=D or project=R and returns
    the _desk_view list. /api/v1/doing/history takes desk=D and/or on=ITEM
    (mail-N, todo-N, hold-N, score-N), plus since= and page=, and returns
    {history, page} with ended_by. A refusal is 400 {"error"}.
    """
    from agent_coord.server.api.mill import rpc

    def one(key: str) -> str:
        return str((qs.get(key) or [""])[0] or "").strip()

    desk, project = one("desk"), one("project")
    try:
        if path == "/api/doing":
            every = one("all").lower() in ("1", "true", "yes")
            if int(every) + int(bool(desk)) + int(bool(project)) != 1:
                return 400, {"error": "GET /api/v1/doing requires one of ?all=1 or ?desk= or ?project="}
            body: dict[str, Any] = {"desk": desk, "project": project, "all": every}
            with _office() as c:
                return 200, rpc._h_session(c, body, project, None)
        on_raw = one("on")
        on = None
        if on_raw:
            hit = _DOING_ITEM.fullmatch(on_raw)
            if not hit:
                return 400, {"error": "GET /api/v1/doing/history: on= is mail-N, todo-N, hold-N or score-N"}
            on = (hit.group(1), int(hit.group(2)))
        if not desk and not on:
            return 400, {"error": "GET /api/v1/doing/history requires ?desk= or ?on= (or both)"}
        try:
            page = rpc._doing_page(one("page")) or 1
        except CoordError:
            return 400, {"error": f"GET /api/v1/doing/history: page= is 1 to {rpc.DOING_PAGE_MAX}"}
        body = {"desk": desk, "history": True, "since": one("since"), "page": page}
        with _office() as c:
            who = rpc._stored(desk) if desk else ""
            if who:
                from agent_coord.server.records import name as rec_name

                if rec_name.get(c._cn, who, CONST_DESK) is None:
                    return 400, {"error": f"connected: no desk {who[:64]}"}
            return 200, rpc._doing_history(c, body, who, on)
    except CoordError as e:
        return 400, {"error": err_text(e)}


_ERROR_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<title>{title}</title>
<style>
  html, body {{ margin: 0; min-height: 100%; background:
    radial-gradient(900px 420px at 8% -12%, rgba(228,181,106,.10), transparent 55%),
    #080a0d; color: #e8eef5;
    font-family: "Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif; }}
  body {{ display: flex; align-items: center; justify-content: center; padding: 1.5rem; }}
  main {{ max-width: 32rem; }}
  p.mark {{ display: flex; align-items: center; gap: .55rem; margin: 0 0 1rem;
    letter-spacing: .2em; color: #e4b56a; font-size: 14px; font-weight: 700; }}
  .mill-mark {{ width: 14px; height: 14px; border: 2px solid #e4b56a; border-radius: 50%;
    box-shadow: 0 0 10px rgba(228,181,106,.35); position: relative; }}
  .mill-mark::before {{ content: ""; position: absolute; inset: 2px;
    border: 2px solid #e4b56a; border-radius: 50%; border-right-color: transparent; }}
  h1 {{ font-size: 1.7rem; font-weight: 600; letter-spacing: 0; margin: 0 0 .6rem; }}
  p.detail {{ color: #8d99a8; margin: 0; line-height: 1.5; }}
</style>
</head>
<body>
<main>
  <p class="mark"><span class="mill-mark" aria-hidden="true"></span>THE MILL</p>
  <h1>{heading}</h1>
  <p class="detail">{detail}</p>
</main>
</body>
</html>
"""


def _html_error(heading: str, detail: str) -> bytes:
    page = _ERROR_PAGE.format(
        title=html.escape(heading),
        heading=html.escape(heading),
        detail=html.escape(detail),
    )
    return page.encode("utf-8")


def _wants_error_page(handler: BaseHTTPRequestHandler) -> bool:
    """A document navigation. API and asset requests keep a short body."""
    try:
        accept = (handler.headers.get("Accept") or "").lower()
    except Exception:
        return False
    path = urlparse(getattr(handler, "path", "") or "").path
    if path.startswith(("/api", "/mill", "/ws")):
        return False
    return "text/html" in accept



def _is_nest_board_path(path: str) -> bool:
    """True when Hub should serve Nest board HTML (SPA deep-link fallthrough).

    Exact: /, /board, /index.html, /welcome.
    Prefix families: /project, /station, /role (optional slug).
    Boundary-safe: /project matches; /projectfoo does not.
    Never SPA-fallthrough static-looking assets (stale relative mail/mail.js
    under /project/... must not return board HTML -> Unexpected token '<').
    Root /mail/*.js is served by static lookup, not this helper.
    """
    if path in ("/", "/board", "/index.html", "/welcome"):
        return True
    # Asset suffixes never get Nest board HTML (fall through to static/404).
    suf = Path(path).suffix.lower()
    if suf in {
        ".js",
        ".css",
        ".map",
        ".svg",
        ".png",
        ".ico",
        ".woff",
        ".woff2",
        ".json",
        ".txt",
        ".md",
    }:
        return False
    for prefix in ("/project", "/station", "/role"):
        if path == prefix or path.startswith(prefix + "/"):
            return True
    return False


def _send_not_found(handler: BaseHTTPRequestHandler, *, closed: bool) -> None:
    if _wants_error_page(handler):
        if closed:
            heading = "This address is not open"
            detail = "Open the invite link you were given."
        else:
            heading = "That page is not here"
            detail = "The wall has no page at this address."
        handler._send(404, _html_error(heading, detail), "text/html; charset=utf-8")
        return
    handler._send(404, b"not found\n", "text/plain; charset=utf-8")


def error_id(exc: BaseException, where: str) -> str:
    """Log the exception under a fresh opaque id and return the id for the client."""
    eid = secrets.token_hex(6)
    try:
        from agent_coord.server.push import api_log

        api_log(f"500 error_id={eid} {where} {type(exc).__name__}: {exc}")
    except Exception:
        pass
    return eid


_SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
_CRED_HEADERS = ("Authorization", "PRIVATE-TOKEN", "X-Mill-Invite")


def _has_session_cookie(headers) -> bool:
    from agent_coord.server.glance import GLANCE_COOKIE

    for part in (headers.get("Cookie") or "").split(";"):
        name = part.strip().partition("=")[0].strip()
        if name == GLANCE_COOKIE or name.startswith("factory-door"):
            return True
    return False


def _host_port(host: str, scheme: str) -> tuple[str, int] | None:
    from urllib.parse import urlsplit

    try:
        parts = urlsplit("//" + (host or "").strip())
        name = (parts.hostname or "").lower()
        port = parts.port or (443 if scheme == "https" else 80)
    except ValueError:
        return None
    return (name, port) if name else None


def origin_matches(origin: str, headers, peer: str) -> bool:
    """True when Origin names this wall: the Host header, or X-Forwarded-Host and
    X-Forwarded-Proto when the TCP peer is a trusted proxy (allow.trusted_proxies).
    The installed edge keeps Host and sends no proto, so the port defaults from
    the Origin's own scheme."""
    from urllib.parse import urlsplit

    from agent_coord.server.allow import _in_rules, trusted_proxies

    try:
        want = urlsplit((origin or "").strip())
        o_scheme = (want.scheme or "").lower()
        o_host = (want.hostname or "").lower()
        o_port = want.port or (443 if o_scheme == "https" else 80)
    except ValueError:
        return False
    if o_scheme not in ("http", "https") or not o_host:
        return False
    host = (headers.get("Host") or "").strip()
    proto = ""
    if _in_rules(peer, trusted_proxies()):
        host = (headers.get("X-Forwarded-Host") or "").split(",")[0].strip() or host
        proto = (headers.get("X-Forwarded-Proto") or "").split(",")[0].strip().lower()
    if proto and proto != o_scheme:
        return False
    got = _host_port(host, proto or o_scheme)
    return got == (o_host, o_port)


def cookie_write_refusal(command: str, headers, peer: str) -> tuple[int, str]:
    """(status, reason) when a cookie-authenticated write is refused, else (0, "").

    Only a write (any method but GET, HEAD, OPTIONS) that carries a door or
    glance session cookie and no credential header is checked. It must be
    application/json (a cross-origin page cannot send that without a CORS
    preflight, which the wall never grants) and same-origin: Sec-Fetch-Site
    same-origin, an Origin that matches the wall, or the X-Mill-Wall header.
    """
    if (command or "").upper() in _SAFE_METHODS or not _has_session_cookie(headers):
        return 0, ""
    if any((headers.get(h) or "").strip() for h in _CRED_HEADERS):
        return 0, ""
    ctype = (headers.get("Content-Type") or "").split(";")[0].strip().lower()
    if ctype != "application/json":
        return 415, "a write with the session cookie must be Content-Type application/json"
    site = (headers.get("Sec-Fetch-Site") or "").strip().lower()
    if site in ("cross-site", "same-site"):
        return 403, "cross-origin write refused"
    if site == "same-origin":
        return 0, ""
    origin = (headers.get("Origin") or "").strip()
    if origin:
        return (0, "") if origin_matches(origin, headers, peer) else (403, "cross-origin write refused")
    if (headers.get("X-Mill-Wall") or "").strip():
        return 0, ""
    return 403, "a write with the session cookie needs a same-origin Origin or X-Mill-Wall"


def _refuse_cookie_write(handler: BaseHTTPRequestHandler) -> bool:
    """Answer a refused cookie-authenticated write (card 749); True when refused."""
    peer = str((getattr(handler, "client_address", None) or ("", 0))[0] or "")
    code, why = cookie_write_refusal(getattr(handler, "command", "") or "", handler.headers, peer)
    if not code:
        return False
    handler._send(code, _json({"error": why}), "application/json; charset=utf-8")
    return True


def _fail_closed(handler: BaseHTTPRequestHandler, exc: BaseException) -> None:
    """One bad route must fail that request closed - never kill the 18765 listener.

    The client gets a fixed message and an error id; the text stays in the server log.
    """
    try:
        where = f"{getattr(handler, 'command', '') or ''} {urlparse(getattr(handler, 'path', '') or '').path}"
        body = _json({"error": "mill API error", "error_id": error_id(exc, where.strip())})
        if not getattr(handler, "headers_sent", False) and not handler.wfile.closed:
            handler.send_response(500)
            handler.send_header("Content-Type", "application/json; charset=utf-8")
            handler.send_header("Content-Length", str(len(body)))
            handler.send_header("Cache-Control", "no-store")
            for key, val in SECURITY_HEADERS:
                handler.send_header(key, val)
            handler.end_headers()
            handler.wfile.write(body)
    except Exception:
        pass


def _score_miss(last, target) -> bool:
    """Same rule as the Wall score chip: off target, not a blank or a pass."""
    text = str(last or "").strip().lower()
    if not text or any(w in text for w in ("not run", "leftover", "shipped", "stay", "none")):
        return False
    if any(w in text for w in ("fail", "starve", "miss")):
        return True

    def numish(s):
        raw = str(s or "").replace("*", "").strip()
        token = ""
        for ch in raw:
            if ch.isdigit() or ch in ".-":
                token += ch
            elif token:
                break
        try:
            return float(token) if token else None
        except ValueError:
            return None

    ln, tn = numish(last), numish(target)
    if ln is None or tn is None:
        return False
    if tn == 0:
        return ln != 0
    return ln < tn


def _scope_strip(cn, kind: str, label: str) -> dict:
    """Counts for one project or one role. No mail bodies, no full floor."""

    kind_sql = SCOPE_PROJECT if kind == SCOPE_PROJECT else SCOPE_ROLE
    empty = {
        "here": 0, "away": 0, "holds": 0, "unassigned": 0, "unread": 0, "misses": 0,
        "here_names": [], "away_names": [], "holds_rows": [], "unread_by": [], "miss_rows": [],
    }
    cur = cn.cursor()
    try:
        cur.execute(
            "SELECT id FROM name WHERE deleted IS NULL AND type=%s AND name=%s",
            (kind_sql, label),
        )
        found = cur.fetchone()
        if not found:
            return empty
        aid = int(found[0])
        cur.execute(
            "SELECT d.name,"
            " (j.time_connect IS NOT NULL AND (j.time_disconnect IS NULL"
            "  OR j.time_connect >= j.time_disconnect)) AS connected"
            " FROM member m"
            " JOIN name d ON d.id = m.desk_id AND d.deleted IS NULL"
            " LEFT JOIN seat j ON j.desk_id = d.id"
            " WHERE m.name_id=%s ORDER BY d.name",
            (aid,),
        )
        here_names, away_names = [], []
        for name, on in cur.fetchall():
            label_name = _stored(str(name or ""))
            if on:
                here_names.append(label_name)
            else:
                away_names.append(label_name)
        cur.execute(
            "SELECT r.name, d.name FROM hold h"
            " JOIN name r ON r.id = h.resource_id"
            " JOIN name d ON d.id = h.desk_id"
            " WHERE h.desk_id IS NOT NULL"
            " AND h.updated < mill_now() - INTERVAL 1 DAY"
            " ORDER BY h.updated LIMIT 12",
        )
        holds_rows = [
            {"resource": _stored(str(r[0] or "")), "desk": _stored(str(r[1] or ""))}
            for r in cur.fetchall()
        ]
        cur.execute(
            "SELECT COUNT(*) FROM hold WHERE desk_id IS NOT NULL"
            " AND updated < mill_now() - INTERVAL 1 DAY",
        )
        holds = int((cur.fetchone() or [0])[0] or 0)
        cur.execute(
            "SELECT COUNT(*) FROM todo WHERE roster_id=%s"
            " AND status='open' AND assigned_id IS NULL",
            (aid,),
        )
        unassigned = int((cur.fetchone() or [0])[0] or 0)
        cur.execute(
            "SELECT ANY_VALUE(d.name), COUNT(*) FROM mail_to t"
            " JOIN name d ON d.id = t.desk_id"
            " JOIN mail m ON m.type = 'mail' AND m.id = t.id"
            " JOIN activity a ON a.type = 'mail' AND a.id = m.id"
            " WHERE t.opened IS NULL"
            " AND (m.roster_id=%s OR a.roster_id=%s)"
            " GROUP BY d.name ORDER BY d.name",
            (aid, aid),
        )
        unread_by = [
            {"desk": _stored(str(r[0] or "")), "n": int(r[1] or 0)}
            for r in cur.fetchall()
        ]
        # A roster-owned score has no desk (beta 0.8.0): it shows under the roster's name.
        cur.execute(
            "SELECT COALESCE(d.name, r.name), s.kpi, s.value, s.target FROM score s"
            " LEFT JOIN name d ON d.id = s.desk_id"
            " JOIN name r ON r.id = s.roster_id"
            " WHERE s.roster_id=%s",
            (aid,),
        )
        miss_rows = []
        for dname, kname, val, tgt in cur.fetchall():
            if _score_miss(val, tgt):
                miss_rows.append({
                    "desk": _stored(str(dname or "")),
                    "kpi": _stored(str(kname or "")),
                })
        return {
            "here": len(here_names),
            "away": len(away_names),
            "holds": holds,
            "unassigned": unassigned,
            "unread": sum(r["n"] for r in unread_by),
            "misses": len(miss_rows),
            "here_names": here_names,
            "away_names": away_names,
            "holds_rows": holds_rows,
            "unread_by": unread_by,
            "miss_rows": miss_rows,
        }
    finally:
        cur.close()


def _recent(raw):
    if raw in (None, ""):
        return None
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


_RECENT_ACTIVITY_EXPR = (
    " IF(ra.id IS NULL, NULL, JSON_OBJECT("
    " 'type', ra.type, 'id', ra.id,"
    " 'roster_id', ra.roster_id,"
    " 'roster', aff.name, 'roster_type', aff.type,"
    " 'thing', CASE ra.type"
    "   WHEN 'mail' THEN LEFT(ml.body, 80)"
    "   WHEN 'todo' THEN LEFT(td.body, 80)"
    "   WHEN 'hold' THEN hr.name"
    "   WHEN 'score' THEN sc.kpi"
    "   WHEN 'doing' THEN jd.name"
    "   ELSE NULL END))"
)

_RECENT_ACTIVITY_JOINS = (
    " LEFT JOIN LATERAL ("
    "   SELECT type, id, roster_id, updated FROM activity USE INDEX (idx_desk_updated)"
    "   WHERE desk_id = {desk}"
    "   ORDER BY updated DESC LIMIT 1"
    " ) ra ON TRUE"
    " LEFT JOIN name aff ON aff.id = ra.roster_id"
    " LEFT JOIN mail ml ON ra.type = 'mail' AND ml.id = ra.id"
    " LEFT JOIN todo td ON ra.type = 'todo' AND td.id = ra.id"
    " LEFT JOIN hold ho ON ra.type = 'hold' AND ho.id = ra.id"
    " LEFT JOIN name hr ON hr.id = ho.resource_id"
    " LEFT JOIN score sc ON ra.type = 'score' AND sc.id = ra.id"
    " LEFT JOIN doing js ON ra.type = 'doing' AND js.id = ra.id"
    " LEFT JOIN name jd ON jd.id = js.desk_id"
)


def _page_rows(cn, tab: str, *, scope: str = "", desk: str = "", project: str = "", role_name: str = "", lan: str | None = None) -> dict:
    """Rows for one strip count and one point of view. Capped. No full bodies."""

    cur = cn.cursor()
    try:
        affil = None
        ids: list[int] = []
        if project or role_name:
            kind_sql = SCOPE_PROJECT if project else SCOPE_ROLE
            cur.execute(
                "SELECT id FROM name WHERE deleted IS NULL AND type=%s AND name=%s",
                (kind_sql, project or role_name),
            )
            found = cur.fetchone()
            if not found:
                return {"tab": tab, "rows": []}
            affil = int(found[0])
        else:
            where = (
                "n.deleted IS NULL AND n.type = 'desk' AND ("
                " (j.time_connect IS NOT NULL AND (j.time_disconnect IS NULL"
                "  OR j.time_connect >= j.time_disconnect))"
                " OR (j.time_disconnect IS NOT NULL"
                "  AND j.time_disconnect >= mill_now() - INTERVAL 1 DAY"
                "  AND (j.time_connect IS NULL OR j.time_disconnect > j.time_connect))"
                ")"
            )
            params: list = []
            if desk:
                where += " AND n.name=%s"
                params.append(desk)
            elif lan is not None:
                if lan:
                    where += " AND j.lan_ip=%s"
                    params.append(lan)
                else:
                    where += " AND (j.lan_ip IS NULL OR j.lan_ip='')"
            elif scope != "mine":
                return {"tab": tab, "rows": []}
            cur.execute(
                "SELECT n.id FROM name n JOIN seat j ON j.desk_id=n.id WHERE " + where,
                tuple(params),
            )
            ids = [int(r[0]) for r in cur.fetchall() if r and r[0]]
            if not ids:
                return {"tab": tab, "rows": []}
        marks = ",".join(["%s"] * len(ids)) if ids else ""
        rows: list[dict] = []
        if tab == "here" and ids:
            cur.execute(
                "SELECT n.name, (SELECT g.text FROM doing g WHERE g.desk_id = j.desk_id ORDER BY g.created DESC, g.id DESC LIMIT 1),"
                " (j.time_connect IS NOT NULL AND (j.time_disconnect IS NULL"
                "  OR j.time_connect >= j.time_disconnect)) AS connected,"
                + _RECENT_ACTIVITY_EXPR
                + " FROM name n JOIN seat j ON j.desk_id=n.id"
                + _RECENT_ACTIVITY_JOINS.format(desk="n.id")
                + " WHERE n.id IN (" + marks + ") ORDER BY connected DESC, n.name LIMIT 40",
                tuple(ids),
            )
            rows = [
                {
                    "desk": _stored(str(r[0] or "")),
                    "doing": str(r[1] or ""),
                    "connected": bool(r[2]),
                    "recent_activity": _recent(r[3]),
                }
                for r in cur.fetchall()
            ]
        elif tab == "here" and affil:
            cur.execute(
                "SELECT d.name, (SELECT g.text FROM doing g WHERE g.desk_id = j.desk_id ORDER BY g.created DESC, g.id DESC LIMIT 1),"
                " (j.time_connect IS NOT NULL AND (j.time_disconnect IS NULL"
                "  OR j.time_connect >= j.time_disconnect)) AS connected,"
                + _RECENT_ACTIVITY_EXPR
                + " FROM member m"
                " JOIN name d ON d.id=m.desk_id AND d.deleted IS NULL"
                " LEFT JOIN seat j ON j.desk_id=d.id"
                + _RECENT_ACTIVITY_JOINS.format(desk="d.id")
                + " WHERE m.name_id=%s ORDER BY connected DESC, d.name LIMIT 40",
                (affil,),
            )
            rows = [
                {
                    "desk": _stored(str(r[0] or "")),
                    "doing": str(r[1] or ""),
                    "connected": bool(r[2]),
                    "recent_activity": _recent(r[3]),
                }
                for r in cur.fetchall()
            ]
        elif tab in ("unread",) and ids:
            cur.execute(
                "SELECT src.name, dst.name, LEFT(m.body, 80),"
                " TIMESTAMPDIFF(HOUR, t.created, mill_now())"
                " FROM mail_to t"
                " JOIN mail m ON m.id=t.id"
                " JOIN name dst ON dst.id=t.desk_id"
                " JOIN name src ON src.id=m.desk_id"
                " WHERE t.opened IS NULL AND t.desk_id IN (" + marks + ")"
                " ORDER BY t.created LIMIT 40",
                tuple(ids),
            )
            rows = [
                {"from": _stored(str(r[0] or "")), "to": _stored(str(r[1] or "")),
                 "text": str(r[2] or ""), "age": int(r[3] or 0)}
                for r in cur.fetchall()
            ]
        elif tab == "unread" and affil:
            cur.execute(
                "SELECT ANY_VALUE(d.name), COUNT(*), TIMESTAMPDIFF(HOUR, MIN(t.created), mill_now())"
                " FROM mail_to t JOIN name d ON d.id=t.desk_id"
                " JOIN mail m ON m.type = 'mail' AND m.id = t.id"
                " JOIN activity a ON a.type = 'mail' AND a.id = m.id"
                " WHERE t.opened IS NULL"
                " AND (m.roster_id=%s OR a.roster_id=%s)"
                " GROUP BY d.name ORDER BY COUNT(*) DESC LIMIT 40",
                (affil, affil),
            )
            rows = [
                {"to": _stored(str(r[0] or "")), "n": int(r[1] or 0), "age": int(r[2] or 0)}
                for r in cur.fetchall()
            ]
        elif tab == "claimed" and ids:
            cur.execute(
                "SELECT t.status, LEFT(t.body, 180), d.name, a.name,"
                " TIMESTAMPDIFF(HOUR, t.updated, mill_now())"
                " FROM todo t"
                " JOIN name d ON d.id=t.assigned_id"
                " JOIN name a ON a.id=t.roster_id"
                " WHERE t.status='claimed' AND t.assigned_id IN (" + marks + ")"
                " ORDER BY t.updated LIMIT 40",
                tuple(ids),
            )
            rows = [
                {"status": str(r[0] or ""), "title": _todo_title(r[1]),
                 "desk": _stored(str(r[2] or "")), "project": _stored(str(r[3] or "")),
                 "age": int(r[4] or 0)}
                for r in cur.fetchall()
            ]
        elif tab == "unassigned" and affil:
            cur.execute(
                "SELECT LEFT(t.body, 180), a.name, TIMESTAMPDIFF(HOUR, t.updated, mill_now())"
                " FROM todo t JOIN name a ON a.id=t.roster_id"
                " WHERE t.roster_id=%s AND t.status='open' AND t.assigned_id IS NULL"
                " ORDER BY t.updated LIMIT 40",
                (affil,),
            )
            rows = [
                {"status": "open", "title": _todo_title(r[0]),
                 "project": _stored(str(r[1] or "")), "age": int(r[2] or 0)}
                for r in cur.fetchall()
            ]
        elif tab == "holds" and ids:
            cur.execute(
                "SELECT r.name, d.name, an.name, TIMESTAMPDIFF(HOUR, h.updated, mill_now())"
                " FROM hold h"
                " JOIN name r ON r.id=h.resource_id"
                " JOIN name d ON d.id=h.desk_id"
                " JOIN activity act ON act.type='hold' AND act.id=h.id"
                " JOIN name an ON an.id=act.roster_id"
                " WHERE h.desk_id IN (" + marks + ")"
                " ORDER BY h.updated LIMIT 40",
                tuple(ids),
            )
            rows = [
                {"resource": _stored(str(r[0] or "")), "desk": _stored(str(r[1] or "")),
                 "project": _stored(str(r[2] or "")), "age": int(r[3] or 0)}
                for r in cur.fetchall()
            ]
        elif tab == "holds" and affil:
            cur.execute(
                "SELECT r.name, d.name, TIMESTAMPDIFF(HOUR, h.updated, mill_now())"
                " FROM hold h"
                " JOIN name r ON r.id=h.resource_id"
                " JOIN name d ON d.id=h.desk_id"
                " WHERE h.desk_id IS NOT NULL"
                " AND h.updated < mill_now() - INTERVAL 1 DAY"
                " ORDER BY h.updated LIMIT 40",
            )
            rows = [
                {"resource": _stored(str(r[0] or "")), "desk": _stored(str(r[1] or "")),
                 "age": int(r[2] or 0)}
                for r in cur.fetchall()
            ]
        elif tab == "misses":
            sql = (
                "SELECT COALESCE(d.name, r.name), s.kpi, s.value, s.target FROM score s"
                " LEFT JOIN name d ON d.id=s.desk_id"
                " JOIN name r ON r.id=s.roster_id WHERE "
            )
            if affil:
                cur.execute(sql + "s.roster_id=%s LIMIT 80", (affil,))
            else:
                cur.execute(sql + "s.desk_id IN (" + marks + ") LIMIT 80", tuple(ids))
            for dname, kname, val, tgt in cur.fetchall():
                if not _score_miss(val, tgt):
                    continue
                rows.append({
                    "desk": _stored(str(dname or "")),
                    "kpi": _stored(str(kname or "")),
                    "value": str(val or ""),
                    "target": str(tgt or ""),
                })
                if len(rows) >= 40:
                    break
        return {"tab": tab, "rows": rows}
    finally:
        cur.close()


def _todo_title(body) -> str:
    from agent_coord.server.records.todo import unpack

    raw = str(body or "")
    try:
        text = str(unpack(raw, "").get("detail") or "")
    except Exception:
        text = raw
    return " ".join(text.split())[:80]


def make_handler(roots: dict[str, Path], *, api_only: bool = False):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:
            return

        def _send(
            self,
            code: int,
            body: bytes,
            ctype: str,
            extra: list[tuple[str, str]] | None = None,
        ) -> None:
            from agent_coord.server.howto import API_VERSION

            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            extra = list(getattr(self, "_door_extra", []) or []) + list(extra or [])
            if not any(str(k).lower() == "cache-control" for k, _ in extra):
                extra.append(("Cache-Control", "no-store"))
            self.send_header("X-Mill-Api", API_VERSION)
            try:
                from agent_coord.install.packver import package_version

                self.send_header("X-Mill-Version", package_version())
            except Exception:
                pass
            have = {str(k).lower() for k, _ in extra}
            extra.extend((k, v) for k, v in SECURITY_HEADERS if k.lower() not in have)
            for key, val in extra:
                self.send_header(key, val)
            self.end_headers()
            if body:
                self.wfile.write(body)

        def _send_health(self) -> None:
            """200 when the book answers, 503 when it does not. No door, no secrets (#144)."""
            from agent_coord.server.records.db import book_ping
            from agent_coord.server.records.driver import cached

            if book_ping():
                from agent_coord.server.records.db import book_sql_state

                # #614: a book left on another pack's SQL is not healthy; name the fix.
                st = book_sql_state()
                if not st.get("ok"):
                    msg = "book SQL is not this pack's (book %s, pack %s)" % (
                        st.get("book") or "none",
                        st.get("pack") or "unknown",
                    )
                    self._send(
                        503,
                        json.dumps({"ok": False, "error": msg, "fix": st.get("fix")}).encode("ascii"),
                        "application/json",
                    )
                    return
                path = "c" if cached().get("path") == "c" else "pure"
                self._send(200, b'{"ok":true,"db_driver":"' + path.encode() + b'"}', "application/json")
                return
            self._send(
                503,
                b'{"ok":false,"error":"book unavailable"}',
                "application/json",
            )

        def _door_ok(self) -> tuple[bool, str, list[tuple[str, str]]]:
            from agent_coord.server.admin.door import (
                check,
                invite_from_request,
                match_key,
                mode,
                set_cookie_header,
                set_key_cookie_header,
            )

            token = invite_from_request(self.path, self.headers)
            self._door_extra = []
            self._invite_key_id = ""
            def seat_opens() -> bool:
                # A pre-provisioned seat opens only the CA fetch and its own
                # one-shot join; it is not a door invite for anything else.
                from agent_coord.server.admin.seats import seat_known

                path_only = urlparse(self.path).path
                cmd = (self.command or "").upper()
                if cmd == "GET" and path_only in ("/ca.crt", "/api/ca.crt"):
                    return seat_known(token)
                if cmd == "POST":
                    from agent_coord.client.outbound import (
                        is_mill_command_path,
                        parse_path,
                    )

                    if is_mill_command_path(path_only) and (parse_path(path_only) or "") == "join":
                        return seat_known(token)
                return False

            m = mode()
            if m in ("directory", "iam"):
                from urllib.parse import urlparse as _urlparse

                from agent_coord.server.admin.human import agent_call

                if agent_call(_urlparse(self.path).path):
                    return True, token, []
                if not check(token):
                    if seat_opens():
                        return True, "", []
                    return False, token, []
                extra: list[tuple[str, str]] = []
                if token:
                    extra.append(("Set-Cookie", set_cookie_header(token)))
                self._door_extra = extra
                return True, token, extra
            if m != "invite":
                return True, token, []
            if not check(token):
                if seat_opens():
                    return True, "", []
                return False, token, []
            extra = []
            if token:
                extra.append(("Set-Cookie", set_cookie_header(token)))
                row = match_key(token)
                if row and row.get("key_id"):
                    self._invite_key_id = str(row["key_id"])
                    extra.append(("Set-Cookie", set_key_cookie_header(self._invite_key_id)))
            self._door_extra = extra
            return True, token, extra

        def do_GET(self) -> None:  # noqa: N802
            t0 = time.perf_counter()
            try:
                if _refuse_cookie_write(self):
                    return
                self._do_GET_inner()
            except Exception as _route_exc:
                _fail_closed(self, _route_exc)
            finally:
                _note_wall_api(self.path, t0)

        def _do_GET_inner(self) -> None:
            from agent_coord.server.admin.door import (
                board_signout,
                clear_session_headers,
                mode,
                signout_href,
                strip_invite_query,
            )

            path_only = urlparse(self.path).path
            # /health only. /api/health would be scored as a wall route and open the book.
            if path_only == "/health":
                self._send_health()
                return

            if path_only == "/mill/signout":
                loc = signout_href() or "/"
                extra_out: list[tuple[str, str]] = [("Location", loc)]
                if mode() in ("directory", "iam"):
                    extra_out.extend(clear_session_headers())
                self._send(302, b"", "text/plain; charset=utf-8", extra_out)
                return

            allowed, token, extra = self._door_ok()
            if not allowed:
                icon = urlparse(self.path).path
                if icon == "/mill/oidc/callback":
                    from urllib.parse import parse_qs as _parse_qs

                    from agent_coord.server.admin.door import (
                        clear_oidc_cookie_header,
                        complete_login,
                        set_cookie_header,
                    )

                    query = _parse_qs(urlparse(self.path).query)
                    code = ((query.get("code") or [""])[0] or "").strip()
                    state = ((query.get("state") or [""])[0] or "").strip()
                    got = complete_login(code, state, self.headers.get("Cookie") or "")
                    if got:
                        from agent_coord.server.admin.human import seat

                        bearer = seat(got)
                        if bearer:
                            self._send(
                                302,
                                b"",
                                "text/plain; charset=utf-8",
                                [
                                    ("Location", "/"),
                                    ("Set-Cookie", set_cookie_header(bearer)),
                                    ("Set-Cookie", clear_oidc_cookie_header()),
                                ],
                            )
                            return
                if _is_nest_board_path(icon) and _wants_error_page(self):
                    from agent_coord.server.admin.door import login_redirect

                    loc, login_cookie = login_redirect()
                    if loc:
                        self._send(
                            302,
                            b"",
                            "text/plain; charset=utf-8",
                            [("Location", loc), ("Set-Cookie", login_cookie)],
                        )
                        return
                if icon in ("/favicon.svg", "/favicon.ico"):
                    found = _safe_static("favicon.svg")
                    if found is not None:
                        self._send(200, found.read_bytes(), "image/svg+xml")
                        return
                _send_not_found(self, closed=True)
                return
            parsed = urlparse(self.path)
            path = parsed.path
            if path.startswith("/api/v1/"):
                path = "/api/" + path[len("/api/v1/") :]
            qs = parse_qs(parsed.query)
            if token and qs.get("invite") and _is_nest_board_path(path):
                loc = strip_invite_query(self.path)
                extra = extra + [("Location", loc or "/")]
                self._send(302, b"", "text/plain; charset=utf-8", extra)
                return
            if _is_nest_board_path(path):
                if api_only and mode() != "invite":
                    if _wants_error_page(self):
                        self._send(
                            404,
                            _html_error(
                                "API only",
                                "This port serves the mill API. The board is on the wall.",
                            ),
                            "text/html; charset=utf-8",
                        )
                    else:
                        self._send(
                            404,
                            b"api only; mill-wall --api-only (nginx serves the board)\n",
                            "text/plain; charset=utf-8",
                        )
                    return
                board = wall_ui_default_board()
                html_txt = board_signout(board.read_text(encoding="utf-8"))
                aid = wall_asset_id(board)
                if 'name="wall-asset-id"' in html_txt:
                    html_txt = re.sub(
                        r'(<meta\s+name="wall-asset-id"\s+content=")[^"]*(")',
                        lambda m, _aid=aid: m.group(1) + _aid + m.group(2),
                        html_txt,
                        count=1,
                    )
                else:
                    html_txt = html_txt.replace(
                        "<head>",
                        '<head>\n  <meta name="wall-asset-id" content="%s">' % aid,
                        1,
                    )
                shown = 'class="wall-signout" data-signout="on"' in html_txt
                etag = '"%s%s"' % (aid or "0", "-so" if shown else "")
                inm = (self.headers.get("If-None-Match") or "").strip()
                if inm and inm == etag:
                    self._send(
                        304,
                        b"",
                        "text/html; charset=utf-8",
                        extra=[
                            ("Cache-Control", BOARD_CACHE),
                            ("Vary", "Cookie"),
                            ("ETag", etag),
                        ],
                    )
                    return
                self._send(
                    200,
                    html_txt.encode("utf-8"),
                    "text/html; charset=utf-8",
                    extra=[
                        ("Cache-Control", BOARD_CACHE),
                        ("Vary", "Cookie"),
                        ("ETag", etag),
                    ],
                )
                return
            if not api_only and not path.startswith("/api/"):
                rel = path.lstrip("/")
                if rel:
                    found = _safe_static(rel)
                    body = _read_static(found) if found is not None else None
                    if found is not None and body is not None:
                        ctype = _STATIC_TYPES.get(found.suffix.lower(), "application/octet-stream")
                        etag = _static_etag(body)
                        extra = [
                            ("Cache-Control", _static_cache_control(self.path, ctype)),
                            ("ETag", etag),
                        ]
                        inm = (self.headers.get("If-None-Match") or "").strip()
                        if inm and etag in [t.strip() for t in inm.split(",")]:
                            self._send(304, b"", ctype, extra=extra)
                            return
                        self._send(200, body, ctype, extra=extra)
                        return
            if path in (
                "/mill/v1/version",
                "/api/mill/version",
                "/api/version",
                "/version.json",
            ):
                from agent_coord.install.packver import package_version_info

                self._send(
                    200,
                    _json(package_version_info()),
                    "application/json; charset=utf-8",
                )
                return
            if path in ("/ca.crt", "/api/ca.crt"):
                from agent_coord.install import mill_ca_crt

                ca = mill_ca_crt()
                if ca.is_file():
                    self._send(200, ca.read_bytes(), "application/x-pem-file")
                else:
                    self._send(404, b"no mill ca\n", "text/plain; charset=utf-8")
                return
            if path == "/api/pov":
                qs = parse_qs(urlparse(self.path).query)
                part = ((qs.get("part") or [""])[0] or "").strip().lower()
                pov_type = {"desks": "desk", "rosters": "roster"}.get(part)
                if not pov_type:
                    self._send(
                        400,
                        _json({"error": "GET /api/pov requires ?part=desks|rosters"}),
                        "application/json; charset=utf-8",
                    )
                    return
                from agent_coord.server.allow import workstation_ip

                pov_ip = ""
                if part == "desks":
                    pov_ip = workstation_ip((self.client_address or ("", 0))[0]) or ""
                pov_key = "pov|" + part + "|" + pov_ip

                def produce() -> bytes:
                    with _office() as c:

                        cur = c._cn.cursor()
                        try:
                            if part == "desks":
                                cur.execute(
                                    "SELECT n.name,"
                                    " (j.time_connect IS NOT NULL AND (j.time_disconnect IS NULL"
                                    " OR j.time_connect >= j.time_disconnect)) AS connected,"
                                    " j.lan_ip, j.updated,"
                                    + _RECENT_ACTIVITY_EXPR
                                    + " FROM name n"
                                    " JOIN seat j ON j.desk_id = n.id"
                                    + _RECENT_ACTIVITY_JOINS.format(desk="n.id")
                                    + " WHERE n.deleted IS NULL AND n.type = %s"
                                    " AND ("
                                    "   (j.time_connect IS NOT NULL AND (j.time_disconnect IS NULL"
                                    "    OR j.time_connect >= j.time_disconnect))"
                                    "   OR (j.time_disconnect IS NOT NULL"
                                    "    AND j.time_disconnect >= mill_now() - INTERVAL 1 DAY"
                                    "    AND (j.time_connect IS NULL OR j.time_disconnect > j.time_connect))"
                                    " )"
                                    " ORDER BY (j.lan_ip IS NULL), j.lan_ip, j.updated DESC, n.name",
                                    (pov_type,),
                                )
                                rows = []
                                for r in cur.fetchall():
                                    if not r or not r[0]:
                                        continue
                                    rows.append({
                                        "name": _stored(str(r[0] or "")),
                                        "connected": bool(r[1]),
                                        "lan_ip": str(r[2] or ""),
                                        "updated": str(r[3] or ""),
                                        "recent_activity": _recent(r[4]),
                                    })
                            else:
                                cur.execute(
                                    "SELECT ANY_VALUE(n.name), COUNT(d.id) AS desks FROM name n"
                                    " LEFT JOIN member m ON m.name_id=n.id"
                                    " LEFT JOIN name d ON d.id=m.desk_id"
                                    "  AND d.deleted IS NULL AND d.type = 'desk'"
                                    " WHERE n.deleted IS NULL AND n.type = %s"
                                    " GROUP BY n.id, n.name"
                                    " ORDER BY n.name",
                                    (pov_type,),
                                )
                                rows = [
                                    {"name": _stored(str(r[0] or "")), "desks": int(r[1] or 0)}
                                    for r in cur.fetchall() if r and r[0]
                                ]
                        finally:
                            cur.close()
                        if part == "rosters":
                            rows.sort(key=lambda rec: (rec["name"] != CONST_OFFICE, rec["name"].lower()))
                        if part == "desks":
                            from agent_coord.server.allow import workstation_ip

                            mine = workstation_ip((self.client_address or ("", 0))[0])
                            groups: dict[str, list] = {}
                            for rec in rows:
                                groups.setdefault(rec["lan_ip"], []).append(rec)
                            rest = [ip for ip in groups if ip and ip != mine]
                            rest.sort(key=lambda ip: groups[ip][0]["updated"], reverse=True)
                            ordered = ([mine] if mine and mine in groups else []) + rest
                            ordered += [ip for ip in groups if not ip]
                            rows = []
                            for ip in ordered:
                                for rec in groups[ip]:
                                    rows.append({
                                        "name": rec["name"],
                                        "connected": rec["connected"],
                                        "lan_ip": rec["lan_ip"],
                                        "recent_activity": rec.get("recent_activity"),
                                    })
                            body = _json({"part": part, "mine": mine, "rows": rows})
                        else:
                            body = _json({"part": part, "rows": rows})
                    return body

                try:
                    body, _cached = cached_read(pov_key, produce)
                    self._send(200, body, "application/json; charset=utf-8")
                except Exception as e:
                    self._send(500, _json({"error": err_text(e)}), "application/json; charset=utf-8")
                return
            if path == "/api/rows":
                qs = parse_qs(urlparse(self.path).query)
                tab = ((qs.get("tab") or ["here"])[0] or "here").strip().lower()
                scope = ((qs.get("scope") or [""])[0] or "").strip().lower()
                desk = ((qs.get("desk") or [""])[0] or "").strip()
                project = ((qs.get("project") or [""])[0] or "").strip()
                role_name = ((qs.get("role") or [""])[0] or "").strip()
                lan = ((qs.get("lan") or [""])[0] if "lan" in qs else None)
                rows_key = "|".join(
                    ("rows", tab, scope, desk, project, role_name, "" if lan is None else lan)
                )

                def produce() -> bytes:
                    with _office() as c:
                        return _json(_page_rows(
                            c._cn,
                            tab,
                            scope=scope,
                            desk=desk,
                            project=project,
                            role_name=role_name,
                            lan=lan,
                        ))

                try:
                    body, _cached = cached_read(rows_key, produce)
                    self._send(200, body, "application/json; charset=utf-8")
                except Exception as e:
                    self._send(500, _json({"error": err_text(e)}), "application/json; charset=utf-8")
                return
            if path == "/api/strip":
                qs = parse_qs(urlparse(self.path).query)
                scope = ((qs.get("scope") or [""])[0] or "").strip().lower()
                one = ((qs.get("desk") or [""])[0] or "").strip()
                project = ((qs.get("project") or [""])[0] or "").strip()
                role_name = ((qs.get("role") or [""])[0] or "").strip()
                if project or role_name:
                    try:
                        with _office() as c:
                            body = _json(_scope_strip(
                                c._cn,
                                "project" if project else "role",
                                project or role_name,
                            ))
                        self._send(200, body, "application/json; charset=utf-8")
                    except Exception as e:
                        self._send(500, _json({"error": err_text(e)}), "application/json; charset=utf-8")
                    return
                lan_set = "lan" in qs
                lan = ((qs.get("lan") or [""])[0] or "")
                if scope != "mine" and not one and not lan_set:
                    self._send(
                        400,
                        _json({"error": "GET /api/strip requires scope=mine or desk= or lan="}),
                        "application/json; charset=utf-8",
                    )
                    return
                try:
                    with _office() as c:

                        cur = c._cn.cursor()
                        try:
                            where = (
                                "n.deleted IS NULL AND n.type = 'desk' AND ("
                                " (j.time_connect IS NOT NULL AND (j.time_disconnect IS NULL"
                                "  OR j.time_connect >= j.time_disconnect))"
                                " OR (j.time_disconnect IS NOT NULL"
                                "  AND j.time_disconnect >= mill_now() - INTERVAL 1 DAY"
                                "  AND (j.time_connect IS NULL OR j.time_disconnect > j.time_connect))"
                                ")"
                            )
                            params: list = []
                            if one:
                                where += " AND n.name = %s"
                                params.append(one)
                            elif lan_set:
                                if lan:
                                    where += " AND j.lan_ip = %s"
                                    params.append(lan)
                                else:
                                    where += " AND (j.lan_ip IS NULL OR j.lan_ip = '')"
                            cur.execute(
                                "SELECT n.id, n.name,"
                                " (j.time_connect IS NOT NULL AND (j.time_disconnect IS NULL"
                                "  OR j.time_connect >= j.time_disconnect)) AS connected"
                                " FROM name n JOIN seat j ON j.desk_id = n.id"
                                " WHERE " + where,
                                tuple(params),
                            )
                            picked = [
                                (int(r[0]), _stored(str(r[1] or "")), bool(r[2]))
                                for r in cur.fetchall() if r and r[0]
                            ]
                            ids = [i for i, _name, _on in picked]
                            here_names = [name for _i, name, on in picked if on]
                            stale_names = [name for _i, name, on in picked if not on]
                            here = len(here_names)
                            unread = claimed = holds = misses = 0
                            unread_by, claimed_by, holds_by, miss_rows = [], [], [], []
                            if ids:
                                marks = ",".join(["%s"] * len(ids))
                                cur.execute(
                                    "SELECT ANY_VALUE(d.name), COUNT(*) FROM mail_to t"
                                    " JOIN name d ON d.id = t.desk_id"
                                    " WHERE t.opened IS NULL AND t.desk_id IN (" + marks + ")"
                                    " GROUP BY d.name ORDER BY d.name",
                                    tuple(ids),
                                )
                                unread_by = [
                                    {"desk": _stored(str(r[0] or "")), "n": int(r[1] or 0)}
                                    for r in cur.fetchall()
                                ]
                                unread = sum(r["n"] for r in unread_by)
                                cur.execute(
                                    "SELECT ANY_VALUE(d.name), COUNT(*) FROM todo t"
                                    " JOIN name d ON d.id = t.assigned_id"
                                    " WHERE t.status='claimed' AND t.assigned_id IN (" + marks + ")"
                                    " GROUP BY d.name ORDER BY d.name",
                                    tuple(ids),
                                )
                                claimed_by = [
                                    {"desk": _stored(str(r[0] or "")), "n": int(r[1] or 0)}
                                    for r in cur.fetchall()
                                ]
                                claimed = sum(r["n"] for r in claimed_by)
                                cur.execute(
                                    "SELECT ANY_VALUE(d.name), COUNT(*) FROM hold h"
                                    " JOIN name d ON d.id = h.desk_id"
                                    " WHERE h.desk_id IN (" + marks + ")"
                                    " GROUP BY d.name ORDER BY d.name",
                                    tuple(ids),
                                )
                                holds_by = [
                                    {"desk": _stored(str(r[0] or "")), "n": int(r[1] or 0)}
                                    for r in cur.fetchall()
                                ]
                                holds = sum(r["n"] for r in holds_by)
                                cur.execute(
                                    "SELECT d.name, s.kpi, s.value, s.target FROM score s"
                                    " JOIN name d ON d.id = s.desk_id"
                                    " WHERE s.desk_id IN (" + marks + ")"
                                    " ORDER BY d.name, s.kpi",
                                    tuple(ids),
                                )
                                for dname, kname, val, tgt in cur.fetchall():
                                    if _score_miss(val, tgt):
                                        miss_rows.append({
                                            "desk": _stored(str(dname or "")),
                                            "kpi": _stored(str(kname or "")),
                                        })
                                misses = len(miss_rows)
                        finally:
                            cur.close()
                        body = _json({
                            "here": here,
                            "unread": unread,
                            "claimed": claimed,
                            "holds": holds,
                            "misses": misses,
                            "here_names": here_names,
                            "stale_names": stale_names,
                            "unread_by": unread_by,
                            "claimed_by": claimed_by,
                            "holds_by": holds_by,
                            "miss_rows": miss_rows,
                        })
                    self._send(200, body, "application/json; charset=utf-8")
                except Exception as e:
                    self._send(500, _json({"error": err_text(e)}), "application/json; charset=utf-8")
                return
            # GET /api/v1/mail/{id} and /api/v1/todo/{id} - full body/text on open
            _m_mail = re.match(r"^/api/mail/(\d+)$", path)
            _m_todo = re.match(r"^/api/todo/(\d+)$", path)
            if _m_mail or _m_todo:
                t0 = time.perf_counter()
                kind = "mail" if _m_mail else "todo"
                iid = int((_m_mail or _m_todo).group(1))
                try:
                    with _office() as c:
                        from agent_coord.server.records import floor as rec_floor_mod

                        if kind == CONST_MAIL:
                            payload = rec_floor_mod.v1_mail(c._cn, iid)
                        else:
                            payload = rec_floor_mod.v1_todo(c._cn, iid)
                    missing = payload.get("error") or (
                        (kind == CONST_MAIL and payload.get("mail") is None)
                        or (kind == CONST_TODO and payload.get("todo") is None)
                    )
                    ms = (time.perf_counter() - t0) * 1000.0
                    body = _json(payload)
                    status = 404 if missing else 200
                    self._send(status, body, "application/json; charset=utf-8")
                    try:
                        from agent_coord.server.push import api_log, perf_log

                        api_log(
                            f"GET /api/v1/{kind}/{iid} {status} ms={ms:.0f} resp_b={len(body)}"
                        )
                        perf_log(
                            f"api.v1.{kind}_one",
                            ms,
                            status=status,
                            resp_b=len(body),
                        )
                    except Exception:
                        pass
                except Exception as e:
                    try:
                        from agent_coord.server.push import api_log, mill_admin_alert, perf_log

                        ms = (time.perf_counter() - t0) * 1000.0
                        api_log(f"GET /api/v1/{kind}/{iid} 500 ms={ms:.0f} err={e}")
                        perf_log(f"api.v1.{kind}_one", ms, status=500, err=str(e)[:160])
                        with _office() as c2:
                            mill_admin_alert(
                                c2._cn, f"GET /api/v1/{kind}/{iid}: {e}", command="floor"
                            )
                    except Exception:
                        pass
                    self._send(
                        500,
                        _json({"error": err_text(e)}),
                        "application/json; charset=utf-8",
                    )
                return

            if path in ("/api/doing", "/api/doing/history"):
                code, payload = _doing_read(path, parse_qs(urlparse(self.path).query))
                self._send(code, _json(payload), "application/json; charset=utf-8")
                return

            # GET /api/v1/{rooms,mailbox,tree-mail,tree-todo,todos,agents,scores,holds,watchers,events,names,map,timeline}
            # (path rewrite above maps /api/v1/X -> /api/X)
            _V1_PARTS = {
                "rooms": ("rooms", "v1_rooms"),
                "mailbox": ("mailbox", "v1_mailbox"),
                "tree-mail": ("tree-mail", "v1_tree_mail"),
                "tree-todo": ("tree-todo", "v1_tree_todo"),
                "todos": ("todos", "v1_todos"),
                "agents": ("agents", "v1_agents"),
                "scores": ("scores", "v1_scores"),
                "holds": ("holds", "v1_holds"),
                "watchers": ("watchers", "v1_watchers"),
                "events": ("events", "v1_events"),
                "names": ("names", "v1_names"),
                "map": ("map", "v1_map"),
                "timeline": ("timeline", "v1_timeline"),
            }
            if path.startswith("/api/") and path[len("/api/") :] in _V1_PARTS:
                route_key = path[len("/api/") :]
                v1_name, builder_name = _V1_PARTS[route_key]
                t0 = time.perf_counter()
                qs = parse_qs(urlparse(self.path).query)
                plist: list[str] = []
                for raw in (qs.get("projects") or []) + (qs.get("project") or []):
                    if not raw:
                        continue
                    plist.extend(x.strip() for x in str(raw).split(",") if x.strip())
                role_name = ((qs.get("role") or [""])[0] or "").strip()
                lan = ((qs.get("lan") or [""])[0] or "").strip()
                scope_n = int(bool(plist)) + int(bool(role_name)) + int(bool(lan))
                if scope_n != 1:
                    err = {
                        "error": f"GET /api/v1/{v1_name} requires one of ?project= or ?role= or ?lan="
                    }
                    self._send(400, _json(err), "application/json; charset=utf-8")
                    try:
                        from agent_coord.server.push import api_log

                        api_log(f"GET /api/v1/{v1_name} 400 ms=0 projects=[] err=scope required")
                    except Exception:
                        pass
                    return
                want_timings = str((qs.get("timings") or [""])[0] or "").strip().lower() in (
                    "1",
                    "true",
                    "yes",
                )
                from agent_coord.server.records.floor import (
                    parse_floor_fps,
                    parse_list_page,
                    parse_tree_depth,
                    parse_tree_parent_id,
                    parse_tree_window,
                )

                page_lim, page_cur = parse_list_page(qs)
                part_list: list[str] = []
                for raw in qs.get("parts") or []:
                    if not raw:
                        continue
                    part_list.extend(x.strip() for x in str(raw).split(",") if x.strip())
                desk_q = str((qs.get("desk") or [""])[0] or "").strip() or None
                scope_q = str((qs.get("scope") or [""])[0] or "").strip() or None
                win_s = str((qs.get("window") or [""])[0] or "").strip() or None
                if builder_name in ("v1_tree_mail", "v1_tree_todo"):
                    try:
                        parse_tree_window(qs)
                    except ValueError as e:
                        err = {"error": str(e)}
                        self._send(400, _json(err), "application/json; charset=utf-8")
                        try:
                            from agent_coord.server.push import api_log

                            api_log(
                                f"GET /api/v1/{v1_name} 400 ms=0 "
                                f"projects={plist!r} err=invalid window"
                            )
                        except Exception:
                            pass
                        return
                client_fps = parse_floor_fps(qs)
                fp_key = ",".join(f"{k}:{client_fps[k]}" for k in sorted(client_fps))
                from agent_coord.server.table_ver import PANE_TABLES, version_stamp

                pane_ver = version_stamp(PANE_TABLES.get(v1_name, ()))
                cache_key = "|".join(
                    (
                        "v1",
                        v1_name,
                        ",".join(plist),
                        role_name,
                        lan,
                        ",".join(part_list),
                        str(page_lim),
                        page_cur or "",
                        fp_key,
                        desk_q or "",
                        scope_q or "",
                        win_s or "",
                        str(parse_tree_depth(qs) or ""),
                        str(parse_tree_parent_id(qs) or ""),
                        pane_ver,
                    )
                )

                def load_payload() -> dict:
                    with _office() as c:
                        if role_name or lan:
                            from agent_coord.server.records.floor import v1_by_scope

                            return v1_by_scope(
                                c._cn,
                                v1_name,
                                "lan" if lan else "role",
                                lan or role_name,
                                client_fps=client_fps or None,
                                limit=page_lim,
                                cursor=page_cur,
                                parts=part_list or None,
                            )
                        from agent_coord.server.records import floor as rec_floor_mod

                        builder = getattr(rec_floor_mod, builder_name)
                        # v1 isolates + map/timeline joins: empty-on-match when ?fp= matches
                        # + lean list ?limit=/?cursor= (default limit 50; next cursor on response)
                        if builder_name in (
                            "v1_mailbox",
                            "v1_todos",
                            "v1_agents",
                            "v1_scores",
                            "v1_holds",
                            "v1_watchers",
                            "v1_events",
                            "v1_names",
                            "v1_map",
                            "v1_timeline",
                            "v1_tree_mail",
                            "v1_tree_todo",
                        ):
                            if builder_name in ("v1_tree_mail", "v1_tree_todo"):
                                kwargs = {
                                    "projects": plist,
                                    "limit": page_lim,
                                    "cursor": page_cur,
                                    "depth": parse_tree_depth(qs),
                                    "parent_id": parse_tree_parent_id(qs),
                                    "window": win_s,
                                }
                            else:
                                kwargs = {
                                    "projects": plist,
                                    "client_fps": client_fps or None,
                                    "limit": page_lim,
                                    "cursor": page_cur,
                                }
                            if builder_name == "v1_timeline":
                                kwargs["parts"] = part_list or None
                            return builder(c._cn, **kwargs)
                        # rooms (+ any future simple isolates): optional desk/scope
                        # for limited-trust membership filter (Host trust matrix).
                        if builder_name == "v1_rooms":
                            return builder(
                                c._cn,
                                projects=plist,
                                desk=desk_q,
                                scope=scope_q,
                            )
                        return builder(c._cn, projects=plist)

                def _v1_n(payload: dict) -> int:
                    if "mailbox" in payload:
                        return len(payload.get("mailbox") or [])
                    if "needs" in payload or "issues" in payload:
                        return len(payload.get("needs") or []) + len(payload.get("issues") or [])
                    if "events" in payload:
                        return len(payload.get("events") or [])
                    if "timeline" in payload:
                        return len(payload.get("timeline") or [])
                    if "agents" in payload:
                        return len(payload.get("agents") or [])
                    if "kpis" in payload:
                        return len(payload.get("kpis") or [])
                    if "locks" in payload:
                        return len(payload.get("locks") or [])
                    if "watchers" in payload:
                        return len(payload.get("watchers") or [])
                    if "catalog" in payload:
                        return len(payload.get("catalog") or [])
                    if "trees" in payload:
                        return len(payload.get("trees") or [])
                    return 0

                try:
                    if want_timings:
                        payload = load_payload()
                        n = _v1_n(payload)
                        ms = (time.perf_counter() - t0) * 1000.0
                        payload = dict(payload)
                        payload["timings"] = {"sql_ms": round(ms, 1), "resp_b": 0, "n": n}
                        body = _json(payload)
                        payload["timings"]["resp_b"] = len(body)
                        body = _json(payload)
                        cached = False
                    else:
                        def produce() -> bytes:
                            return _json(load_payload())

                        body, cached = cached_read(cache_key, produce, ttl=None)
                        n = 0
                        ms = (time.perf_counter() - t0) * 1000.0
                    self._send(200, body, "application/json; charset=utf-8")
                    try:
                        from agent_coord.server.push import api_log, perf_log

                        api_log(
                            f"GET /api/v1/{v1_name} 200 ms={ms:.0f} projects={plist!r} resp_b={len(body)}"
                        )
                        perf_log(
                            f"api.v1.{v1_name.replace('-', '_')}",
                            ms,
                            status=200,
                            n=n,
                            resp_b=len(body),
                            cache=1 if cached else 0,
                        )
                    except Exception:
                        pass
                except Exception as e:
                    try:
                        from agent_coord.server.push import api_log, mill_admin_alert, perf_log

                        ms = (time.perf_counter() - t0) * 1000.0
                        api_log(f"GET /api/v1/{v1_name} 500 ms={ms:.0f} err={e}")
                        perf_log(f"api.v1.{v1_name.replace('-', '_')}", ms, status=500, err=str(e)[:160])
                        with _office() as c2:
                            mill_admin_alert(c2._cn, f"GET /api/v1/{v1_name}: {e}", command="floor")
                    except Exception:
                        pass
                    self._send(500, _json({"error": err_text(e)}), "application/json; charset=utf-8")
                return
            if path == "/api/activity":
                qs = parse_qs(urlparse(self.path).query)
                project = (qs.get("project") or ["the-mill"])[0] or "the-mill"
                window = (qs.get("window") or ["24h"])[0] or "24h"
                type_s = (qs.get("type") or [""])[0] or ""
                from agent_coord.server.records.floor import parse_list_page

                span = window.strip().lower()
                page_lim, page_cur = parse_list_page(qs)
                cut = _activity_cut(qs, project)
                if span == "between" or span in ("min", "hourly", "hour", "daily", "day"):
                    if cut is None:
                        self._send(
                            400,
                            _json({"error": "activity scope is project, role, or lan"}),
                            "application/json; charset=utf-8",
                        )
                        return
                    scope, ident = cut

                if span == "between":
                    raw_lim = (qs.get("limit") or ["50"])[0]
                    try:
                        per_desk = int(str(raw_lim).strip() or "50")
                    except (TypeError, ValueError):
                        per_desk = 50
                    shown = 50 if per_desk < 1 or per_desk > 50 else per_desk
                    cache_key = f"activity|between|{scope}|{ident}|{shown}"

                    def produce() -> bytes:
                        with _office() as c:
                            from agent_coord.server.records import activity as rec_activity

                            rows = rec_activity.between_rows(c._cn, scope, ident, per_desk)
                        return _json(
                            {
                                "project": project,
                                "scope": scope,
                                "id": ident,
                                "window": "between",
                                "source": "activity",
                                "limit": shown,
                                "rows": rows,
                                "next": None,
                            }
                        )
                elif span in ("min", "hourly", "hour", "daily", "day"):
                    grain = "min" if span == "min" else (
                        "hour" if span in ("hourly", "hour") else "day"
                    )
                    cache_key = (
                        f"activity|span|{scope}|{ident}|{span}|{page_lim}|{page_cur or ''}"
                    )

                    def produce() -> bytes:
                        with _office() as c:
                            from agent_coord.server.records import activity as rec_activity
                            from agent_coord.server.records.floor import page_activity_rows

                            source, raw_rows = rec_activity.span_rows(
                                c._cn, scope, ident, grain
                            )
                            rows, nxt = page_activity_rows(
                                raw_rows, limit=page_lim, cursor=page_cur
                            )
                        return _json(
                            {
                                "project": project,
                                "scope": scope,
                                "id": ident,
                                "window": span,
                                "source": source,
                                "bucket": grain,
                                "rows": rows,
                                "next": nxt,
                            }
                        )
                else:

                    proj_name = _stored(project)
                    cache_key = (
                        f"activity|bucket|{proj_name}|{window}|{type_s}|{page_lim}|{page_cur or ''}"
                    )

                    def produce() -> bytes:
                        with _office() as c:
                            from agent_coord.server.records import activity as rec_activity
                            from agent_coord.server.records.floor import (
                                _timeline,
                                page_activity_rows,
                                window_bucket,
                            )

                            since, buck = window_bucket(window)
                            raw_rows = (
                                _timeline(c._cn, proj_name, window)
                                if not type_s
                                else rec_activity.bucket(
                                    c._cn, proj_name, 0, type_s, since, buck
                                )
                            )
                            rows, nxt = page_activity_rows(
                                raw_rows, limit=page_lim, cursor=page_cur
                            )
                        return _json(
                            {
                                "project": project,
                                "window": window,
                                "bucket": buck,
                                "rows": rows,
                                "next": nxt,
                            }
                        )

                body, _cached = cached_read(cache_key, produce)
                self._send(200, body, "application/json; charset=utf-8")
                return
            if path == "/api/howto":
                from agent_coord.server.howto import howto

                qs = parse_qs(urlparse(self.path).query)
                audience = (qs.get("audience") or [""])[0] or ""
                self._send(200, _json(howto(audience=audience)), "application/json; charset=utf-8")
                return
            if path == "/api/office-glance":
                qs = parse_qs(urlparse(self.path).query)
                window = (qs.get("window") or ["24h"])[0] or "24h"
                plist = []
                for raw in (qs.get("projects") or []) + (qs.get("project") or []):
                    if not raw:
                        continue
                    plist.extend(x.strip() for x in str(raw).split(",") if x.strip())
                if not plist:
                    self._send(
                        400,
                        _json({"error": "GET /api/office-glance requires ?project="}),
                        "application/json; charset=utf-8",
                    )
                    return
                project = ",".join(plist)
                with _office() as c:
                    from agent_coord.server.records.floor import office_glance as rec_glance

                    body = _json(rec_glance(c._cn, project, window=window))
                self._send(200, body, "application/json; charset=utf-8")
                return
            if path == "/api/wall-asset":
                board = wall_ui_default_board()
                body = _json(
                    {
                        "asset_id": wall_asset_id(board),
                        "pack": "default",
                        "path": str(board.name),
                    }
                )
                self._send(200, body, "application/json; charset=utf-8")
                return
            if path == "/api/wall-prefs":
                qs = parse_qs(urlparse(self.path).query)
                desk = (qs.get("desk") or [""])[0] or None
                body = _json(load_wall_prefs(desk=desk))
                self._send(200, body, "application/json; charset=utf-8")
                return
            if path in ("/api/admin/invites", "/api/invites"):
                # #sec S-5: the list is Admin only, from the door session or a bearer.
                from agent_coord.server.admin.invites import list_invites

                auth = (self.headers.get("Authorization") or "").strip()
                bearer = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
                try:
                    row = list_invites(office=_office, token=bearer, session=token or "")
                except CoordError as e:
                    self._send(403, _json({"error": str(e)}), "application/json; charset=utf-8")
                    return
                except Exception as e:
                    self._send(403, _json({"error": err_text(e)}), "application/json; charset=utf-8")
                    return
                self._send(200, _json(row), "application/json; charset=utf-8")
                return
            if path == "/api/glance" or path.startswith("/api/glance/"):
                from agent_coord.server.glance import serve as serve_glance

                serve_glance(self, path, token, api_only=api_only)
                return
            if path == "/api/briefing":
                from agent_coord.install.office import briefing_text

                qs = parse_qs(urlparse(self.path).query)
                kind = (qs.get("kind") or ["usecases"])[0] or "usecases"
                try:
                    text = briefing_text(kind)
                except ValueError as e:
                    self._send(400, str(e).encode("utf-8") + b"\n", "text/plain; charset=utf-8")
                    return
                self._send(200, text.encode("utf-8"), "text/markdown; charset=utf-8")
                return
            _send_not_found(self, closed=False)

        def do_POST(self) -> None:  # noqa: N802
            t0 = time.perf_counter()
            try:
                if _refuse_cookie_write(self):
                    return
                self._do_POST_inner()
            except Exception as _route_exc:
                _fail_closed(self, _route_exc)
            finally:
                _note_wall_api(self.path, t0)

        def _glance_tap(self) -> None:
            from agent_coord.server.allow import door_client
            from agent_coord.server.glance import GLANCE_COOKIE, _SESSION_S, accept_tap

            n = int(self.headers.get("Content-Length") or "0")
            if n < 0 or n > 2048:
                self._send(404, b"not found\n", "text/plain; charset=utf-8")
                return
            raw = self.rfile.read(n) if n else b""
            taps: list[str] = []
            word = ""
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
                if isinstance(data, dict) and isinstance(data.get("taps"), list):
                    taps = [str(t) for t in data.get("taps") or []]
                    word = str(data.get("passphrase") or "")
            except Exception:
                taps = []
            peer = (self.client_address or ("", 0))[0]
            # The lockout bucket is the trusted-proxy client, never a forged hop (#731).
            ip, _via = door_client(str(peer or ""), str(self.headers.get("x-forwarded-for") or ""))
            token = accept_tap(taps, word, ip=ip)
            if not token:
                self._send(404, b"not found\n", "text/plain; charset=utf-8")
                return
            self._send(
                200,
                _json({"open": True, "secrets": "redacted"}),
                "application/json; charset=utf-8",
                [("Set-Cookie", f"{GLANCE_COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={int(_SESSION_S)}")],
            )

        def _do_POST_inner(self) -> None:
            allowed, _token, extra = self._door_ok()
            if not allowed:
                _send_not_found(self, closed=True)
                return
            path = urlparse(self.path).path
            if path.startswith("/api/v1/"):
                path = "/api/" + path[len("/api/v1/") :]
            if path == "/api/glance/tap":
                self._glance_tap()
                return
            from agent_coord.client.outbound import canonical_command, is_mill_command_path, parse_path

            if is_mill_command_path(path):
                n = int(self.headers.get("Content-Length") or "0")
                raw = self.rfile.read(n) if n else b"{}"
                try:
                    data = json.loads(raw.decode("utf-8") or "{}")
                except json.JSONDecodeError:
                    self._send(400, _json({"error": "bad json"}), "application/json; charset=utf-8")
                    return
                if not isinstance(data, dict):
                    data = {}
                command = parse_path(path) or canonical_command(
                    str(data.get("verb") or data.get("cmd") or "")
                )
                data["verb"] = command
                auth = (self.headers.get("Authorization") or "").strip()
                token = ""
                if auth.lower().startswith("bearer "):
                    token = auth[7:].strip()
                elif auth.lower().startswith("token "):
                    token = auth[6:].strip()
                token = token or (self.headers.get("PRIVATE-TOKEN") or "").strip()
                token = token or str(data.get("token") or "")
                owner_log = str(data.get("owner") or "")[:64]
                acting = ""
                t0 = time.perf_counter()
                try:
                    from agent_coord.server.api.mill.rpc import dispatch

                    with _office() as c:
                        peer = (self.client_address or ("", 0))[0]
                        from agent_coord.server.admin.guard import mark_host

                        fwd = (self.headers.get("x-forwarded-for") or "").strip()
                        mark_host(data, peer, forwarded=bool(fwd))
                        row = dispatch(c, data, token=token)
                        acting = str(getattr(c, "acting_desk", "") or "")
                        if command == "join" and isinstance(row, dict):
                            from agent_coord.server.records import join as rec_join
                            from agent_coord.server.allow import workstation_ip

                            who = str(row.get("owner") or data.get("owner") or "")
                            rec_join.set_lan_ip(c._cn, who, workstation_ip(peer))
                    self._send(200, _json(row), "application/json; charset=utf-8")
                    try:
                        from agent_coord.server.push import api_log

                        ms = (time.perf_counter() - t0) * 1000.0
                        api_log(f"POST /api/mill/{command} 200 ms={ms:.0f} owner={owner_log}")
                        from agent_coord.server.push import perf_log

                        body_b = len(str(data.get("body") or data.get("need") or data.get("note") or "").encode("utf-8"))
                        resp_b = len(_json(row))
                        perf_log(
                            f"api.mill.{command}",
                            ms,
                            status=200,
                            owner=owner_log,
                            req_b=n,
                            body_b=body_b,
                            resp_b=resp_b,
                        )
                        from agent_coord.server.score_system import enqueue_command

                        enqueue_command(
                            acting,
                            command,
                            req_b=len(raw),
                            resp_b=resp_b,
                            ms=ms,
                        )
                    except Exception:
                        pass
                except CoordError as e:
                    try:
                        from agent_coord.server.push import api_log

                        ms = (time.perf_counter() - t0) * 1000.0
                        api_log(f"POST /api/mill/{command} 400 ms={ms:.0f} owner={owner_log} err={e}")
                        from agent_coord.server.push import perf_log

                        perf_log(f"api.mill.{command}", ms, status=400, owner=owner_log, err=" ".join(str(e).split())[:160])
                    except Exception:
                        pass
                    self._send(400, _json({"error": str(e)}), "application/json; charset=utf-8")
                except Exception as e:
                    try:
                        from agent_coord.server.push import api_log, mill_admin_alert

                        ms = (time.perf_counter() - t0) * 1000.0
                        api_log(f"POST /api/mill/{command} 500 ms={ms:.0f} owner={owner_log} err={e}")
                        from agent_coord.server.push import perf_log

                        perf_log(f"api.mill.{command}", ms, status=500, owner=owner_log, err=" ".join(str(e).split())[:160])
                        with _office() as c2:
                            mill_admin_alert(
                                c2._cn,
                                f"mill-wall {command}: {e}"[:4000],
                                command=str(command or ""),
                            )
                    except Exception:
                        pass
                    self._send(500, _json({"error": err_text(e)}), "application/json; charset=utf-8")
                return
            if path == "/api/howto":
                from agent_coord.server.howto import howto

                self._send(200, _json(howto()), "application/json; charset=utf-8")
                return
            if path in ("/api/admin/invites", "/api/invites"):
                n = int(self.headers.get("Content-Length") or "0")
                raw = self.rfile.read(n) if n else b"{}"
                try:
                    data = json.loads(raw.decode("utf-8") or "{}")
                except json.JSONDecodeError:
                    self._send(400, b'{"error":"bad json"}\n', "application/json; charset=utf-8")
                    return
                if not isinstance(data, dict):
                    self._send(400, b'{"error":"bad json"}\n', "application/json; charset=utf-8")
                    return
                try:
                    from agent_coord.server.admin.invites import post_invites

                    row = post_invites(data, office=_office, human_token=_token)
                    self._send(200, _json(row), "application/json; charset=utf-8")
                except CoordError as e:
                    self._send(400, _json({"error": str(e)}), "application/json; charset=utf-8")
                except Exception as e:
                    self._send(400, _json({"error": err_text(e)}), "application/json; charset=utf-8")
                return
            if path == "/api/collect":
                n = int(self.headers.get("Content-Length") or "0")
                raw = self.rfile.read(n) if n else b"{}"
                try:
                    data = json.loads(raw.decode("utf-8") or "{}")
                except json.JSONDecodeError:
                    self._send(400, b'{"error":"bad json"}\n', "application/json; charset=utf-8")
                    return
                if not isinstance(data, dict):
                    self._send(400, b'{"error":"bad json"}\n', "application/json; charset=utf-8")
                    return
                try:
                    from agent_coord.server.admin.human import redeem_collect

                    row = redeem_collect(str(data.get("code") or data.get("collect") or ""))
                    self._send(200, _json(row), "application/json; charset=utf-8")
                except CoordError as e:
                    self._send(400, _json({"error": str(e)}), "application/json; charset=utf-8")
                return
            if path == "/api/wall-prefs":
                n = int(self.headers.get("Content-Length") or "0")
                raw = self.rfile.read(n) if n else b"{}"
                try:
                    data = json.loads(raw.decode("utf-8") or "{}")
                except json.JSONDecodeError:
                    self._send(400, b'{"error":"bad json"}\n', "application/json; charset=utf-8")
                    return
                if not isinstance(data, dict):
                    self._send(400, b'{"error":"bad json"}\n', "application/json; charset=utf-8")
                    return
                try:
                    row = save_wall_prefs_stub(data)
                except Exception as e:
                    self._send(400, _json({"error": err_text(e)}), "application/json; charset=utf-8")
                    return
                self._send(200, _json({"ok": True, **row}), "application/json; charset=utf-8")
                return
            if path != "/api/desk":
                _send_not_found(self, closed=False)
                return
            n = int(self.headers.get("Content-Length") or "0")
            raw = self.rfile.read(n) if n else b"{}"
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                self._send(400, b'{"error":"bad json"}\n', "application/json; charset=utf-8")
                return
            if not isinstance(data, dict):
                self._send(400, b'{"error":"bad json"}\n', "application/json; charset=utf-8")
                return
            try:
                from agent_coord.server.admin.human import desk_post

                with _office() as c:
                    row = desk_post(c._cn, data, session=_token)
                self._send(200, _json(row), "application/json; charset=utf-8")
            except CoordError as e:
                self._send(400, _json({"error": str(e)}), "application/json; charset=utf-8")

    return Handler


def make_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    roots: dict[str, Path] | None = None,
    *,
    api_only: bool = False,
) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer(
        (host, port),
        make_handler(roots or parse_roots(), api_only=api_only),
    )
    return httpd


def serve(
    host: str = "127.0.0.1",
    port: int = 8765,
    roots: dict[str, Path] | None = None,
    *,
    api_only: bool = False,
    dogfood: bool = False,
) -> None:
    from agent_coord.server.netbind import assert_mill_api_bind

    roots = roots or parse_roots()
    # Product: HTTPS only. mill-wall --api-only is loopback behind nginx TLS.
    assert_mill_api_bind(host, api_only=api_only if api_only else True)
    # Non-api wall process on non-loopback without nginx TLS is not a supported cleartext mode.
    if not api_only:
        h = (host or "").strip()
        if h in ("0.0.0.0", "::", "*") or (
            h and h not in ("127.0.0.1", "localhost", "::1") and not h.startswith("127.")
        ):
            raise SystemExit(
                "HTTPS-only: refusing cleartext wall on non-loopback. "
                "Use `install wall --http nginx --apply` (TLS) or bind 127.0.0.1."
            )
    from .asgi import run_uvicorn

    run_uvicorn(host, port, roots, api_only=api_only, dogfood=dogfood)
