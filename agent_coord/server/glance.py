# -*- coding: utf-8 -*-
"""Human-readonly service glance. Six cached reads. One mill-perf tail for the slowest command this hour. No writes.

GET /api/v1/glance and GET /api/v1/glance/{alerts,office,platform,logs,book,door}.
One 30s body serves every browser. timings=1 skips that map.

Secrets are removed before the JSON is sent: tokens, bearers, invites, passwords,
client secrets, cookies, PRIVATE-TOKEN, CA keys, and mail or todo text. Counts
only. A book error string is not returned. The one error text kept is the
slowest command's err= from mill-perf.log, trimmed to 160 and secret-redacted.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from agent_coord.const import (
    CONST_ADMIN,
    CONST_HOLD,
    CONST_DOING,
    CONST_MAIL,
    CONST_OFFICE,
    CONST_ROSTER,
    CONST_SCORE,
    CONST_TODO,
    CONST_WATCH_NAME,
)
from agent_coord.server.admin.guard import ADMIN_ROSTER_ID, OFFICE_ROSTER_ID

TAP_RE = re.compile(r"^[A-Za-z0-9]{10}$")
GLANCE_COOKIE = "mill-glance"
_SESSION_S = 3600.0
_MISS_LIMIT = 5
_MISS_WINDOW_S = 900.0
_tap_lock = threading.Lock()
_sessions: dict[str, float] = {}
_misses: dict[str, list[float]] = {}

SECTIONS = ("alerts", "office", "platform", "logs", "book", "door")

_DROP_KEYS = frozenset(
    {
        "access_token",
        "authorization",
        "bearer",
        "body",
        "cert",
        "client_secret",
        "cookie",
        "directory_client_secret",
        "err",
        "error",
        "id_token",
        "invite",
        "invite_key",
        "invite_path",
        "invite_url",
        "key",
        "key_id",
        "note",
        "passwd",
        "password",
        "private-token",
        "private_token",
        "reason",
        "seat",
        "secret",
        "ca",
        "set-cookie",
        "ssl_dir",
        "token",
        "token_hash",
    }
)

_SAFE_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_SAFE_ROUTE = re.compile(r"^/api/[A-Za-z0-9_./-]{1,60}$")
_SAFE_STATION = re.compile(r"^[0-9A-Fa-f:.%]{1,45}$")
_SAFE_ALLOW = re.compile(r"^[0-9A-Fa-f:.]+(?:/\d{1,3})?$")
_TARGET = re.compile(r"^\d{0,6}$")

_WATCH = ("mill_span", "mill_between", "mill_wall_event")
_KEPT_OFF = (
    "mill-wall.floor_n",
    "mill-wall.floor_ms",
    "mill-wall.floor_bytes",
    "mill-desk.idle_verbs",
)
_LOG_LINES = (
    ("mill-wall.api_n", "mill-api.log", "mill commands in the last hour"),
    ("mill-wall.api_ms", "mill-perf.log", "p95 milliseconds of those commands"),
    ("mill-wall.api_bytes", "mill-api.log", "request plus response bytes of those commands"),
    ("mill-wall.ws_push", "mill-backchannel.log", "hub pushes that landed"),
    ("mill-wall.ws_miss", "mill-backchannel.log", "hub fanout misses"),
    ("mill-wall.err_n", "mill-api.log and mill-wall-svc.log", "command 500s and service crashes"),
    ("mill-wall.ticks", "mill-perf.log", "tick lines in the last hour"),
    ("mill-desk.hint_drop", "mill-perf.log", "sit drops in the last hour"),
)
_UNSTORED = (
    "p50 and max of one call",
    "4xx versus 5xx",
    "largest paths by response bytes",
    "answering, empty, or failed per activity window",
    "op=score.history count",
    "session hint files",
    "mill-wall-svc-out.log",
)
_STATION_TODOS = (
    "Station cards still fail when the book is asked with a lan cut. "
    "The wall asks those cards on the project book."
)
_TRUST_CHART = {
    "high": (
        "Any seated desk may mint a roster or a label. "
        "A label is mill label NAME NAME --yes first, then label-add. "
        "A seated desk may assign a card that has no assignee."
    ),
    "limited": (
        "Minting a roster or a label, and assigning a card, stay with Admin."
    ),
    "assign": "Nobody overwrites an assignee. The assignee releases the card first.",
}
_TYPES = (CONST_MAIL, CONST_TODO, CONST_DOING, CONST_HOLD, CONST_SCORE)


_COMMAND_LINE = re.compile(r"(?:^|\s)op=(?:verb|api\.mill\.([^\s]+))(?:\s|$)")
_COMMAND_MS = re.compile(r"(?:^|\s)ms=([0-9.]+)(?:\s|$)")
_COMMAND_NAME = re.compile(r"(?:^|\s)verb=([^\s]+)")
_COMMAND_DESK = re.compile(r"(?:^|\s)(?:desk|owner)=([^\s]+)")
_COMMAND_OK = re.compile(r"(?:^|\s)ok=([01])(?:\s|$)")
_COMMAND_STATUS = re.compile(r"(?:^|\s)status=(\d{3})(?:\s|$)")
_COMMAND_ERR = re.compile(r"(?:^|\s)err=(.*)$")
_ERR_MAX = 160
_KEEP_ERR_UNDER = "slowest_verb"
_COMMAND_TS = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})")
_PERF_TAIL = 16 * 1024 * 1024


def slowest_command_text(text: str, since: datetime) -> dict[str, Any] | None:
    """Max-ms command line at or after since. None when the hour has no command line.

    Reads both transports: op=verb (websocket, verb= and desk=) and
    op=api.mill.<command> (HTTP, owner=). Each call is logged once, on one
    transport, so no line is counted twice. ok is 1 or 0 (ws ok=, HTTP
    status 2xx). err is the line's err= text, trimmed to 160, only when the
    line has it. err= is the last field perf_log writes, so it runs to end of line.
    """
    best_ms = -1.0
    best: dict[str, Any] | None = None
    for line in (text or "").splitlines():
        op_m = _COMMAND_LINE.search(line)
        if op_m is None:
            continue
        ts_m = _COMMAND_TS.match(line)
        if ts_m is None:
            continue
        try:
            ts = datetime.strptime(ts_m.group(1), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if ts < since:
            continue
        ms_m = _COMMAND_MS.search(line)
        http_command = op_m.group(1)
        name_m = None if http_command else _COMMAND_NAME.search(line)
        name = http_command or (name_m.group(1) if name_m else None)
        if ms_m is None or not name:
            continue
        try:
            ms = float(ms_m.group(1))
        except ValueError:
            continue
        if ms <= best_ms:
            continue
        best_ms = ms
        desk_m = _COMMAND_DESK.search(line)
        ok_m = _COMMAND_OK.search(line)
        st_m = _COMMAND_STATUS.search(line)
        ok = int(ok_m.group(1)) if ok_m else (int(st_m.group(1)) < 400 if st_m else None)
        best = {
            "verb": name[:64],
            "ms": round(ms, 1),
            "desk": (desk_m.group(1) if desk_m else "")[:64],
        }
        if ok is not None:
            best["ok"] = int(ok)
        err_m = _COMMAND_ERR.search(line)
        err = err_m.group(1).strip() if err_m else ""
        if err:
            best["err"] = err[:_ERR_MAX]
    return best


def slowest_command(now: datetime | None = None) -> dict[str, Any] | None:
    """Last hour of mill-perf.log, last 16MB only. Not a score row."""
    from agent_coord.config import mill_home

    path = mill_home() / "mill-perf.log"
    try:
        if not path.is_file():
            return None
        size = path.stat().st_size
        with path.open("rb") as fh:
            fh.seek(max(0, size - _PERF_TAIL))
            raw = fh.read().decode("utf-8", "replace")
    except OSError:
        return None
    if size > _PERF_TAIL:
        raw = raw.split("\n", 1)[-1]
    now = now or datetime.now(timezone.utc)
    return slowest_command_text(raw, now - timedelta(hours=1))


def seal(value: Any) -> Any:
    """Drop secret keys, then redact secret text left in any string."""
    from agent_coord.server.redact import redact_obj

    return redact_obj(_drop(value))


def _drop(value: Any, parent: str = "") -> Any:
    if isinstance(value, dict):
        out: dict[Any, Any] = {}
        for key, item in value.items():
            name = str(key).strip().lower()
            if name in _DROP_KEYS and not (name == "err" and parent == _KEEP_ERR_UNDER):
                continue
            out[key] = _drop(item, name)
        return out
    if isinstance(value, list):
        return [_drop(item, parent) for item in value]
    if isinstance(value, str) and (
        "PRIVATE KEY" in value or value.startswith("-----BEGIN") or _b64_cert(value)
    ):
        return "[redacted]"
    return value


def _b64_cert(text: str) -> bool:
    """True when text is base64 of a PEM certificate. PEM redaction misses that form."""
    raw = (text or "").strip()
    if len(raw) < 40 or any(ch.isspace() for ch in raw):
        return False
    import base64

    try:
        body = base64.b64decode(raw, validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return False
    return "BEGIN CERTIFICATE" in body and "END CERTIFICATE" in body


def _num(raw: Any) -> int | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def _target(raw: Any) -> str:
    text = str(raw or "").strip()
    return text if _TARGET.fullmatch(text) else ""


def _iso(raw: Any) -> str | None:
    if raw is None:
        return None
    if hasattr(raw, "isoformat"):
        try:
            return raw.isoformat(sep=" ", timespec="seconds")[:32]
        except TypeError:
            return raw.isoformat()[:32]
    text = str(raw).strip()
    return text[:32] if text else None


def _name(raw: Any) -> str:
    text = str(raw or "").strip()
    return text if _SAFE_NAME.fullmatch(text) else ""


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _q(cn, sql: str) -> list[tuple] | None:
    cur = cn.cursor()
    try:
        cur.execute(sql)
        return list(cur.fetchall() or [])
    except Exception:
        return None
    finally:
        try:
            cur.close()
        except Exception:
            pass


def _cell(scores: dict[str, tuple], kpi: str) -> dict[str, Any]:
    row = scores.get(kpi)
    if not row:
        return {"value": None, "stored": False, "target": ""}
    value = _num(row[0])
    target = _target(row[1] if len(row) > 1 else "")
    if value is None:
        return {"value": None, "stored": False, "target": target}
    return {"value": value, "stored": True, "target": target}


def versions() -> dict[str, Any]:
    from importlib.metadata import PackageNotFoundError, version

    from agent_coord.install.packver import package_version, package_version_info

    info = package_version_info()
    process = str(package_version() or "")
    checkout = str(info.get("version") or "") if info.get("source") == "pyproject" else None
    try:
        installed = version("the-mill")
    except PackageNotFoundError:
        installed = None
    return {
        "process": process,
        "installed": installed,
        "checkout": checkout,
        "skew": bool(installed) and installed != process,
    }


def office_config(*, api_only: bool) -> dict[str, Any]:
    """Process facts. Host and database name only. No user, password, or secret."""
    from agent_coord.config import mill_trust, settings
    from agent_coord.server.admin.door import DEFAULT_INVITE_TTL, mode
    from agent_coord.server.allow import load_allow
    from agent_coord.server.netbind import lan_only_enabled, office_dir

    s = settings()
    door = mode()
    logout = bool(str(s.get("directory_logout_url") or "").strip())
    ssl = office_dir() / "ssl"
    allow = []
    for rule in load_allow():
        text = str(rule or "").strip()
        if _SAFE_ALLOW.fullmatch(text):
            allow.append(text)
        if len(allow) >= 64:
            break
    return {
        "door": door if door in ("path", "invite", "ip", "directory", "iam") else "path",
        "trust": "limited" if mill_trust() == "limited" else "high",
        "https": True,
        "bind": str(s.get("dashboard_bind") or "")[:64],
        "lan_only": bool(lan_only_enabled()),
        "cert_present": (ssl / "wall.crt").is_file() and (ssl / "wall.key").is_file(),
        "one_process": True,
        "api_only": bool(api_only),
        "serves_glass": not api_only,
        "static_cache": "pinned ?v=: public, max-age=31536000, immutable; else public, max-age=60 + ETag",
        "api_cache": "no-store",
        "mysql_host": str(s.get("host") or "")[:255],
        "mysql_database": str(s.get("database") or "")[:64],
        "issuer_set": bool(str(s.get("directory_issuer") or "").strip()),
        "client_id_present": bool(str(s.get("directory_client_id") or "").strip()),
        "logout_url_present": logout,
        "sign_out_link": logout and door in ("directory", "iam"),
        "allow": allow,
        "default_ttl": DEFAULT_INVITE_TTL,
    }


def _pack_routines() -> set[str] | None:
    try:
        import agent_coord
        from pathlib import Path

        root = Path(agent_coord.__file__).resolve().parent / "server" / "sql"
        order = (root / "apply_order.txt").read_text(encoding="utf-8").splitlines()
        create = re.compile(
            r"CREATE\s+(?:PROCEDURE|FUNCTION)\s+`?(mill_[A-Za-z0-9_]+)`?",
            re.I,
        )
        skip = {"wipe.sql", "tables.sql"}
        found: set[str] = set()
        for name in order:
            name = name.strip()
            if not name or name.startswith("#") or name in skip:
                continue
            found.update(create.findall((root / name).read_text(encoding="utf-8")))
        return found
    except Exception:
        return None


def _office_scores(cn) -> dict[str, tuple]:
    rows = _q(
        cn,
        "SELECT s.kpi, s.value, s.target, s.updated "
        "FROM score s "
        "JOIN name a ON a.id = s.roster_id "
        "JOIN name d ON d.id = s.desk_id "
        f"WHERE a.id = {OFFICE_ROSTER_ID} AND d.id = {ADMIN_ROSTER_ID} "
        "/* glance:office-scores */",
    )
    out: dict[str, tuple] = {}
    for row in rows or []:
        kpi = str(row[0] or "")
        if kpi and kpi not in out:
            out[kpi] = row[1:]
    return out


def _key_status(revoked, expires, enabled, now: datetime) -> str:
    if revoked:
        return "revoked"
    if isinstance(expires, datetime) and expires < now:
        return "expired"
    if not enabled:
        return "pending"
    return "enabled"


def _drain(cn) -> dict[str, Any] | None:
    rows = _q(
        cn,
        "SELECT LEFT(body, 240) FROM mail "
        "WHERE body LIKE 'MAINTENANCE_DRAIN%' "
        "ORDER BY id DESC LIMIT 1 /* glance:drain */",
    )
    if not rows or not rows[0] or not rows[0][0]:
        return None
    from agent_coord.protocol.presence.drain import drain_public_dict, parse_maintenance_drain

    parsed = parse_maintenance_drain(str(rows[0][0]))
    if not parsed:
        return None
    public = drain_public_dict(parsed)
    phase = str(public.get("phase") or "")
    eta = _iso(public.get("eta_at"))
    if phase not in ("draining", "overdue") or not eta:
        return None
    return {"phase": phase, "eta_at": eta}


def _routes(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", "replace")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    if not isinstance(raw, dict):
        return []
    out = []
    for key, item in raw.items():
        route = str(key or "")
        if route == "/api/floor" or route.startswith("/api/floor/"):
            continue
        if not _SAFE_ROUTE.fullmatch(route) or not isinstance(item, dict):
            continue
        n = _num(item.get("n"))
        ms = _num(item.get("ms"))
        if n is None:
            continue
        out.append({"route": route, "n": n, "ms": 0 if ms is None else ms})
    out.sort(key=lambda row: (-row["n"], row["route"]))
    return out[:64]


def _count(cn, sql: str) -> int | None:
    rows = _q(cn, sql)
    if not rows or not rows[0]:
        return None
    return _num(rows[0][0])


def build(cn, *, api_only: bool = False) -> dict[str, Any]:
    """Office-wide packet. Station and signed_in are filled per request."""
    from agent_coord.server.score_tick import BOOK_PERF, EVERY_S, WINDOW_S

    cfg = office_config(api_only=api_only)
    scores = _office_scores(cn)
    ver = versions()

    system_rows = _q(
        cn,
        "SELECT d.name, s.value FROM score s "
        "JOIN name d ON d.id = s.desk_id "
        "JOIN name a ON a.id = s.roster_id "
        f"WHERE s.kpi = 'system' AND a.id = {OFFICE_ROSTER_ID} "
        "/* glance:system-scores */",
    )
    commands = 0
    with_score: set[str] = set()
    if system_rows is not None:
        for name, value in system_rows:
            desk = _name(name)
            if not desk:
                continue
            with_score.add(desk)
            n = _num(value)
            if n is not None:
                commands += n
    join_rows = _q(
        cn,
        "SELECT d.name FROM seat j "
        "JOIN name d ON d.id = j.desk_id /* glance:join-desks */",
    )
    here: list[str] = []
    if join_rows is not None:
        for (name,) in join_rows:
            desk = _name(name)
            if desk and desk not in with_score and desk not in here:
                here.append(desk)
    here.sort()

    hour_rows = _q(
        cn,
        "SELECT e.value FROM score s "
        "JOIN score_evidence e ON e.score_id = s.id "
        "JOIN name a ON a.id = s.roster_id "
        "JOIN name d ON d.id = s.desk_id "
        f"WHERE s.kpi = 'wall' AND a.id = {OFFICE_ROSTER_ID} AND d.id = {OFFICE_ROSTER_ID} "
        "AND e.`timestamp` = STR_TO_DATE("
        "CONCAT('1970-01-01 ', LPAD(HOUR(NOW()), 2, '0'), ':00:00'), '%Y-%m-%d %H:%i:%s') "
        "AND e.taken = CURDATE() "
        "LIMIT 1 /* glance:wall-hour */",
    )
    routes = _routes(hour_rows[0][0]) if hour_rows else []

    episodes = []
    for kpi in BOOK_PERF:
        cell = _cell(scores, kpi)
        if not cell["stored"]:
            continue
        episodes.append({"kpi": kpi, "value": cell["value"], "target": cell["target"]})

    type_rows = _q(
        cn,
        "SELECT type, COUNT(*) FROM activity GROUP BY type /* glance:activity-types */",
    )
    activity = {name: 0 for name in _TYPES}
    book_open = type_rows is not None
    if type_rows is not None:
        for typ, n in type_rows:
            key = str(typ or "")
            if key in activity:
                activity[key] = _num(n) or 0
    live = {
        "mail": _count(cn, "SELECT COUNT(*) FROM mail /* glance:live-mail */"),
        "todo": _count(cn, "SELECT COUNT(*) FROM todo /* glance:live-todo */"),
        "join": _count(cn, "SELECT COUNT(*) FROM seat /* glance:live-join */"),
        "hold": _count(cn, "SELECT COUNT(*) FROM hold /* glance:live-hold */"),
        "score": _count(cn, "SELECT COUNT(*) FROM score /* glance:live-score */"),
    }
    name_rows = _q(
        cn,
        "SELECT SUM(deleted IS NULL), SUM(deleted IS NOT NULL) FROM name /* glance:names */",
    )
    name_live = _num(name_rows[0][0]) if name_rows and name_rows[0] else None
    name_retired = _num(name_rows[0][1]) if name_rows and name_rows[0] else None
    types: dict[str, Any] = {}
    for name in _TYPES:
        types[name] = {"activity": activity[name], "live": live.get(name)}
    types[CONST_WATCH_NAME] = {"live": name_live, "retired": name_retired}

    seed_rows = _q(
        cn,
        f"SELECT type, IF(id = {OFFICE_ROSTER_ID}, '{CONST_OFFICE}', '{CONST_ADMIN}'), deleted IS NULL FROM name "
        f"WHERE id IN ({OFFICE_ROSTER_ID}, {ADMIN_ROSTER_ID}) /* glance:seeds */",
    )
    seeds = [
        {"type": CONST_ROSTER, "name": CONST_OFFICE, "present": False, "retired": False},
        {"type": CONST_ROSTER, "name": CONST_ADMIN, "present": False, "retired": False},
    ]
    found: dict[tuple[str, str], bool] = {}
    for row in seed_rows or []:
        found[(str(row[0] or ""), str(row[1] or ""))] = bool(row[2])
    for seed in seeds:
        alive = found.get((seed["type"], seed["name"]))
        if alive is None:
            continue
        seed["present"] = True
        seed["retired"] = not alive

    admin_rows = _q(
        cn,
        "SELECT d.name FROM member m "
        "JOIN name d ON d.id = m.desk_id "
        "JOIN name r ON r.id = m.name_id "
        f"WHERE r.type = '{CONST_ROSTER}' AND r.name = '{CONST_ADMIN}' "
        "ORDER BY d.name /* glance:admin */",
    )
    admin = []
    for row in admin_rows or []:
        desk = _name(row[0])
        if desk and desk not in admin:
            admin.append(desk)

    pack = _pack_routines()
    live_rows = _q(
        cn,
        "SELECT ROUTINE_NAME FROM information_schema.ROUTINES "
        "WHERE ROUTINE_SCHEMA = DATABASE() AND ROUTINE_NAME LIKE 'mill\\_%' "
        "/* glance:routines */",
    )
    if pack is None or live_rows is None:
        routines: dict[str, Any] = {
            "pack": None,
            "live": None,
            "missing": None,
            "extra": None,
            "watch": {name: None for name in _WATCH},
        }
        missing_n = None
    else:
        live_names = {str(row[0]) for row in live_rows if row and row[0]}
        missing = sorted(pack - live_names)
        extra = sorted(name for name in (live_names - pack) if _SAFE_NAME.fullmatch(name))
        routines = {
            "pack": len(pack),
            "live": len(live_names),
            "missing": missing[:50],
            "extra": extra[:50],
            "watch": {name: name in live_names for name in _WATCH},
        }
        missing_n = len(missing)

    invite_rows = _q(
        cn,
        "SELECT label, ttl_seconds, expires_at, revoked_at, enabled_at "
        "FROM mill_invite ORDER BY created_at DESC /* glance:invites */",
    )
    now = _now()
    counts = {"pending": 0, "enabled": 0, "revoked": 0, "expired": 0}
    keys = []
    if invite_rows is not None:
        for label, ttl_s, expires, revoked, enabled in invite_rows:
            status = _key_status(revoked, expires, enabled, now)
            counts[status] = counts.get(status, 0) + 1
            text = str(label or "").strip()[:64]
            keys.append(
                {
                    "label": text,
                    "status": status,
                    "ttl_seconds": _num(ttl_s),
                    "expires_at": _iso(expires),
                }
            )
    welcome_invites = _count(cn, "SELECT COUNT(*) FROM mill_invite /* glance:welcome-invites */")
    welcome_joined = _count(cn, "SELECT COUNT(*) FROM mill_invite_join /* glance:welcome-joined */")

    touched = _cell(scores, "mill-office.activities")
    lines = []
    for kpi, source, caption in _LOG_LINES:
        cell = _cell(scores, kpi)
        lines.append(
            {
                "kpi": kpi,
                "value": cell["value"],
                "stored": cell["stored"],
                "target": cell["target"],
                "source": source,
                "caption": caption,
            }
        )

    packet = {
        "secrets": "redacted",
        "alerts": {
            "secrets": "redacted",
            "err_n": _cell(scores, "mill-wall.err_n"),
            "ws_miss": _cell(scores, "mill-wall.ws_miss"),
            "hint_drop": _cell(scores, "mill-desk.hint_drop"),
            "drain": _drain(cn),
            "standing": [{"id": "station_todos", "line": _STATION_TODOS}],
            "version": ver,
            "routines_missing": missing_n,
        },
        "office": {
            "secrets": "redacted",
            "door": cfg["door"],
            "trust": cfg["trust"],
            "https": True,
            "bind": cfg["bind"],
            "lan_only": cfg["lan_only"],
            "cert_present": cfg["cert_present"],
            "one_process": True,
            "api_only": cfg["api_only"],
            "serves_glass": cfg["serves_glass"],
            "static_cache": cfg["static_cache"],
            "api_cache": cfg["api_cache"],
            "mysql": {"host": cfg["mysql_host"], "database": cfg["mysql_database"]},
            "seeds": seeds,
            "station": "",
            "signed_in": False,
        },
        "platform": {
            "secrets": "redacted",
            "desks_with_score": len(with_score) if system_rows is not None else None,
            "verbs_today": commands if system_rows is not None else None,
            "desks_here_without": len(here) if join_rows is not None else None,
            "desks_here_without_names": here[:50],
            "ticks": _cell(scores, "mill-wall.ticks"),
            "hint_drop": _cell(scores, "mill-desk.hint_drop"),
            "routes": routes,
            "episodes": episodes,
            "kept_off": list(_KEPT_OFF),
        },
        "logs": {
            "secrets": "redacted",
            "window_s": WINDOW_S,
            "every_s": EVERY_S,
            "lines": lines,
            "unstored": list(_UNSTORED),
            "slowest_verb": slowest_command(),
        },
        "book": {
            "secrets": "redacted",
            "open": book_open,
            "types": types,
            "seats_here": live.get("join"),
            "promises_held": live.get("hold"),
            "retired_names": name_retired,
            "admin": admin,
            "routines": routines,
            "activity_touched_last_hour": {
                "value": touched["value"],
                "stored": touched["stored"],
            },
        },
        "door": {
            "secrets": "redacted",
            "default_ttl": cfg["default_ttl"],
            "keys_stored": invite_rows is not None,
            "counts": counts,
            "keys": keys[:100],
            "welcome": {
                "invites": welcome_invites,
                "joined": welcome_joined,
                "stored": welcome_invites is not None and welcome_joined is not None,
            },
            "allow": cfg["allow"],
            "allow_enforced": cfg["door"] == "ip",
            "directory": {
                "issuer_set": cfg["issuer_set"],
                "client_id_present": cfg["client_id_present"],
                "logout_url_present": cfg["logout_url_present"],
                "sign_out_link": cfg["sign_out_link"],
            },
            "trust": cfg["trust"],
            "trust_chart": dict(_TRUST_CHART),
        },
    }
    return seal(packet)


def client_bits(*, peer: str, forwarded: str, token: str) -> dict[str, Any]:
    """This browser only. A boolean and a station address. The token stays here."""
    from agent_coord.server.allow import door_client, workstation_ip

    station = workstation_ip(door_client(peer or "", forwarded or "")[0])
    if not _SAFE_STATION.fullmatch(station or ""):
        station = ""
    return {"station": station, "signed_in": _signed_in(token)}


def _signed_in(token: str) -> bool:
    raw = (token or "").strip()
    if not raw:
        return False
    try:
        from agent_coord.client.tokens import token_hash
        from agent_coord.server.middleware import _office
        from agent_coord.server.records import human as rec_human

        with _office() as book:
            return bool(rec_human.open(book._cn, token_hash(raw)))
    except Exception:
        return False


def serial(taps: list[str], passphrase: str = "") -> str:
    """Ordered tap lines, then p:<passphrase> when a passphrase is present."""
    lines = [str(t or "").strip() for t in taps]
    if not lines or any(TAP_RE.fullmatch(line) is None for line in lines) or len(lines) > 16:
        raise ValueError("tap required")
    text = "\n".join(lines)
    word = str(passphrase or "")
    if word:
        text = text + "\np:" + word
    return text


def digest_for(taps: list[str], passphrase: str = "") -> str:
    return hashlib.sha256(serial(taps, passphrase).encode("utf-8")).hexdigest()


def stored_digest() -> str:
    from agent_coord.config import settings

    raw = str(settings().get("glance_tap") or "").strip().lower()
    if re.fullmatch(r"[0-9a-f]{64}", raw):
        return raw
    return ""


def _cookie(handler, name: str) -> str:
    headers = getattr(handler, "headers", None)
    raw = str(headers.get("Cookie") or "") if headers is not None else ""
    for part in raw.split(";"):
        if "=" not in part:
            continue
        key, val = part.split("=", 1)
        if key.strip() == name:
            return val.strip()
    return ""


def session_open(token: str) -> bool:
    now = time.monotonic()
    with _tap_lock:
        dead = [key for key, exp in _sessions.items() if exp <= now]
        for key in dead:
            _sessions.pop(key, None)
        exp = _sessions.get(token or "")
        return bool(exp and exp > now)


def _locked_out(ip: str) -> bool:
    now = time.monotonic()
    with _tap_lock:
        recent = [t for t in _misses.get(ip, []) if now - t < _MISS_WINDOW_S]
        _misses[ip] = recent
        return len(recent) >= _MISS_LIMIT


def _note_miss(ip: str) -> None:
    now = time.monotonic()
    with _tap_lock:
        recent = [t for t in _misses.get(ip, []) if now - t < _MISS_WINDOW_S]
        recent.append(now)
        _misses[ip] = recent


def _clear_miss(ip: str) -> None:
    with _tap_lock:
        _misses.pop(ip, None)


def open_session() -> str:
    token = secrets.token_urlsafe(32)
    with _tap_lock:
        _sessions[token] = time.monotonic() + _SESSION_S
    return token


def read_allowed(handler) -> bool:
    """A glance read needs the cookie from a keypad match. An empty digest does not open it."""
    return session_open(_cookie(handler, GLANCE_COOKIE))


def accept_tap(taps: list[str], passphrase: str, *, ip: str) -> str | None:
    """Return a session token when the digest matches. None on a miss. No secrets in errors."""
    if _locked_out(ip):
        return None
    want = stored_digest()
    if not want:
        _note_miss(ip)
        return None
    try:
        got = digest_for(taps, passphrase)
    except ValueError:
        _note_miss(ip)
        return None
    if not hmac.compare_digest(got, want):
        _note_miss(ip)
        return None
    _clear_miss(ip)
    return open_session()


def load_packet(*, api_only: bool) -> dict[str, Any]:
    from agent_coord.server.middleware import _office

    with _office() as book:
        return build(book._cn, api_only=api_only)


def serve(handler, path: str, token: str, *, api_only: bool) -> None:
    """Answer one glance GET. Unknown section is HTTP 404. Book text is not returned."""
    from urllib.parse import parse_qs, urlparse

    import time

    from agent_coord.server.middleware import _json, cached_read

    if not read_allowed(handler):
        handler._send(404, b"not found\n", "text/plain; charset=utf-8")
        return
    tail = path[len("/api/glance") :].strip("/")
    if tail == "":
        section = ""
    elif tail in SECTIONS:
        section = tail
    else:
        handler._send(
            404,
            _json({"error": "unknown glance section", "secrets": "redacted"}),
            "application/json; charset=utf-8",
        )
        return
    qs = parse_qs(urlparse(handler.path).query)
    timings = str((qs.get("timings") or [""])[0] or "").strip().lower() in ("1", "true", "yes")

    def produce() -> bytes:
        return json.dumps(seal(load_packet(api_only=api_only)), default=str).encode("utf-8")

    started = time.perf_counter()
    try:
        if timings:
            raw = produce()
        else:
            raw, _hit = cached_read("glance", produce)
    except Exception:
        try:
            from agent_coord.server.push import api_log

            api_log("GET /api/glance 500")
        except Exception:
            pass
        handler._send(
            500,
            _json({"error": "glance unavailable", "secrets": "redacted"}),
            "application/json; charset=utf-8",
        )
        return
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError:
        doc = {}
    if not isinstance(doc, dict):
        doc = {}
    peer = (getattr(handler, "client_address", None) or ("", 0))[0]
    forwarded = ""
    headers = getattr(handler, "headers", None)
    if headers is not None:
        forwarded = str(headers.get("x-forwarded-for") or "")
    bits = client_bits(peer=str(peer or ""), forwarded=forwarded, token=token or "")
    office = doc.get("office")
    if isinstance(office, dict):
        office["station"] = bits["station"]
        office["signed_in"] = bool(bits["signed_in"])
    doc = seal(doc)
    if section:
        body = doc.get(section)
        if not isinstance(body, dict):
            body = {"secrets": "redacted"}
    else:
        body = doc
    if timings:
        body = dict(body)
        body["timings"] = {"sql_ms": round((time.perf_counter() - started) * 1000.0, 1)}
    handler._send(200, _json(seal(body)), "application/json; charset=utf-8")
