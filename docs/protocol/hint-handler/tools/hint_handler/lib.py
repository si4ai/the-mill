"""hint_handler.lib - stdin HINT JSON -> event; thin mill-fetch leftovers.

Protocol facts (do not invent):
- route key matches client route_chain.route_key: explicit route, else
  mail:MAIL for {kind: mail}, else type:hint
- detail = watcher.hint or cheap default JSON (hints.md). A letter has none.
- MAIL leftovers -> mill inbox; TODO -> that card only (not full board)
- exit 0 -> STOP; mill connect does not mill-update (connect.md)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence


@dataclass
class HintEvent:
    type: str
    id: Any
    hint: str
    detail: Any
    raw: Mapping[str, Any]

    @property
    def route_key(self) -> str:
        return f"{self.type}:{self.hint}"

    @property
    def ignore(self) -> bool:
        # route.md / hints.md: PING never routed; DOING ignore
        h = self.hint.upper()
        return h in ("", "PING", "DOING") or self.type in ("heartbeat", "doing")


def parse_stdin(raw: Optional[str] = None) -> HintEvent:
    text = sys.stdin.read() if raw is None else raw
    try:
        obj = json.loads(text or "{}")
    except json.JSONDecodeError as e:
        raise ValueError(f"HINT stdin not JSON: {e}") from e
    if not isinstance(obj, dict):
        raise ValueError("HINT stdin must be a JSON object")
    return parse_hint(obj)


def _client_route_key(obj: Mapping[str, Any]) -> str:
    """Same rule as agent_coord.client.route_chain.route_key."""
    got = str(obj.get("route") or "").strip()
    if got:
        return got
    kind = str(obj.get("kind") or "").strip().lower()
    if kind == "mail":
        return "mail:MAIL"
    typ = str(obj.get("type") or "").strip()
    hint = str(obj.get("hint") or "").strip()
    if typ and hint:
        return f"{typ}:{hint}"
    return hint or typ or ""


def parse_hint(obj: Mapping[str, Any]) -> HintEvent:
    """Route key matches route_key in client/route_chain.py."""
    key = _client_route_key(obj)
    if ":" in key:
        typ, hint = key.split(":", 1)
        typ, hint = typ.strip(), hint.strip()
    else:
        typ = str(obj.get("type") or "").strip()
        hint = (key or str(obj.get("hint") or "")).strip()
    hint = hint.upper()
    detail = obj.get("detail")
    if isinstance(detail, str):
        # Default detail is cheap JSON string or object - try parse
        s = detail.strip()
        if s.startswith("{") or s.startswith("["):
            try:
                detail = json.loads(s)
            except json.JSONDecodeError:
                pass
    return HintEvent(
        type=typ,
        id=obj.get("id"),
        hint=hint,
        detail=detail,
        raw=dict(obj),
    )


def _owner_project(ev: HintEvent) -> tuple[str, str]:
    owner = (
        os.environ.get("AGENT_COORD_OWNER")
        or str(ev.raw.get("desk") or "")
        or ""
    ).strip()
    project = os.environ.get("AGENT_COORD_PROJECT") or "the-mill"
    return owner, project


def run_mill(argv: Sequence[str], *, timeout: float = 30.0) -> subprocess.CompletedProcess[str]:
    """Thin wrapper: prefer `mill` on PATH; fall back to `python -m agent_coord`."""
    env = os.environ.copy()
    cmd = ["mill", *argv]
    try:
        return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return subprocess.run(
            [sys.executable, "-m", "agent_coord", *argv],
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )


def _detail_sufficient(ev: HintEvent) -> bool:
    """True when detail already carries recipe fields beyond cheap default crumbs."""
    d = ev.detail
    if d is None or d == "":
        return False
    if isinstance(d, str):
        s = d.strip()
        # Non-JSON recipe string (e.g. "need,status") is a hint to fetch - not body.
        if not (s.startswith("{") or s.startswith("[")):
            return False
        try:
            d = json.loads(s)
        except json.JSONDecodeError:
            return False
    if not isinstance(d, dict):
        return bool(d)
    # Cheap default keys alone are not enough to do the job (hints.md / route.md).
    cheap = {"what", "id", "when", "state", "watchers", "tree"}
    extra = set(d.keys()) - cheap
    return bool(extra)


def leftovers(ev: HintEvent) -> str:
    """mill-fetch only leftovers per route.md / hints.md. Returns stdout text.

    MAIL -> mill inbox (unread; not "only id")
    TODO -> prefer detail; if insufficient, do **not** dump full `mill todo` board -
            return "" and let the task narrow to `ev.id` (that card). mill todo CLI
            lists the board; one-card fetch is the handler's job.
    HOLD/SCORE/NAME -> empty string (caller decides; no auto-fetch dump)
    """
    if ev.ignore:
        return ""
    owner, project = _owner_project(ev)
    h = ev.hint.upper()
    if h == "MAIL":
        if _detail_sufficient(ev):
            return json.dumps(ev.detail) if not isinstance(ev.detail, str) else ev.detail
        if not owner:
            log("leftovers: set AGENT_COORD_OWNER for inbox")
            return ""
        r = run_mill(["inbox", "--limit", "3"])
        if r.returncode:
            log(r.stderr or f"inbox rc={r.returncode}")
        return r.stdout or ""
    if h == "TODO":
        if _detail_sufficient(ev):
            return json.dumps(ev.detail) if not isinstance(ev.detail, str) else ev.detail
        # Do not dump full mill todo board (hints.md / route.md: that card only).
        # Return "" so the task handler narrows with ev.id.
        log(f"leftovers: TODO id={ev.id} - no full board; task narrows to that card")
        return ""
    return ""


def log(msg: str) -> None:
    print(f"hint_handler: {msg}", file=sys.stderr, flush=True)


def exit_ok() -> int:
    return 0


def exit_err(code: int = 1) -> int:
    return int(code)
