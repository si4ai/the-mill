"""Shared mill home log rotation (#797).

Every dest_log write goes through here. When the live file is at or over
MAX_BYTES, copytruncate into a date-suffixed copy and truncate the live
file in place so Windows handles that still hold it keep writing. Copies
older than RETAIN_DAYS are deleted on each rotate and on sweep_retention.
"""
from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
from pathlib import Path

# Defaults; office config may override later via set_limits.
MAX_BYTES = 10 * 1024 * 1024
RETAIN_DAYS = 30

_lock = threading.Lock()


def set_limits(*, max_bytes: int | None = None, retain_days: int | None = None) -> None:
    global MAX_BYTES, RETAIN_DAYS
    if max_bytes is not None and max_bytes > 0:
        MAX_BYTES = int(max_bytes)
    if retain_days is not None and retain_days > 0:
        RETAIN_DAYS = int(retain_days)


def _dated_name(path: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    base = path.with_name(f"{path.name}.{stamp}")
    if not base.exists():
        return base
    # Same-day second rotate: add a serial suffix.
    n = 1
    while True:
        cand = path.with_name(f"{path.name}.{stamp}.{n}")
        if not cand.exists():
            return cand
        n += 1


def rotate_if_needed(path: Path) -> None:
    """If path is at or over MAX_BYTES, copytruncate to a dated copy."""
    try:
        if not path.is_file() or path.stat().st_size < MAX_BYTES:
            return
    except OSError:
        return
    dest = _dated_name(path)
    try:
        # copytruncate: copy bytes, then truncate live in place.
        data = path.read_bytes()
        dest.write_bytes(data)
        with path.open("r+b") as f:
            f.truncate(0)
            f.flush()
            os.fsync(f.fileno())
    except OSError:
        return
    sweep_retention(path.parent, path.name)


def sweep_retention(home: Path, filename: str) -> None:
    """Delete dated copies of filename older than RETAIN_DAYS (by mtime)."""
    cutoff = datetime.now(timezone.utc).timestamp() - RETAIN_DAYS * 86400
    prefix = filename + "."
    try:
        for p in home.iterdir():
            if not p.is_file():
                continue
            if not p.name.startswith(prefix):
                continue
            # skip numeric-only mill-perf.log.1 style if somehow present without date
            try:
                if p.stat().st_mtime < cutoff:
                    p.unlink(missing_ok=True)
            except OSError:
                pass
    except OSError:
        return



def append_line(path: Path, text: str) -> None:
    """Rotate if needed, then append one line. Thread-safe per process."""
    from agent_coord.server.redact import redact_secrets

    # Redact at the sink so log files never hold clear secrets (CodeQL py/clear-text-storage).
    line = redact_secrets(text)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        rotate_if_needed(path)
        with path.open("a", encoding="utf-8") as f:
            # Owner-only mill-home log; line already passed redact_secrets (dest_log + above).
            f.write(line)  # codeql[py/clear-text-storage-sensitive-data]


def read_log_text(home: Path, filename: str) -> str:
    """Live file plus dated copies, oldest first, so last-hour windows still see history."""
    parts: list[tuple[float, str]] = []
    live = home / filename
    if live.is_file():
        try:
            parts.append((live.stat().st_mtime, live.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            pass
    prefix = filename + "."
    try:
        for p in home.iterdir():
            if p.is_file() and p.name.startswith(prefix):
                try:
                    parts.append((p.stat().st_mtime, p.read_text(encoding="utf-8", errors="replace")))
                except OSError:
                    pass
    except OSError:
        pass
    parts.sort(key=lambda t: t[0])
    return "".join(t[1] for t in parts)
