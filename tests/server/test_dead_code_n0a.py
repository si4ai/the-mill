"""N0a: dead code is gone and the live paths it shadowed still work."""
from __future__ import annotations

import re
from pathlib import Path

from agent_coord.install.migrate import sql_dir
from agent_coord.server.admin import door
from agent_coord.server.records import opened, todo

_CREATE = re.compile(r"CREATE\s+(?:FUNCTION|PROCEDURE)\s+(\w+)", re.I)


def _creates(name: str) -> list[str]:
    return _CREATE.findall((sql_dir() / name).read_text(encoding="utf-8-sig"))


def _sql(name: str) -> str:
    return (sql_dir() / name).read_text(encoding="utf-8-sig")


def test_mill_name_alias_is_gone_and_still_dropped_on_upgrade() -> None:
    assert "MILL_NAME" not in _creates("fn_name.sql")
    assert "DROP FUNCTION IF EXISTS MILL_NAME;" in _sql("fn_name.sql")


def test_opened_shims_are_gone_and_still_dropped_on_upgrade() -> None:
    assert _creates("sp_opened.sql") == ["mill_mail_open"]
    for proc in ("mill_opened_insert", "mill_opened_select"):
        assert f"DROP PROCEDURE IF EXISTS {proc};" in _sql("sp_opened.sql")


def test_opened_insert_calls_mill_mail_open_and_pushes_the_receipt(monkeypatch) -> None:
    seen: dict = {}

    def fake_call(cn, name, args):
        seen["call"] = (name, list(args))
        return [{"push_receipt": 1, "id": 7}]

    monkeypatch.setattr(opened, "call", fake_call)
    monkeypatch.setattr(
        "agent_coord.server.mail_push.push_receipt", lambda cn, row: seen.setdefault("push", row)
    )
    rows = opened.insert(object(), 7, "builder")
    assert seen["call"] == ("mill_mail_open", [7, "builder"])
    assert seen["push"] == {"push_receipt": 1, "id": 7}
    assert rows == [{"push_receipt": 1, "id": 7}]
    assert not hasattr(opened, "select")


def test_next_status_is_gone() -> None:
    assert not hasattr(todo, "next_status")
    assert todo.progress_is_done("100%") is True


class _Cur:
    with_rows = True

    def __init__(self, log: list[str], rows: list) -> None:
        self.log, self.rows, self.rowcount = log, rows, 1

    def execute(self, sql, args=()) -> None:
        self.log.append(sql)

    def fetchall(self):
        # #867: an invite write is a CALL that answers with its row count.
        return [(1,)] if self.log[-1].startswith("CALL") else self.rows

    def nextset(self):
        return None

    def close(self) -> None:
        pass


class _Cn:
    def __init__(self, log: list[str], rows: list) -> None:
        self.log, self.rows = log, rows

    def cursor(self):
        return _Cur(self.log, self.rows)

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass


_GONE = re.compile(r"\bagent_(human|grant|vouch)\w*", re.I)


def test_revoke_and_join_touch_no_undefined_tables(monkeypatch) -> None:
    log: list[str] = []
    rows = [("human", "h1"), ("agent", "a1")]
    monkeypatch.setattr(door, "_db", lambda: _Cn(log, rows))
    out = door.revoke_key("k1")
    assert out["cohort_humans"] == ["h1"] and out["cohort_agents"] == ["a1"]
    assert door.record_join("k1", "human", "h1") is True
    assert log and not [s for s in log if _GONE.search(s)]
    assert not _GONE.search(Path(door.__file__).read_text(encoding="utf-8"))
    assert not hasattr(door, "_purge_humans")


def test_name_type_keeps_its_guarded_migration_trigger() -> None:
    """D8 is not a duplicate: the first trigger keeps name watchers while the
    backfill deletes name activity rows; the second restores tables.sql's body."""
    blob = _sql("name_type.sql")
    assert blob.count("CREATE TRIGGER activity_del_watchers") == 2
    assert "@mill_keep_name_watchers = 1" in blob
    assert _sql("tables.sql").count("CREATE TRIGGER activity_del_watchers") == 1
