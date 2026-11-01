"""F-log-rotation: dest_log rotates by size, keeps dated copies, drops past retention (#797)."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agent_coord.server import log_rotate as lr
from agent_coord.server import push


def test_write_past_size_makes_a_dated_copy_and_restarts_live(tmp_path, monkeypatch):
    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)
    monkeypatch.setattr(
        "agent_coord.config.settings",
        lambda path=None: {"log_max_bytes": 200, "log_retain_days": 30},
    )
    live = tmp_path / "mill-api.log"
    push.dest_log("mill-api.log", "x" * 80)
    push.dest_log("mill-api.log", "y" * 80)
    push.dest_log("mill-api.log", "z" * 80)  # crosses cap
    assert live.is_file()
    copies = sorted(tmp_path.glob("mill-api.log.*"))
    assert copies, "expected a dated rotated copy"
    assert live.stat().st_size < 200
    # live still receives writes after rotation
    push.dest_log("mill-api.log", "after")
    assert "after" in live.read_text(encoding="utf-8")


def test_copies_past_retention_are_deleted(tmp_path, monkeypatch):
    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)
    monkeypatch.setattr(lr, "RETAIN_DAYS", 2)
    old = tmp_path / "mill-api.log.19990101"
    old.write_text("old\n", encoding="utf-8")
    # stamp mtime far in the past
    old_ts = (datetime.now(timezone.utc) - timedelta(days=10)).timestamp()
    os.utime(old, (old_ts, old_ts))
    live = tmp_path / "mill-api.log"
    live.write_text("live\n", encoding="utf-8")
    lr.sweep_retention(tmp_path, "mill-api.log")
    assert not old.exists()
    assert live.exists()


def test_log_texts_include_latest_rotated_copy(tmp_path):
    live = tmp_path / "mill-perf.log"
    rot = tmp_path / "mill-perf.log.20260101"
    live.write_text("live-line\n", encoding="utf-8")
    rot.write_text("rot-line\n", encoding="utf-8")
    text = lr.read_log_text(tmp_path, "mill-perf.log")
    assert "live-line" in text and "rot-line" in text


def test_rotate_while_live_file_is_held_open(tmp_path, monkeypatch):
    """copytruncate: another open handle must still see a truncated live file."""
    monkeypatch.setattr(lr, "MAX_BYTES", 100)
    live = tmp_path / "mill-backchannel.log"
    live.write_text("a" * 150, encoding="utf-8")
    with live.open("a", encoding="utf-8") as held:
        held.write("")
        held.flush()
        lr.rotate_if_needed(live)
        held.write("post\n")
        held.flush()
    copies = list(tmp_path.glob("mill-backchannel.log.*"))
    assert copies
    # live was truncated then received post
    body = live.read_text(encoding="utf-8")
    assert "post" in body
