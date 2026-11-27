"""Card 1312, card status slice, Validator 7082 warnings.

W1 a quoted string in a SET list or after SET is text, not syntax: a comma or WHERE inside a
literal neither makes a false finding nor hides a real one.
A ; inside a literal does not end the statement.
W2 the column match is case-insensitive and exact: SET STATUS counts, status_note does not.
"""
from __future__ import annotations

import pytest

from tools import bypass_scan as bs

PATH = "agent_coord/server/sql/sp_cmd.sql"


def proc(body: str) -> str:
    return f"CREATE PROCEDURE cmd_x(IN p BIGINT)\nBEGIN\n  {body}\nEND //\n"


def todo_hits(stmt: str) -> int:
    return len([w for w in bs.scan_sql(PATH, proc(stmt)) if w.protocol == "todo"])


@pytest.mark.parametrize("stmt", [
    "UPDATE todo SET body = 'a, status = b' WHERE id = p;",
    "UPDATE todo SET body = 'x = 1, assigned_id = 2' WHERE id = p;",
    "UPDATE todo SET body = \"set status = 1, claimed_at = 2\" WHERE id = p;",
    "UPDATE todo SET body = 'it''s, status = x' WHERE id = p;",
    "UPDATE todo SET body = 'a\\', status = b' WHERE id = p;",
    "UPDATE todo SET body = 'WHERE x, status = 1' WHERE id = p;",
])
def test_a_column_name_inside_a_literal_is_not_a_write(stmt):
    assert todo_hits(stmt) == 0


@pytest.mark.parametrize("stmt", [
    "UPDATE todo SET body = 'go where told', status = 'done' WHERE id = p;",
    "UPDATE todo SET body = 'a, b', assigned_id = 3 WHERE id = p;",
    "UPDATE todo SET body = 'x WHERE y', claimed_at = NOW(6) WHERE id = p;",
    "UPDATE todo SET body = \"a, b\", status = 'open' WHERE id = p;",
    "UPDATE todo SET body = 'it''s fine', status = 'open' WHERE id = p;",
])
def test_a_real_write_after_a_literal_is_still_found(stmt):
    assert todo_hits(stmt) == 1


@pytest.mark.parametrize("stmt", [
    "UPDATE todo SET STATUS = 'done' WHERE id = p;",
    "UPDATE todo SET Assigned_Id = 3 WHERE id = p;",
    "UPDATE todo SET `status` = 'done' WHERE id = p;",
    "UPDATE todo t SET t.STATUS = 'done' WHERE t.id = p;",
])
def test_the_column_match_ignores_case_and_backticks(stmt):
    assert todo_hits(stmt) == 1


@pytest.mark.parametrize("stmt", [
    "UPDATE todo SET status_note = 'x' WHERE id = p;",
    "UPDATE todo SET statuses = 1 WHERE id = p;",
    "UPDATE todo SET assigned_id_old = 3 WHERE id = p;",
    "UPDATE todo SET claimed_at2 = NOW(6) WHERE id = p;",
    "UPDATE todo SET x_status = 1 WHERE id = p;",
])
def test_the_column_match_is_exact_not_a_prefix_or_suffix(stmt):
    assert todo_hits(stmt) == 0


def test_a_literal_in_a_delete_does_not_hide_the_table():
    sql = "DELETE FROM todo WHERE body = 'FROM x USING y'"
    assert todo_hits(sql + ";") == 1


def test_wake_updates_are_read_the_same_way():
    hits = [w for w in bs.scan_sql(PATH, proc("UPDATE wake SET note = 'a, state = 1' WHERE id = p;"))
            if w.protocol == "wake"]
    assert len(hits) == 1
    hits = [w for w in bs.scan_sql(PATH, proc("UPDATE wake SET note = 'a', state = 'b' WHERE id = p;"))
            if w.protocol == "wake"]
    assert len(hits) == 1


def test_a_semicolon_inside_a_literal_does_not_end_the_statement():
    assert todo_hits("UPDATE todo SET body = 'a; b', status = 'x' WHERE id = p;") == 1
    assert todo_hits("UPDATE todo SET body = 'a; status = b' WHERE id = p;") == 0
