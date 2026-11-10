# -*- coding: utf-8 -*-
"""Offline hop spool. Sit-end keeps the child; delivery uses reconnect backoff."""
from __future__ import annotations

import json
import sys
import time
from typing import Any

SPOOL_CAP = 8
_KEEP = frozenset({"start", "exit", "crash"})


def coalesce_key(body: dict[str, Any]) -> tuple[str, str] | tuple[str, str, str]:
    kind = str(body.get("kind") or "")
    watch_id = str(body.get("watch_id") or "")
    if kind in ("stall", "overflow"):
        return (watch_id, kind, str(body.get("cause") or ""))
    return (watch_id, kind)


def retry_delay(attempt: int, *, jitter: float | None = None) -> float:
    """Same curve as a sitting reconnect. Offline spool delivery only."""
    from agent_coord.client.ws import reconnect_delay_s

    return reconnect_delay_s(attempt, jitter=jitter)


class Spool:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []
        self.overflow = False

    def add(self, body: dict[str, Any]) -> None:
        kind = str(body.get("kind") or "")
        if kind not in _KEEP:
            key = coalesce_key(body)
            for index, old in enumerate(self.items):
                if coalesce_key(old) == key:
                    self.items[index] = dict(body)
                    return
        if len(self.items) >= SPOOL_CAP:
            self.overflow = True
            for index, old in enumerate(self.items):
                if str(old.get("kind") or "") not in _KEEP:
                    self.items.pop(index)
                    break
            else:
                return
        self.items.append(dict(body))

    def drain(self) -> list[dict[str, Any]]:
        rows = list(self.items)
        self.items.clear()
        return rows


def spool_path(desk: str):
    """Durable hop file beside the desk runs file."""
    from agent_coord.client.tw.link import _desk, pointer_path

    pointer = pointer_path(_desk(desk))
    return pointer.with_name(pointer.name + ".spool.json")


def _load_raw(desk: str) -> tuple[list[dict[str, Any]], list[str]]:
    path = spool_path(desk)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], []
    dropped: list[str] = []
    if isinstance(raw, dict):
        rows = raw.get("items")
        gone = raw.get("dropped")
        if isinstance(gone, list):
            dropped = [str(item) for item in gone if item]
    else:
        rows = raw
    if not isinstance(rows, list):
        return [], dropped[-32:]
    items = [dict(item) for item in rows if isinstance(item, dict)]
    return items, dropped[-32:]


def load_durable(desk: str) -> list[dict[str, Any]]:
    items, _dropped = _load_raw(desk)
    return items


def _save_raw(desk: str, items: list[dict[str, Any]], dropped: list[str]) -> None:
    path = spool_path(desk)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    body = {"items": items, "dropped": dropped[-32:]}
    tmp.write_text(json.dumps(body), encoding="utf-8")
    tmp.replace(path)


def save_durable(desk: str, items: list[dict[str, Any]]) -> None:
    _items, dropped = _load_raw(desk)
    _save_raw(desk, items, dropped)


def _watch(item: dict[str, Any]) -> str:
    return str(item.get("watch_id") or "")


def _kind(item: dict[str, Any]) -> str:
    return str(item.get("kind") or "")


def _open_in(items: list[dict[str, Any]], watch_id: str) -> bool:
    return any(
        _watch(item) == watch_id and _kind(item) in ("start", "crash")
        for item in items
    )


def _trim(items: list[dict[str, Any]]) -> list[str]:
    """Drop whole watches until the file fits."""
    dropped: list[str] = []
    while len(items) > SPOOL_CAP:
        oldest = _watch(items[0])
        if not oldest:
            items.pop(0)
            continue
        items[:] = [item for item in items if _watch(item) != oldest]
        if oldest not in dropped:
            dropped.append(oldest)
        if not items:
            break
    return dropped


def append_hop(desk: str, body: dict[str, Any]) -> None:
    """Keep one undelivered hop. A cap drop removes that watch, start and exit."""
    row = {
        key: value
        for key, value in body.items()
        if key not in ("verb", "type", "at")
    }
    row["at"] = time.time()
    items, dropped = _load_raw(desk)
    wid = _watch(row)
    # A start that already hit the cap. A later exit would have no start on the server.
    if _kind(row) == "exit" and wid in dropped and not _open_in(items, wid):
        return
    items.append(row)
    for gone in _trim(items):
        if gone in dropped:
            continue
        dropped.append(gone)
        print("tw: %s dropped; spool cap" % gone, file=sys.stderr)
    _save_raw(desk, items, dropped)


def remove_hops(desk: str, bodies: list[dict[str, Any]]) -> None:
    if not bodies:
        return

    def key(item: dict[str, Any]) -> tuple[str, str, str, Any]:
        return (_watch(item), _kind(item), str(item.get("cause") or ""), item.get("exit_code"))

    gone = {key(body) for body in bodies}
    save_durable(desk, [item for item in load_durable(desk) if key(item) not in gone])


def _wire(item: dict[str, Any]) -> dict[str, Any]:
    body: dict[str, Any] = {
        "verb": "tw.event",
        "watch_id": _watch(item),
        "kind": _kind(item),
    }
    if item.get("cause"):
        body["cause"] = item["cause"]
    if item.get("exit_code") is not None:
        body["exit_code"] = item["exit_code"]
    if item.get("wake") is False:
        body["wake"] = False
    try:
        elapsed = int((time.time() - float(item.get("at") or 0)) * 1000)
    except (TypeError, ValueError):
        elapsed = 0
    if elapsed < 0:
        elapsed = 0
    body["counts"] = {"replay": 1, "elapsed_ms": elapsed}
    return body


def _outcome(got: Any) -> str:
    if not isinstance(got, dict):
        return "down"
    if got.get("ok") is True:
        return "ok"
    result = got.get("result")
    if isinstance(result, dict) and result.get("ok") is True:
        return "ok"
    code = got.get("code")
    if not code and isinstance(result, dict):
        code = result.get("code")
    if code == "cap":
        return "cap"
    return "down"


def replay(desk: str) -> None:
    """Send the durable file once, in order. A transport error keeps the rest."""
    items, dropped = _load_raw(desk)
    if not items:
        return
    from agent_coord.client.http import mill_http_call

    changed = False
    index = 0
    while index < len(items):
        item = items[index]
        wid = _watch(item)
        if _kind(item) == "exit" and wid in dropped and not _open_in(items, wid):
            items.pop(index)
            changed = True
            continue
        try:
            outcome = _outcome(mill_http_call(_wire(item)))
        except Exception:
            outcome = "down"
        if outcome == "ok":
            items.pop(index)
            changed = True
            continue
        if outcome == "cap":
            items = [row for row in items if _watch(row) != wid]
            if wid and wid not in dropped:
                dropped.append(wid)
                print("tw: %s dropped; spool cap" % wid, file=sys.stderr)
            changed = True
            index = 0
            continue
        if wid:
            print(
                "%s spooled; replays on next mill connect" % wid,
                file=sys.stderr,
            )
        break
    if changed:
        _save_raw(desk, items, dropped)
