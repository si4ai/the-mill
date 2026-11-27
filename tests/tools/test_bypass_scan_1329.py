"""Card 1329: the bypass scan reads the SQL shapes Validator listed for #526, and pins the allow line.

Each shape has its own fixture, flagged with the protocol's entry point out of the way. Near misses (a
read-only JOIN, the string function REPLACE, a sibling table, a docstring) must stay quiet.
"""
from __future__ import annotations

import pytest

from tools import bypass_scan as bs

OTHER = "agent_coord/server/sql/sp_other.sql"


def sql(stmt: str) -> str:
    return f"CREATE PROCEDURE p1(IN p BIGINT)\nBEGIN\n  {stmt}\nEND //\n"


def hits(stmt: str):
    return [(w.line, w.kind) for w in bs.scan_sql(OTHER, sql(stmt))]


@pytest.mark.parametrize("stmt,kind", [
    ("UPDATE activity a JOIN wake w ON w.id = a.id SET w.state = 'taken' WHERE a.id = p;", "sql-write"),
    ("UPDATE activity a INNER JOIN wake ON wake.id = a.id SET wake.state = 'taken';", "sql-write"),
    ("UPDATE activity a, wake w SET w.state = 'x' WHERE a.id = w.id;", "sql-write"),
    ("UPDATE wake w JOIN activity a ON a.id = w.id SET w.state = 'x';", "sql-write"),
    ("UPDATE LOW_PRIORITY wake SET state = 'x' WHERE id = p;", "sql-write"),
    ("UPDATE LOW_PRIORITY IGNORE wake SET state = 'x';", "sql-write"),
    ("DELETE w FROM mail m JOIN wake w ON w.cause_id = m.id WHERE m.id = p;", "sql-write"),
    ("DELETE LOW_PRIORITY QUICK w FROM mail m JOIN wake w ON w.cause_id = m.id;", "sql-write"),
    ("DELETE wake FROM wake JOIN mail m ON m.id = wake.cause_id;", "sql-write"),
    ("DELETE FROM w USING mail m JOIN wake w ON w.cause_id = m.id WHERE m.id = p;", "sql-write"),
    ("DELETE LOW_PRIORITY FROM wake WHERE id = p;", "sql-write"),
    ("INSERT LOW_PRIORITY INTO wake (type, desk_id) VALUES ('wake', 1);", "sql-write"),
    ("INSERT DELAYED IGNORE INTO wake (type) VALUES ('wake');", "sql-write"),
    ("INSERT wake (type, desk_id) VALUES ('wake', 1);", "sql-write"),
    ("REPLACE LOW_PRIORITY INTO wake (id, type) VALUES (1, 'wake');", "sql-write"),
    ("INSERT INTO transition SELECT 0, NOW(6), 'wake', id, state, 'taken', 'x', desk_id, 'office', NULL, NULL, 1"
     " FROM wake WHERE id = p;", "transition-write"),
    ("INSERT INTO transition VALUES (0, NOW(6), 'wake', 1, 'a', 'b', 'c', 0, 'office', NULL, NULL, 1);",
     "transition-write"),
    ("REPLACE INTO transition (activity_type, activity_id) VALUES ('wake', 1);", "transition-write"),
    ("INSERT LOW_PRIORITY INTO transition (activity_type) VALUES ('wake');", "transition-write"),
])
def test_shape_is_flagged(stmt, kind):
    assert hits(stmt) == [(3, kind)]


@pytest.mark.parametrize("stmt", [
    "UPDATE activity a JOIN wake w ON w.id = a.id SET a.updated = NOW(6) WHERE w.state = 'x';",
    "UPDATE activity SET act = 'ring' WHERE id IN (SELECT id FROM wake);",
    "DELETE m FROM mail m JOIN wake w ON w.cause_id = m.id;",
    "DELETE FROM mail WHERE id IN (SELECT cause_id FROM wake);",
    "INSERT INTO wake_state (a) VALUES (1);",
    "INSERT INTO activity (type, id) SELECT 'wake', id FROM wake;",
    "INSERT INTO transition (activity_type) VALUES ('hold');",
    "INSERT INTO transition SELECT 0, NOW(6), 'hold', 1 FROM hold;",
    "SET v = REPLACE(v, 'wake', 'x');",
    "SELECT id FROM wake WHERE id = p FOR UPDATE;",
    "INSERT INTO transition_edge (activity_type) VALUES ('wake') ON DUPLICATE KEY UPDATE reason = 'x';",
])
def test_near_miss_is_quiet(stmt):
    assert hits(stmt) == []


def test_set_with_calls_does_not_confuse_the_target():
    ok = "UPDATE activity a JOIN wake w ON w.id = a.id SET a.note = IF(w.n = 1, 'a', 'b'), a.x = 1;"
    assert hits(ok) == []
    bad = "UPDATE activity a JOIN wake w ON w.id = a.id SET a.note = CONCAT('a', 'b'), w.state = 'x';"
    assert hits(bad) == [(3, "sql-write")]


def test_positional_and_keyword_put_are_found_anywhere_in_the_call():
    py = ("def f(cn):\n    put(cn, ActivityType.wake, 1)\n    put(cn, 1, ActivityType.wake)\n"
          "    tr.put(cn, activity_type=tr.ActivityType.wake)\n    put(cn, ActivityType.hold, 1)\n")
    assert [(w.line, w.kind) for w in bs.scan_py("agent_coord/server/o.py", py)] == [
        (2, "transition-write"), (3, "transition-write"), (4, "transition-write")]


def test_docstring_is_not_a_write_but_executed_sql_is():
    py = ('"""Module: UPDATE wake SET state = 1."""\n\n\nclass K:\n    """DELETE FROM wake, in prose."""\n\n'
          '    def f(self, cn):\n        """INSERT INTO wake (type) VALUES (1)"""\n'
          '        cn.execute("DELETE FROM wake WHERE id = 1")\n'
          '        sql = "UPDATE wake SET state = 2"\n')
    assert [(w.line, w.function) for w in bs.scan_py("agent_coord/server/o.py", py)] == [(9, "K.f"), (10, "K.f")]


def test_self_test_names_each_new_shape(monkeypatch):
    for shape in ("planted_join_first", "planted_delete_join", "planted_low_priority", "planted_columnless"):
        text = bs.PLANTED["agent_coord/server/sql/sp_planted.sql"]
        i = text.index(f"CREATE PROCEDURE {shape}")
        j = text.index("END //\n", i) + len("END //\n")
        monkeypatch.setitem(bs.PLANTED, "agent_coord/server/sql/sp_planted.sql", text[:i] + text[j:])
        assert any(shape in p for p in bs.self_test()), shape
        monkeypatch.setitem(bs.PLANTED, "agent_coord/server/sql/sp_planted.sql", text)
    py = bs.PLANTED["agent_coord/server/planted.py"]
    monkeypatch.setitem(bs.PLANTED, "agent_coord/server/planted.py", py.replace("put(cn, ActivityType.wake, wid, State.idle)", "pass"))
    assert any("positional" in p for p in bs.self_test())


def test_self_test_fails_when_a_docstring_counts(monkeypatch):
    monkeypatch.setattr(bs._PyScan, "visit_Expr", lambda self, node: self.generic_visit(node))
    assert any("not one" in p for p in bs.self_test())


MIG = "agent_coord/install/migrate.py"
FOLD = 'def apply_transition_1022(cur):\n    cur.execute("INSERT IGNORE INTO wake (id, type) SELECT 1, 2")\n'
OTHERFN = 'def other_thing(cur):\n    cur.execute("INSERT IGNORE INTO wake (id, type) SELECT 1, 2")\n'
ALLOW = [{"line": 4, "protocol": "wake", "path": MIG, "function": "apply_transition_1022", "reason": "r"}]


def test_allow_line_hides_only_its_own_function():
    rep = bs.report(bs.scan_py(MIG, FOLD + "\n\n" + OTHERFN), ALLOW)
    assert rep["allowed"] == 1 and rep["stale_allow"] == []
    assert [f["function"] for f in rep["findings"]] == ["other_thing"]


def test_renamed_function_loses_the_allow_and_the_line_goes_stale():
    renamed = FOLD.replace("apply_transition_1022", "apply_transition_1022_v2")
    rep = bs.report(bs.scan_py(MIG, renamed), ALLOW)
    assert [f["function"] for f in rep["findings"]] == ["apply_transition_1022_v2"]
    assert rep["stale_allow"] == [{"allow_line": 4, "protocol": "wake",
                                   "where": f"{MIG}::apply_transition_1022"}]


def test_moved_file_loses_the_allow_too():
    rep = bs.report(bs.scan_py("agent_coord/install/other.py", FOLD), ALLOW)
    assert len(rep["findings"]) == 1 and len(rep["stale_allow"]) == 1


def test_repo_allow_line_names_a_function_that_still_holds_the_write():
    allow = bs.read_allow(bs.ALLOW)
    assert [(a["protocol"], a["function"]) for a in allow] == [
        ("wake", "apply_transition_1022"), ("todo", "_ensure_todo_claimed_at")]
    rep = bs.report(bs.scan_tree(bs.ROOT), allow)
    assert rep["allowed"] == 2 and rep["stale_allow"] == []
