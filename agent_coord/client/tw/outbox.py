# -*- coding: utf-8 -*-
"""Local hop file for one desk. connect writes it, then sends to the host."""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any


def _reject(text: str) -> None:
    """WAL needs a native local disk. Not a 9p mount and not a network share."""
    folded = text.replace("\\", "/")
    if folded.startswith("//") or "/mnt/" in folded:
        raise OSError("hop file must stay on the native local filesystem")


def native_path(path: Path) -> None:
    _reject(str(path))


def outbox_path(desk: str) -> Path:
    from agent_coord.client.tw.link import _desk, pointer_path

    pointer = pointer_path(_desk(desk))
    return pointer.with_name(pointer.name + ".hops.sqlite")


def _parse(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    raw = item.get("counts")
    if isinstance(raw, str) and raw:
        try:
            item["counts"] = json.loads(raw)
        except ValueError:
            item["counts"] = None
    else:
        item["counts"] = None
    return item


class Outbox:
    def __init__(self, path: Path) -> None:
        native_path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path), timeout=5.0, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA busy_timeout=5000")
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS hop (
                id INTEGER PRIMARY KEY,
                watch_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                cause TEXT,
                exit_code INTEGER,
                wake INTEGER,
                counts TEXT,
                desk TEXT,
                card INTEGER
            )
            """
        )
        self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def add(self, body: dict[str, Any]) -> int:
        counts = body.get("counts")
        card = body.get("card")
        if isinstance(card, bool) or not isinstance(card, int):
            card = None
        desk = body.get("desk")
        if not isinstance(desk, str) or not desk.strip():
            desk = None
        with self._lock:
            cur = self._db.execute(
                """
                INSERT INTO hop (
                    watch_id, kind, cause, exit_code, wake, counts, desk, card
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(body.get("watch_id") or ""),
                    str(body.get("kind") or ""),
                    body.get("cause"),
                    body.get("exit_code"),
                    0 if body.get("wake") is False else None,
                    json.dumps(counts) if isinstance(counts, dict) else None,
                    desk,
                    card,
                ),
            )
            self._db.commit()
            return int(cur.lastrowid or 0)

    def peek(self) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute(
                """
                SELECT id, watch_id, kind, cause, exit_code, wake, counts, desk, card
                FROM hop ORDER BY id LIMIT 1
                """
            ).fetchone()
        if row is None:
            return None
        return _parse(row)

    def next_row(self, skip: set[str]) -> dict[str, Any] | None:
        with self._lock:
            rows = self._db.execute(
                """
                SELECT id, watch_id, kind, cause, exit_code, wake, counts, desk, card
                FROM hop ORDER BY id
                """
            ).fetchall()
        for row in rows:
            item = _parse(row)
            if item["watch_id"] in skip:
                continue
            return item
        return None

    def drop(self, row_id: int) -> None:
        with self._lock:
            self._db.execute("DELETE FROM hop WHERE id = ?", (int(row_id),))
            self._db.commit()


def _post_body(item: dict[str, Any]) -> dict[str, Any]:
    body: dict[str, Any] = {
        "verb": "tw.event",
        "watch_id": item["watch_id"],
        "kind": item["kind"],
    }
    if item.get("desk"):
        body["desk"] = item["desk"]
    if item.get("card") is not None:
        body["card"] = item["card"]
    if item.get("cause"):
        body["cause"] = item["cause"]
    if item.get("exit_code") is not None:
        body["exit_code"] = item["exit_code"]
    if item.get("wake") == 0:
        body["wake"] = False
    if isinstance(item.get("counts"), dict):
        body["counts"] = item["counts"]
    return body


def send_pending(box: Outbox, call) -> str:
    """Send one row. ok deletes it. A capped start is skipped for this pass.

    busy or a transport error keeps the row. The local id is not sent.
    """
    skipped: set[str] = set()
    while True:
        item = box.next_row(skipped)
        if item is None:
            return "cap" if skipped else "empty"
        body = _post_body(item)
        try:
            got = call(body)
        except Exception:
            return "down"
        if isinstance(got, dict) and got.get("ok") is True:
            box.drop(int(item["id"]))
            return "ok"
        code = str(got.get("code") or "") if isinstance(got, dict) else ""
        msg = str(got.get("msg") or "") if isinstance(got, dict) else ""
        if code == "cap" and str(item.get("kind") or "") == "start":
            skipped.add(str(item.get("watch_id") or ""))
            continue
        if code == "cap":
            return "cap"
        if code == "busy" or "busy" in msg.casefold() or "slow" in msg.casefold():
            return "busy"
        return "down"
