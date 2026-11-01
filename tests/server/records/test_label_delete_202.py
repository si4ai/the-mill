"""#202: mill_label_delete refuses an unknown name and reports zero rows as not removed."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.sql

from agent_coord.install import migrate
from agent_coord.server.records import label as rec_label
from agent_coord.server.records import todo as rec_todo
from agent_coord.server.records.db import conn_kwargs as _conn_kwargs
from tests.server.records.conftest import seed_names

def _count(cn, type_s: str, nid: int) -> int:
    cur = cn.cursor()
    cur.execute("SELECT COUNT(*) FROM label WHERE type=%s AND id=%s", (type_s, nid))
    n = int(cur.fetchone()[0])
    cur.close()
    return n

def _body(cn, name: str) -> str:
    cur = cn.cursor()
    cur.execute(
        "SELECT ROUTINE_DEFINITION FROM information_schema.ROUTINES "
        "WHERE ROUTINE_SCHEMA = DATABASE() AND ROUTINE_NAME = %s",
        (name,),
    )
    row = cur.fetchone()
    cur.close()
    return str(row[0] or "") if row else ""

def test_unknown_name_refuses_and_zero_rows_are_not_removed(cn) -> None:
    seed_names(cn, ("unit", "roster"), ("a", "desk"), ("kept", "label"), ("rule:cards", "label"), ("other", "label"))
    tid = int(rec_todo.insert(cn, "unit", "a", "open", "card")[0]["id"])
    assert rec_label.put(cn, "todo", tid, "kept")[0]["name_id"]
    assert rec_label.put(cn, "todo", tid, "rule:cards")[0]["name_id"]
    assert _count(cn, "todo", tid) == 2

    with pytest.raises(Exception, match=r"label: no such name"):
        rec_label.delete(cn, "todo", tid, "rule:card")
    assert _count(cn, "todo", tid) == 2

    miss = rec_label.delete(cn, "todo", tid, "other")
    assert miss[0]["op"] == "not-removed"
    assert _count(cn, "todo", tid) == 2

    gone = rec_label.delete(cn, "todo", tid, "kept")
    assert gone[0]["op"] == "removed"
    assert _count(cn, "todo", tid) == 1

    again = rec_label.delete(cn, "todo", tid, "kept")
    assert again[0]["op"] == "not-removed"
    assert _count(cn, "todo", tid) == 1

    cur = cn.cursor()
    cur.execute("UPDATE name SET deleted = CURRENT_TIMESTAMP(6) WHERE type='label' AND name='other'")
    cn.commit()
    cur.close()
    with pytest.raises(Exception, match=r"label: no such name"):
        rec_label.delete(cn, "todo", tid, "other")
    assert _count(cn, "todo", tid) == 1

def test_ensure_refreshes_label_delete(cn) -> None:
    cur = cn.cursor()
    cur.execute("DROP PROCEDURE IF EXISTS mill_label_delete")
    cur.execute(
        "CREATE PROCEDURE mill_label_delete("
        "IN p_type VARCHAR(16), IN p_id BIGINT UNSIGNED, IN p_label VARCHAR(64)) "
        "SELECT 'removed' AS op"
    )
    cn.commit()
    cur.close()
    assert "no such name" not in _body(cn, "mill_label_delete")
    out = migrate.ensure(cn)
    assert "sp_label.sql" in out["applied"]
    assert "no such name" in _body(cn, "mill_label_delete")
