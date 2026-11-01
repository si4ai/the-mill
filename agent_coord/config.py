"""Office config. Env AGENT_COORD_* overrides the file. Never stores a session token."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from agent_coord.const import CONST_DESK, CONST_LABEL, CONST_ROSTER

DEFAULTS: dict[str, Any] = {
    "host": "127.0.0.1",
    "port": 3306,
    "user": "root",
    "password": "root",
    "database": "agent_coord",
    "node": "",
    "dashboard_bind": "127.0.0.1",
    "dashboard_port": 8765,
    "door": "path",
    "directory_kind": "entra",
    "directory_issuer": "",
    "directory_client_id": "",
    "directory_admin_group": "ROLE_Admin",
    "directory_client_secret": "",
    "directory_logout_url": "",
    "wake_url": "",
    # #618: hosts (with a path prefix) a desk's webhook may point at; comma list.
    "wake_hosts": "api2.cursor.sh/automations/webhook/",
    "bot_wake_url": "",
    "bot_wake_cmd": "",
    "spawn": "",
    "lan_only": "0",
    "mill_url": "",
    "token_required": "1",
    "trust": "high",
    # Card 931 / F223: days a disconnected desk's hold must age before any high-trust desk may drop it.
    "hold_stale_days": "7",
    # MySQL Connector/Python knobs (optional; empty = connector default)
    "use_pure": "",
    "compress": "",
    "buffered": "",
    "glance_tap": "",
    # F171: mill-perf.log on (default), all (fast SQL lines too) or off.
    "perf": "on",
    # #797: mill-home log rotation (bytes cap and retention days).
    "log_max_bytes": str(10 * 1024 * 1024),
    "log_retain_days": "30",
}

_ENV = {
    "host": "AGENT_COORD_HOST",
    "port": "AGENT_COORD_PORT",
    "user": "AGENT_COORD_USER",
    "password": "AGENT_COORD_PASSWORD",
    "database": "AGENT_COORD_DATABASE",
    "node": "AGENT_COORD_NODE",
    "dashboard_bind": "AGENT_COORD_DASHBOARD_BIND",
    "dashboard_port": "AGENT_COORD_DASHBOARD_PORT",
    "door": "AGENT_COORD_DOOR",
    "directory_kind": "AGENT_COORD_DIRECTORY_KIND",
    "directory_issuer": "AGENT_COORD_DIRECTORY_ISSUER",
    "directory_client_id": "AGENT_COORD_DIRECTORY_CLIENT_ID",
    "directory_admin_group": "AGENT_COORD_DIRECTORY_ADMIN_GROUP",
    "directory_client_secret": "AGENT_COORD_DIRECTORY_CLIENT_SECRET",
    "directory_logout_url": "AGENT_COORD_DIRECTORY_LOGOUT_URL",
    "wake_url": "AGENT_COORD_WAKE_URL",
    "wake_hosts": "AGENT_COORD_WAKE_HOSTS",
    "bot_wake_url": "AGENT_COORD_BOT_WAKE_URL",
    "bot_wake_cmd": "AGENT_COORD_BOT_WAKE_CMD",
    "spawn": "AGENT_COORD_SPAWN",
    "lan_only": "AGENT_COORD_LAN_ONLY",
    "mill_url": "AGENT_COORD_MILL_URL",
    "token_required": "AGENT_COORD_TOKEN_REQUIRED",
    "trust": "AGENT_COORD_TRUST",
    "hold_stale_days": "AGENT_COORD_HOLD_STALE_DAYS",
    "use_pure": "AGENT_COORD_USE_PURE",
    "compress": "AGENT_COORD_COMPRESS",
    "buffered": "AGENT_COORD_BUFFERED",
    "glance_tap": "AGENT_COORD_GLANCE_TAP",
    "perf": "AGENT_COORD_PERF",
    "log_max_bytes": "AGENT_COORD_LOG_MAX_BYTES",
    "log_retain_days": "AGENT_COORD_LOG_RETAIN_DAYS",
}

_INT_KEYS = {"port", "dashboard_port", "hold_stale_days", "log_max_bytes", "log_retain_days"}


def mill_debug() -> bool:
    """AGENT_COORD_DEBUG / AGENT_COORD_VERBOSE or mill --verbose. Prints /ws and POST /mill/v1."""
    raw = (
        os.environ.get("AGENT_COORD_DEBUG") or os.environ.get("AGENT_COORD_VERBOSE") or ""
    ).strip().lower()
    return raw in ("1", "true", "yes", "on", "debug", "verbose")


def mill_home() -> Path:
    env = (os.environ.get("AGENT_COORD_MILL_HOME") or "").strip()
    if env:
        return Path(env)
    return Path.home() / ".mill"


def config_path() -> Path:
    raw = (os.environ.get("AGENT_COORD_CONFIG") or "").strip()
    if raw:
        return Path(raw)
    return mill_home() / "config.toml"


def mill_trust() -> str:
    """high (default) or limited. Reclaim/group-name create: mill host always."""
    raw = str(settings().get("trust") or "high").strip().lower()
    return "limited" if raw in ("limited", "low", "strict") else "high"


HOLD_STALE_DAYS_DEFAULT = 7


def hold_stale_days() -> int:
    """Days a disconnected desk's hold must age before a non-Admin may drop it at high trust (F223).

    Config key hold_stale_days / env AGENT_COORD_HOLD_STALE_DAYS. Default 7. Values below 1
    fall back to the default.
    """
    try:
        n = int(settings().get("hold_stale_days") or HOLD_STALE_DAYS_DEFAULT)
    except (TypeError, ValueError):
        return HOLD_STALE_DAYS_DEFAULT
    return n if n >= 1 else HOLD_STALE_DAYS_DEFAULT


def set_mill_trust(level: str, path: Path | None = None) -> str:
    """Persist high or limited on the wall. AGENT_COORD_TRUST still overrides the file."""
    raw = (level or "").strip().lower()
    if raw not in ("high", "limited"):
        raise ValueError("trust must be high or limited")
    data = load_file(path)
    data["trust"] = raw
    save_config(data, path)
    return raw


def mill_catalog_open(kind: str) -> bool:
    """True if this desk may mint a name of this kind.

    A desk is always allowed. A project, role, or label is allowed when trust
    is high. Limited trust: Admin catalog commands mint those. The kind is the
    call's argument.
    """
    k = (kind or "").strip().lower()
    if k in ("", CONST_DESK):
        return True
    if mill_trust() != "high":
        return False
    return k in (CONST_ROSTER, CONST_LABEL)


def load_file(path: Path | None = None) -> dict[str, Any]:
    p = path or config_path()
    if not p.is_file():
        return {}
    out: dict[str, Any] = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        key, raw = s.split("=", 1)
        key = key.strip()
        if key not in DEFAULTS:
            continue
        val = raw.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1].replace("\\\"", '"').replace("\\\\", "\\")
        out[key] = val
    return out


def settings(path: Path | None = None) -> dict[str, Any]:
    """File, then env. Env wins so tests and one-off overrides keep working."""
    out = dict(DEFAULTS)
    for key, val in load_file(path).items():
        if val is None or val == "":
            continue
        out[key] = val
    for key, envn in _ENV.items():
        got = os.environ.get(envn)
        if got is not None and got != "":
            out[key] = got
    for key in _INT_KEYS:
        out[key] = int(out[key])
    return out


def _as_bool(raw: Any, default: bool | None = None) -> bool | None:
    """Parse optional bool config. None = omit (connector default)."""
    if raw is None:
        return default
    s = str(raw).strip().lower()
    if s == "":
        return default
    if s in ("1", "true", "yes", "on"):
        return True
    if s in ("0", "false", "no", "off"):
        return False
    return default


def mysql_kwargs(path: Path | None = None) -> dict[str, Any]:
    """Connect kwargs. Optional use_pure/compress from config/env.

    Safe default: omit use_pure/compress so Connector picks C-ext when present,
    else pure Python. Explicit true/false in config or AGENT_COORD_* wins.
    """
    s = settings(path)
    out: dict[str, Any] = dict(
        host=s["host"],
        port=int(s["port"]),
        user=s["user"],
        password=s["password"],
        database=s["database"],
        autocommit=False,
        connection_timeout=10,
    )
    use_pure = _as_bool(s.get("use_pure"), default=None)
    compress = _as_bool(s.get("compress"), default=None)
    if use_pure is not None:
        out["use_pure"] = use_pure
    if compress is not None:
        out["compress"] = compress
    return out


def mysql_cursor_kwargs(path: Path | None = None) -> dict[str, Any]:
    """Cursor kwargs. buffered only when explicitly set (default omit = False behavior)."""
    s = settings(path)
    buffered = _as_bool(s.get("buffered"), default=None)
    out: dict[str, Any] = {}
    if buffered is not None:
        out["buffered"] = buffered
    return out


def save_config(data: dict[str, Any], path: Path | None = None) -> Path:
    p = path or config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    keys = (
        "host",
        "port",
        "user",
        "password",
        "database",
        "node",
        "dashboard_bind",
        "dashboard_port",
        "door",
        "directory_kind",
        "directory_issuer",
        "directory_client_id",
        "directory_admin_group",
        "directory_client_secret",
        "directory_logout_url",
        "wake_url",
        "wake_hosts",
        "bot_wake_url",
        "bot_wake_cmd",
        "spawn",
        "lan_only",
        "mill_url",
        "token_required",
        "trust",
        "use_pure",
        "compress",
        "buffered",
        "glance_tap",
    )
    lines = [
        "# Written by mill init. AGENT_COORD_* environment variables override this file.",
        "# Office setup only. This is NOT a session token - clock in with mill here.",
        "# trust = high | limited  (who may mint a project, role, or label; reclaim always host)",
        "",
    ]
    for key in keys:
        if key not in data:
            continue
        val = data[key]
        if val is None:
            continue
        if isinstance(val, int):
            lines.append(f"{key} = {val}")
        else:
            text = str(val).replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'{key} = "{text}"')
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    return p


def clear_shared_node_if_owner(owner: str, *, dest=None) -> bool:
    """#489: wipe leftover config.toml node= when connecting as a desk."""
    who = (owner or "").strip()
    if not who:
        return False
    path = dest or config_path()
    data = dict(load_file(path))
    if not data.get("node"):
        return False
    data["node"] = ""
    save_config(data, path)
    return True
