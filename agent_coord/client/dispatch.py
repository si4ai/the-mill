# -*- coding: utf-8 -*-
"""Desk-side HINT dispatch. One frame, one choice.

A route hit runs that program (the desk may be busy; this does not wait).
No route wakes the vendor agent. An empty route value does neither.
The frame is the small Hub push: no token, no letter, no card body.
"""
from __future__ import annotations

import json
import threading
from typing import Any

DETAIL_MAX = 4096
_KEEP = ("type", "id", "hint", "detail", "desk", "route", "verb", "idem", "kind")
_SEEN: set[str] = set()
_SEEN_MAX = 4096
_SEEN_LOCK = threading.Lock()


def _secret_key(key: str) -> bool:
    s = str(key or "").lower().replace("-", "_")
    if s in {"token", "authorization", "password", "secret", "bearer", "cookie", "access_token"}:
        return True
    return s.endswith("_token") or "password" in s


def _cap_detail(detail: Any) -> Any:
    if isinstance(detail, str):
        return detail[:DETAIL_MAX]
    if isinstance(detail, dict):
        clean = {k: v for k, v in detail.items() if not _secret_key(str(k))}
        raw = json.dumps(clean, default=str, separators=(",", ":"))
        if len(raw) <= DETAIL_MAX:
            return clean
        return raw[:DETAIL_MAX]
    return detail


def public_frame(msg: dict[str, Any] | None, desk: str = "") -> dict[str, Any]:
    """Fields a redirector or wake may see. Drops secrets and unknown keys."""
    src = dict(msg or {})
    out: dict[str, Any] = {}
    for key in _KEEP:
        if key not in src or src[key] is None:
            continue
        if key == "detail":
            out["detail"] = _cap_detail(src[key])
        elif key == "desk":
            continue
        elif _secret_key(key):
            continue
        else:
            out[key] = src[key]
    who = (desk or str(src.get("desk") or "")).strip()
    if who:
        out["desk"] = who.strip()
    return out


def _duplicate(frame: dict[str, Any]) -> bool:
    """True when this process already handled the poke's idempotency key."""
    key = str(frame.get("idem") or "").strip()
    if not key:
        return False
    with _SEEN_LOCK:
        if key in _SEEN:
            return True
        if len(_SEEN) >= _SEEN_MAX:
            _SEEN.clear()
        _SEEN.add(key)
        return False


def _log_field(raw: object) -> str:
    """One mill-perf field. Spaces would split the line."""
    text = str(raw or "").replace("\n", " ").replace("\r", " ").strip()
    return text.replace(" ", "_")[:80]


def _stamp_dispatch(decision: str, frame: dict[str, Any], vendor: str = "") -> None:
    """A7 stamp. One line, no duration field: op=hint.dispatch decision= key= idem= vendor=."""
    try:
        from agent_coord.client.route_chain import route_key
        from agent_coord.server.push import dest_log

        dest_log(
            "mill-perf.log",
            "op=hint.dispatch decision=%s key=%s idem=%s vendor=%s"
            % (
                _log_field(decision),
                _log_field(route_key(frame)),
                _log_field(frame.get("idem")),
                _log_field(vendor),
            ),
        )
    except Exception:
        pass


def expected_key(desk: str, frame: dict[str, Any]) -> str:
    """The poke key the wall stamps on this frame for this desk (#618): hint or letter."""
    from agent_coord.server.poke_key import hint_key, letter_key

    try:
        num = int(frame.get("id") or 0)
    except (TypeError, ValueError):
        return ""
    if str(frame.get("kind") or "").lower() == "mail":
        return letter_key(num, desk)
    typ = str(frame.get("type") or "").strip()
    return hint_key(typ, num, desk) if typ and num else ""


def dispatch_hint(desk: str, msg: dict[str, Any], *, replay: bool = False) -> str:
    """work | wake | suppress | skip | left.

    replay (#618): a frame the connect sync handed over (missed while away, or rung
    by a webhook doorbell). Same walk and key check; when no route takes it, it is
    left for the agent reading the sync line ("left"), never a vendor poke: the
    desk is already awake.

    work: a redirector handled the frame. The vendor does not run.
    wake: every redirector returned next. Vendor poke rang a chat-wake path.
    sit-exit: vendor poke could not ring a chat (stamp-only); plain connect
    should exit like connect-wait so a foreground chat wakes (card 985).
    suppress: an empty route value stopped the chain.
    skip: PING, a DOING with no route (chart: ignore, no vendor poke),
    a repeated idempotency key, or this desk's HINT filter file (want) said no.
    The idempotency key is checked before the chain. PING never enters it.
    Each return appends one hint.dispatch line to mill-perf.log.
    """
    frame = public_frame(msg, desk)
    hint = str(frame.get("hint") or "")

    def finish(decision: str, vendor: str = "") -> str:
        _stamp_dispatch(decision, frame, vendor)
        return decision

    if hint == "PING":
        return finish("skip")
    from agent_coord.client.watch_filter import wants

    if not wants(desk, frame):
        return finish("skip")
    if _duplicate(frame):
        return finish("skip")
    from agent_coord.client.route_chain import try_route

    decision = try_route(desk, frame)
    if decision == "handled":
        from agent_coord.client.vendor import session_vendor

        return finish("work", session_vendor() or "")
    if decision == "suppress":
        return finish("suppress")
    if hint == "DOING":
        return finish("skip")
    if replay:
        return finish("left")
    from agent_coord.client.connectors import poke
    from agent_coord.client.vendor import session_vendor

    vendor = session_vendor() or "grok-build"
    # Stamp wake before poke (existing freeze/ordering contract), then correct
    # to sit-exit when the poke could not ring a chat (card 985).
    _stamp_dispatch("wake", frame, vendor)
    rang = poke(vendor, frame)
    if rang is False:
        return finish("sit-exit", vendor)
    return "wake"


def replay_items(desk: str, sync: list[Any]) -> list[dict[str, Any]]:
    """Sync rows the chain should walk (#618): hints and letters that were missed.

    A row the socket delivered live (sent) was walked then. A route exit notice
    (exit) and an expired line are reports, not frames. Each kept frame carries
    the poke key the wall would have stamped, so the walk's key check is the same.

    #670: one frame per poke key, the latest, in the order the keys first appear.
    Rows with one key are one item (every change of one hold), so the chain would
    skip all but the first as a repeat anyway; walking the latest hands it the
    current state, once.
    """
    by_key: dict[str, dict[str, Any]] = {}
    for row in sync or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("outcome") or "") != "missed":
            continue
        kind = str(row.get("kind") or "").lower()
        if kind not in ("hint", "mail") or "exit" in row:
            continue
        frame = {k: v for k, v in row.items() if k not in ("outcome", "time")}
        if kind == "hint":
            frame.pop("kind", None)
        key = expected_key(desk, frame)
        if not key:
            continue
        frame["idem"] = key
        frame["replay"] = 1
        by_key[key] = frame  # a repeat keeps the key's first position, takes the latest frame
    return list(by_key.values())
