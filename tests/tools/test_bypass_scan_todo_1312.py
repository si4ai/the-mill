"""Card 1312, slice 3 (card status): the bypass scan reads todo.status, assigned_id and claimed_at.

A direct UPDATE of card status or the volunteer outside the todo write code is a finding; card
text and the acceptance line (body, meta, done_when) are not card status; the todo write
procedures and todo_activity.py are the entry points.
"""
from __future__ import annotations

import json

import pytest

from tools import bypass_scan as bs

SQL_ENTRY = "agent_coord/server/sql/sp_todo.sql"
SQL_OTHER = "agent_coord/server/sql/sp_cmd.sql"
PY_ENTRY = "agent_coord/server/todo_activity.py"
PY_OTHER = "agent_coord/server/api/mill/rpc.py"


def proc(body: str) -> str:
    return f"CREATE PROCEDURE cmd_x(IN p BIGINT)\nBEGIN\n  {body}\nEND //\n"


def found(path, text):
    return [(w.protocol, w.kind) for w in bs.scan_sql(path, text) if w.protocol == "todo"]


@pytest.mark.parametrize("stmt", [
    "UPDATE todo SET status = 'done' WHERE id = p;",
    "UPDATE todo SET assigned_id = NULL WHERE id = p;",
    "UPDATE todo SET claimed_at = NOW(6), updated = updated WHERE id = p;",
    "UPDATE todo SET body = 'x', status = 'open' WHERE id = p;",
    "UPDATE LOW_PRIORITY todo SET status = 'parked' WHERE id = p;",
    "UPDATE todo t JOIN name r ON r.id = t.roster_id SET t.status = 'open' WHERE t.id = p;",
    "UPDATE name n JOIN todo t ON t.roster_id = n.id SET t.assigned_id = 3 WHERE n.id = p;",
    "UPDATE todo SET status = IF(assigned_id IS NULL, 'open', 'claimed') WHERE id = p;",
])
def test_status_and_volunteer_updates_are_flagged(stmt):
    assert found(SQL_OTHER, proc(stmt)) == [("todo", "sql-write")]


@pytest.mark.parametrize("stmt", [
    "UPDATE todo SET body = 'x' WHERE id = p;",
    "UPDATE todo SET done_when = 'y', meta = NULL WHERE id = p;",
    "UPDATE todo SET updated = NOW(6), updated_id = 3 WHERE id = p;",
    "UPDATE todo SET type = 'doing' WHERE type = 'join';",
    "UPDATE todo_label SET status = 'x' WHERE id = p;",
    "UPDATE name SET status = 'x' WHERE id = p;",
    "UPDATE todo t JOIN name r ON r.id = t.roster_id SET r.status = 'open' WHERE t.id = p;",
    "-- UPDATE todo SET status = 'done';",
    "SELECT status FROM todo WHERE id = p;",
])
def test_card_text_other_tables_and_reads_are_quiet(stmt):
    assert found(SQL_OTHER, proc(stmt)) == []


@pytest.mark.parametrize("stmt", [
    "INSERT INTO todo (updated_id, roster_id, creator_id, status) VALUES (p, 1, 1, 'open');",
    "REPLACE INTO todo (id, status) VALUES (p, 'open');",
    "DELETE FROM todo WHERE id = p;",
])
def test_creating_replacing_and_deleting_a_card_are_flagged(stmt):
    assert found(SQL_OTHER, proc(stmt)) == [("todo", "sql-write")]


def test_a_todo_transition_row_outside_the_entry_is_flagged():
    sql = proc("INSERT INTO transition (activity_type, activity_id, to_state) VALUES ('todo', p, 'done');"
               "\n  CALL mill_transition_put('todo', p, 'open', 'claimed', 'claim', 0, 'actor', NULL, NULL);")
    assert found(SQL_OTHER, sql) == [("todo", "transition-write")] * 2


def test_the_same_write_in_the_todo_procedures_is_not_a_finding():
    writes = bs.scan_sql(SQL_ENTRY, proc("UPDATE todo SET status = 'done' WHERE id = p;"))
    assert len(writes) == 1 and bs.report(writes, [])["findings"] == []


def test_entry_is_the_todo_files_only():
    py = "def f(cn):\n    put(cn, activity_type=ActivityType.todo, activity_id=1)\n"
    assert bs.report(bs.scan_py(PY_ENTRY, py), [])["findings"] == []
    got = bs.report(bs.scan_py(PY_OTHER, py), [])["findings"]
    assert [(f["protocol"], f["function"], f["kind"]) for f in got] == [("todo", "f", "transition-write")]


def test_python_sql_string_for_status_is_found_and_text_is_not():
    py = ("def a(cn):\n    cn.execute(\"UPDATE todo SET status = 'shipped' WHERE id = %s\", (1,))\n"
          "def b(cn):\n    cn.execute(\"UPDATE todo SET done_when = %s WHERE id = %s\", ('y', 1))\n")
    got = bs.scan_py(PY_OTHER, py)
    assert [(w.protocol, w.function) for w in got] == [("todo", "a")]


def test_a_status_write_is_not_a_wake_write_and_the_reverse():
    assert {w.protocol for w in bs.scan_sql(SQL_OTHER, proc("UPDATE wake SET state = 'x' WHERE id = p;"))} == {"wake"}
    assert {w.protocol for w in bs.scan_sql(SQL_OTHER, proc("UPDATE todo SET status = 'x' WHERE id = p;"))} == {"todo"}


def test_self_test_names_each_todo_plant(monkeypatch):
    assert bs.self_test() == []
    for path in ("agent_coord/server/sql/sp_planted_todo.sql", "agent_coord/server/planted_todo.py"):
        monkeypatch.setitem(bs.PLANTED, path, "-- nothing planted\n" if path.endswith("sql") else "x = 1\n")
        problems = bs.self_test()
        assert any("planted bypass not flagged" in p and "todo" in p for p in problems)
        monkeypatch.undo()


def test_self_test_fails_when_card_text_counts_as_status(monkeypatch):
    monkeypatch.setitem(bs.PROTOCOLS["todo"], "columns", None)
    assert any("counted a write that is not one" in p for p in bs.self_test())


def test_status_update_through_a_dropped_column_filter_is_caught_by_the_plants(monkeypatch):
    monkeypatch.setitem(bs.PROTOCOLS["todo"], "columns", ("nothing",))
    assert any("planted bypass not flagged" in p for p in bs.self_test())


def test_repo_scan_has_todo_writes_all_via_entry_or_allowed():
    rep = bs.report(bs.scan_tree(bs.ROOT), bs.read_allow(bs.ALLOW))
    todo = [p for p in rep["protocols"] if p["protocol"] == "todo"][0]
    assert todo["writes"] >= 15 and todo["findings"] == 0
    assert not [f for f in rep["findings"] if f["protocol"] == "todo"]


def test_allow_line_pins_the_migration_function():
    allow = [a for a in bs.read_allow(bs.ALLOW) if a["protocol"] == "todo"]
    assert [a["function"] for a in allow] == ["_ensure_todo_claimed_at"]
    py = "def _ensure_todo_claimed_at(cn):\n    cn.execute(\"UPDATE todo SET claimed_at = NOW(6) WHERE status = 'claimed'\")\n"
    renamed = py.replace("_ensure_todo_claimed_at", "_ensure_todo_claimed_at2")
    path = "agent_coord/install/migrate.py"
    assert bs.report(bs.scan_py(path, py), allow)["findings"] == []
    rep = bs.report(bs.scan_py(path, renamed), allow)
    assert len(rep["findings"]) == 1 and len(rep["stale_allow"]) == len([a for a in allow])


def test_report_is_byte_stable(capsys):
    assert bs.main(["--report"]) == 0
    first = capsys.readouterr().out
    assert bs.main(["--report"]) == 0
    assert capsys.readouterr().out == first
    assert json.loads(first)["stale_allow"] == []
