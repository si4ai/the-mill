"""#220: pane cache keys follow table versions. Reads and push do not bump."""
from __future__ import annotations

from pathlib import Path

from agent_coord.server import score_system
from agent_coord.server import table_ver
from agent_coord.server.middleware import _FLOOR_TTL, cached_read
import agent_coord.server.middleware as mw


def test_reads_and_push_do_not_bump() -> None:
    assert table_ver.tables_for_proc("mill_mail_select") == ()
    assert table_ver.tables_for_proc("mill_mail_get") == ()
    assert table_ver.tables_for_proc("mill_mail_list") == ()
    assert table_ver.tables_for_proc("mill_tree_subtree") == ()
    assert table_ver.tables_for_proc("mill_activity_bucket") == ()
    assert table_ver.tables_for_proc("mill_push_put") == ()
    assert table_ver.tables_for_proc("mill_wall_event") == ()
    assert table_ver.tables_for_proc("mill_floor_part") == ()


def test_a_mail_write_bumps_mail_and_the_stamp_changes() -> None:
    assert table_ver.tables_for_proc("mill_mail_insert") == ("mail", "mail_to")
    assert table_ver.tables_for_proc("mill_mail_open") == ("mail_to",)
    before = table_ver.version_stamp(("mail", "mail_to"))
    mail_n = table_ver.version_of("mail")
    table_ver.bump(table_ver.tables_for_proc("mill_mail_insert"))
    assert table_ver.version_of("mail") == mail_n + 1
    assert table_ver.version_of("mail_to") >= 1
    assert table_ver.version_stamp(("mail", "mail_to")) != before
    assert table_ver.version_stamp(table_ver.PANE_TABLES["mailbox"]) != before


def test_pane_cache_keeps_a_hit_without_a_time_limit(monkeypatch) -> None:
    mw._floor_cache.clear()
    clock = {"n": 1000.0}
    monkeypatch.setattr(mw.time, "monotonic", lambda: clock["n"])
    body, hit = cached_read("pane-220", lambda: b"a", ttl=None)
    assert body == b"a" and hit is False
    clock["n"] += 120.0
    body, hit = cached_read("pane-220", lambda: b"b", ttl=None)
    assert body == b"a" and hit is True
    assert _FLOOR_TTL == 30.0


def test_default_cache_still_expires_at_thirty_seconds(monkeypatch) -> None:
    mw._floor_cache.clear()
    clock = {"n": 5000.0}
    monkeypatch.setattr(mw.time, "monotonic", lambda: clock["n"])
    cached_read("rail-220", lambda: b"a")
    clock["n"] += 31.0
    body, hit = cached_read("rail-220", lambda: b"b")
    assert body == b"b" and hit is False


def test_enqueue_does_not_open_the_book(monkeypatch) -> None:
    score_system._wall_q.clear()

    def _no(*_a, **_k):
        raise AssertionError("book")

    monkeypatch.setattr("agent_coord.server.records.db.connect", _no)
    score_system.enqueue_wall("/api/v1/rooms?project=the-mill", 12.0)
    score_system.enqueue_wall("/api/mill/send", 3.0)
    assert score_system._wall_q == [("/api/v1", 12.0)]


def test_flush_uses_one_connection(monkeypatch) -> None:
    opened = {"n": 0}

    class _Cn:
        def close(self) -> None:
            return None

    def _connect():
        opened["n"] += 1
        return _Cn()

    seen: list = []

    def _note(route, ms=0.0, *, cn=None, now=None):
        seen.append((route, ms, cn))

    monkeypatch.setattr("agent_coord.server.records.db.connect", _connect)
    monkeypatch.setattr(score_system, "note_wall", _note)
    score_system._wall_q[:] = [("/api/v1/rooms", 1.0), ("/api/v1/mailbox", 2.0)]
    assert score_system.flush_wall() == 2
    assert opened["n"] == 1
    assert [row[0] for row in seen] == ["/api/v1/rooms", "/api/v1/mailbox"]
    assert seen[0][2] is seen[1][2]
    assert score_system._wall_q == []


def test_f13_names_the_lan_wall_latency_row() -> None:
    path = Path(__file__).resolve().parents[2] / "docs" / "protocol" / "profiler.md"
    text = path.read_text(encoding="utf-8")
    row = next(line for line in text.splitlines() if "F13" in line)
    assert "lan-wall-latency" in row
    assert "token" not in row.lower()
