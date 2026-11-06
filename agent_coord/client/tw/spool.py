# -*- coding: utf-8 -*-
"""Offline hop spool. Sit-end keeps the child; delivery uses reconnect backoff."""
from __future__ import annotations

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
