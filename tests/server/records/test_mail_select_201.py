"""#201: mill_mail_select is the desk inbox, every roster. Project and role do not filter."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.sql

from agent_coord.server.records import mail as rec_mail
from agent_coord.server.records.db import conn_kwargs as _conn_kwargs
from tests.server.records.conftest import seed_names

def _ids(cn, desk: str) -> set[int]:
    return {int(r["id"]) for r in rec_mail.select(cn, desk)}

def _param_names(cn) -> list[str]:
    cur = cn.cursor()
    try:
        cur.execute(
            "SELECT PARAMETER_NAME FROM information_schema.PARAMETERS "
            "WHERE SPECIFIC_SCHEMA = DATABASE() AND SPECIFIC_NAME = 'mill_mail_select' "
            "AND ROUTINE_TYPE = 'PROCEDURE' "
            "ORDER BY ORDINAL_POSITION"
        )
        return [str(row[0]) for row in cur.fetchall() if row and row[0]]
    finally:
        cur.close()

def test_select_source_takes_only_the_desk() -> None:
    from pathlib import Path

    from agent_coord.install.migrate import split_script

    text = Path("agent_coord/server/sql/sp_mail.sql").read_text(encoding="utf-8")
    body = text.split("CREATE PROCEDURE mill_mail_select", 1)[1].split("CREATE PROCEDURE", 1)[0]
    assert "m.roster_id = v_proj" not in body
    assert "IN p_project" not in body
    assert "IN p_role" not in body
    assert "IN p_desk" in body
    assert "t.desk_id = v_desk" in body
    stmts = [
        s for s in split_script(text)
        if s.strip().lower().startswith("create procedure mill_mail_select")
    ]
    assert len(stmts) == 1
    whole = text[text.index("CREATE PROCEDURE mill_mail_select"): text.index("\nEND //", text.index("CREATE PROCEDURE mill_mail_select"))]
    assert "IN p_desk" in stmts[0] and "IN p_desk" in whole
    assert "IN p_role" not in stmts[0] and "IN p_role" not in whole

def test_desk_inbox_includes_every_project(cn) -> None:
    seed_names(cn, ("unit", "roster"), ("beta", "roster"), ("a", "desk"), ("b", "desk"))
    one = int(rec_mail.insert(cn, "unit", "a", "b", "from unit")[0]["id"])
    two = int(rec_mail.insert(cn, "beta", "a", "b", "from beta")[0]["id"])
    assert _ids(cn, "b") == {one, two}
    assert one not in _ids(cn, "a")
    assert two not in _ids(cn, "a")
    assert _ids(cn, "nobody") == set()
    assert _param_names(cn) == ["p_desk"]

def test_ensure_replaces_a_three_arg_select(cn) -> None:
    from agent_coord.install import migrate

    cur = cn.cursor()
    try:
        cur.execute("DROP PROCEDURE IF EXISTS mill_mail_select")
        cur.execute(
            "CREATE PROCEDURE mill_mail_select("
            "IN p_project VARCHAR(64), IN p_desk VARCHAR(64), IN p_role VARCHAR(64)) "
            "BEGIN SELECT 1 AS id; END"
        )
        cn.commit()
    finally:
        cur.close()
    try:
        assert _param_names(cn) == ["p_project", "p_desk", "p_role"]
        out = migrate.ensure(cn)
        assert "sp_mail.sql" in out["applied"]
        assert _param_names(cn) == ["p_desk"]
        assert _ids(cn, "nobody") == set()
    finally:
        migrate.ensure(cn)
