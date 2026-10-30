# -*- coding: utf-8 -*-
"""Door invite mint: unset TTL defaults to 24h; seat path unchanged."""
from __future__ import annotations

from datetime import datetime, timedelta
from agent_coord.server.admin import door


class _FakeCur:
    with_rows = True  # an invite SP answers with its row count (#867)

    def __init__(self):
        self.rowcount = 1

    def execute(self, *_a, **_k):
        return None

    def fetchall(self):
        return [(1,)]

    def nextset(self):
        return None

    def close(self):
        return None


class _FakeCn:
    def __init__(self):
        self.committed = False
        self.rolled = False

    def cursor(self, dictionary=False):
        return _FakeCur()

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled = True

    def close(self):
        return None


def test_parse_ttl_empty_still_never() -> None:
    """parse_ttl itself keeps empty/0/never as no expiry (set_key_ttl / escape)."""
    assert door.parse_ttl(None) == (None, None)
    assert door.parse_ttl("") == (None, None)
    assert door.parse_ttl(0) == (None, None)
    assert door.parse_ttl("never") == (None, None)
    assert door.parse_ttl("0") == (None, None)


def test_parse_ttl_24h() -> None:
    secs, exp = door.parse_ttl("24h")
    assert secs == 86400
    assert exp is not None
    assert abs((exp - door._now()) - timedelta(hours=24)) < timedelta(seconds=2)


def test_mint_key_unset_ttl_defaults_24h(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(door, "_db", lambda: _FakeCn())
    monkeypatch.setattr(door, "hash_path", lambda: tmp_path / "door.hash")
    before = door._now()
    row = door.mint_key(label="ttl-default", created_by="test", sync_legacy=False)
    assert row["ok"] is True
    assert row["ttl_seconds"] == 86400
    assert row["expires_at"] is not None
    exp = datetime.fromisoformat(row["expires_at"])
    delta = exp - before
    assert timedelta(hours=23, minutes=59) <= delta <= timedelta(hours=24, minutes=1)


def test_mint_key_empty_string_ttl_defaults_24h(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(door, "_db", lambda: _FakeCn())
    monkeypatch.setattr(door, "hash_path", lambda: tmp_path / "door.hash")
    row = door.mint_key(label="empty", created_by="test", ttl="", sync_legacy=False)
    assert row["ttl_seconds"] == 86400
    assert row["expires_at"] is not None


def test_mint_key_explicit_never_escape(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(door, "_db", lambda: _FakeCn())
    monkeypatch.setattr(door, "hash_path", lambda: tmp_path / "door.hash")
    row = door.mint_key(label="never", created_by="test", ttl="never", sync_legacy=False)
    assert row["ttl_seconds"] is None
    assert row["expires_at"] is None


def test_mint_key_explicit_0_escape(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(door, "_db", lambda: _FakeCn())
    monkeypatch.setattr(door, "hash_path", lambda: tmp_path / "door.hash")
    row = door.mint_key(label="zero", created_by="test", ttl=0, sync_legacy=False)
    assert row["ttl_seconds"] is None
    assert row["expires_at"] is None


def test_mint_key_explicit_7d(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(door, "_db", lambda: _FakeCn())
    monkeypatch.setattr(door, "hash_path", lambda: tmp_path / "door.hash")
    row = door.mint_key(label="week", created_by="test", ttl="7d", sync_legacy=False)
    assert row["ttl_seconds"] == 7 * 86400


def test_set_key_ttl_still_allows_never(monkeypatch) -> None:
    """Admin set_key_ttl left as-is: never remains valid."""
    seen = {}

    class Cur(_FakeCur):
        def execute(self, sql, args=None):
            seen["sql"] = sql
            seen["args"] = args

    class Cn(_FakeCn):
        def cursor(self, dictionary=False):
            return Cur()

    monkeypatch.setattr(door, "_db", lambda: Cn())
    out = door.set_key_ttl("abcd1234", "never")
    assert out["ok"] is True
    assert out["ttl_seconds"] is None
    assert out["expires_at"] is None
    assert seen["args"][0] == "abcd1234"
    assert seen["args"] == ("abcd1234", None)  # cmd_invite_ttl(key, ttl): NULL never expires


def test_default_invite_ttl_const() -> None:
    assert door.DEFAULT_INVITE_TTL == "24h"
