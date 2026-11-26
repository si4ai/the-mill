"""Card 1312: the bypass scan flags protected writes outside the protocol's entry point.

The planted fixtures (a direct UPDATE of wake, a wake transition and a DELETE
from Python outside the wake code) must each be flagged; an entry-point write,
a commented-out write and an allowlisted write must not be; a stale allow line
is reported; the same tree gives the same bytes.
"""
from __future__ import annotations

import json

from tools import bypass_scan as bs

SQL_ENTRY = "agent_coord/server/sql/sp_push.sql"
SQL_OTHER = "agent_coord/server/sql/sp_mail.sql"


def kinds(writes, allow=()):
    return sorted((f["path"], f["function"], f["kind"]) for f in bs.report(writes, list(allow))["findings"])


def test_self_test_flags_every_plant():
    assert bs.self_test() == []


def test_self_test_fails_when_a_plant_is_missed(monkeypatch):
    monkeypatch.setitem(bs.PLANTED, "agent_coord/server/planted.py", "def lease_end_elsewhere():\n    pass\n")
    assert any("not flagged" in p for p in bs.self_test())
    assert bs.main(["--self-test"]) == 1


def test_direct_update_outside_entry_is_a_finding():
    sql = "CREATE PROCEDURE mill_mail_delete(IN p BIGINT)\nBEGIN\n  UPDATE wake SET state = 'taken' WHERE id = p;\nEND //\n"
    assert kinds(bs.scan_sql(SQL_OTHER, sql)) == [(SQL_OTHER, "mill_mail_delete", "sql-write")]


def test_same_write_in_entry_point_is_not_a_finding():
    sql = "CREATE PROCEDURE mill_push_take(IN p BIGINT)\nBEGIN\n  UPDATE wake SET state = 'taken' WHERE id = p;\nEND //\n"
    writes = bs.scan_sql(SQL_ENTRY, sql)
    assert len(writes) == 1 and kinds(writes) == []


def test_entry_by_function_name_only_covers_that_routine():
    sql = ("CREATE PROCEDURE cmd_push_sent(IN p BIGINT)\nBEGIN\n  UPDATE wake SET state='taken' WHERE id=p;\nEND //\n"
           "CREATE PROCEDURE cmd_other(IN p BIGINT)\nBEGIN\n  DELETE FROM wake WHERE id=p;\nEND //\n")
    path = "agent_coord/server/sql/sp_cmd.sql"
    assert kinds(bs.scan_sql(path, sql)) == [(path, "cmd_other", "sql-write")]


def test_comments_and_other_tables_do_not_count():
    sql = ("CREATE PROCEDURE p1()\nBEGIN\n  -- UPDATE wake SET x = 1;\n  /* DELETE FROM wake */\n"
           "  UPDATE wake_state SET x = 1;\n  INSERT INTO transition_edge (a) VALUES ('wake');\nEND //\n")
    assert bs.scan_sql(SQL_OTHER, sql) == []


def test_transition_insert_counts_only_for_its_activity():
    sql = ("CREATE PROCEDURE p1()\nBEGIN\n"
           "  INSERT INTO transition (activity_type, activity_id) VALUES ('hold', 1);\n"
           "  CALL mill_transition_put('wake', 1, 'a', 'b', 'c', 0, 'office', NULL, NULL);\nEND //\n")
    got = bs.scan_sql(SQL_OTHER, sql)
    assert [(w.line, w.kind) for w in got] == [(4, "transition-write")]


def test_python_string_and_put_call_are_found_with_their_function():
    py = ("class K:\n    def drop(self, cn):\n"
          "        cn.execute(\"UPDATE wake SET state = 'x' WHERE id = 1\")\n"
          "        tr.put(cn, activity_type=ActivityType.wake, activity_id=1)\n"
          "        tr.put(cn, activity_type=ActivityType.hold, activity_id=1)\n")
    got = bs.scan_py("agent_coord/server/other.py", py)
    assert [(w.line, w.function, w.kind) for w in got] == [
        (3, "K.drop", "sql-write"), (4, "K.drop", "transition-write")]


def test_allowlist_hides_a_write_and_a_stale_line_is_reported(tmp_path):
    p = tmp_path / "allow.txt"
    p.write_text("# c\nwake agent_coord/server/sql/sp_mail.sql::mill_mail_delete test fixture\n"
                 "wake agent_coord/x.py::gone no longer in code\n", encoding="utf-8")
    allow = bs.read_allow(p)
    sql = "CREATE PROCEDURE mill_mail_delete()\nBEGIN\n  DELETE FROM wake WHERE id = 1;\nEND //\n"
    rep = bs.report(bs.scan_sql(SQL_OTHER, sql), allow)
    assert rep["findings"] == [] and rep["allowed"] == 1
    assert rep["stale_allow"] == [{"allow_line": 3, "protocol": "wake", "where": "agent_coord/x.py::gone"}]


def test_bad_allow_line_exits_2(tmp_path):
    p = tmp_path / "allow.txt"
    p.write_text("wake no-function-here\n", encoding="utf-8")
    assert bs.main(["--allow", str(p)]) == 2


def test_repo_scan_is_byte_stable_and_report_mode_exits_0(capsys):
    assert bs.main(["--report"]) == 0
    first = capsys.readouterr().out
    bs.main(["--report"])
    assert capsys.readouterr().out == first
    rep = json.loads(first)
    assert rep["stale_allow"] == []
    assert [p["protocol"] for p in rep["protocols"]] == ["wake"]
