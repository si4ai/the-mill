"""#614 on a real book: the wall knows when the book's SQL is not this pack's. Regression row F66 (sql-stamp).

Seen live: a pack update plus a wall restart left the stored procedures of
the previous pack; the wall served new code over them with health green.
"""
from __future__ import annotations

import pytest

from agent_coord.install import migrate
from agent_coord.server.records import apply
from agent_coord.server.records.db import rows_done, scalar_done

pytestmark = pytest.mark.sql

FIX = "mill install sql --apply"


def test_ensure_stamps_this_pack(cn):
    migrate.ensure(cn)
    st = migrate.sql_state(cn)
    assert st["ok"] is True
    assert st["book"] == st["pack"] == migrate.sql_digest()[:12]


def test_a_book_left_by_another_pack_is_stale(cn):
    migrate.ensure(cn)
    migrate._stamp_sql(cn, "0" * 64)
    st = migrate.sql_state(cn)
    assert st["ok"] is False
    assert st["book"] == "0" * 12
    assert st["fix"] == FIX


def test_a_book_from_before_the_stamp_is_stale(cn):
    migrate.ensure(cn)
    cur = cn.cursor()
    cur.execute("DROP FUNCTION IF EXISTS MILL_SQL_STAMP")
    cur.close()
    st = migrate.sql_state(cn)
    assert st["ok"] is False
    assert st["book"] == ""
    assert st["fix"] == FIX


def test_install_sql_apply_runs_ensure_and_verifies(cn):
    migrate._stamp_sql(cn, "0" * 64)
    out = migrate.install_sql(cn, apply=False)
    assert out["ok"] is False and out["applied"] is False and out["fix"] == FIX
    assert migrate.sql_state(cn)["ok"] is False
    out = migrate.install_sql(cn, apply=True)
    assert out["ok"] is True and out["applied"] is True
    assert migrate.sql_state(cn)["ok"] is True


def _x(cn, sql: str, args: tuple = ()) -> None:
    cur = cn.cursor()
    try:
        cur.execute(sql, args)
    finally:
        cur.close()


def test_h_sql_state_flags_a_missing_or_changed_routine(cn):
    """A routine dropped or changed by hand after ensure is not this pack's SQL.

    F117 sql_state rules: ensure reloads whenever sql_state is not ok, and
    sql_state is not ok while a shipped routine is missing or the routines
    differ from the fingerprint the last finished ensure stamped.
    """
    apply(cn, wipe=True)
    migrate.ensure(cn)
    assert migrate.sql_state(cn)["ok"] is True
    _x(cn, "DROP FUNCTION IF EXISTS MILL_SCORE_DOC_ADD")
    cn.commit()
    st = migrate.sql_state(cn)
    assert st["ok"] is False and "mill_score_doc_add" in st["routines"].lower()
    migrate.ensure(cn)
    assert migrate.sql_state(cn)["ok"] is True
    _x(cn, "DROP PROCEDURE IF EXISTS mill_floor_scope_load")
    _x(cn, "CREATE PROCEDURE mill_floor_scope_load() SELECT 1")
    cn.commit()
    assert migrate.sql_state(cn)["ok"] is False
    migrate.ensure(cn)
    assert migrate.sql_state(cn)["ok"] is True


def test_i_a_book_whose_routines_name_a_missing_definer_converges(cn):
    """A dump restored on another server keeps DEFINER = a user that is not
    there; calling the stamp then fails with 1449. ensure must read that as
    unstamped and reload, not crash before the reload. F117 definer rule.
    """
    apply(cn, wipe=True)
    migrate.ensure(cn)
    gone = "`gone_818`@`localhost`"
    redefined = 0
    for r in rows_done(cn, "SELECT ROUTINE_TYPE AS t, ROUTINE_NAME AS n FROM information_schema.ROUTINES"
                           " WHERE ROUTINE_SCHEMA = DATABASE()"):
        rtype, name = r["t"], r["n"]
        ddl = rows_done(cn, f"SHOW CREATE {rtype} `{name}`")[0][f"Create {rtype.title()}"]
        rest = ddl.partition(f" {rtype} ")[2]
        try:
            _x(cn, f"DROP {rtype} `{name}`")
            _x(cn, f"CREATE DEFINER={gone} {rtype} {rest}")
        except Exception as e:  # no SET_USER_ID here: the case cannot be built
            if getattr(e, "errno", None) in (1227, 1044):
                pytest.skip("this server user cannot create routines for another definer")
            raise
        redefined += 1
    cn.commit()
    assert redefined > 2
    st = migrate.sql_state(cn)
    assert st["ok"] is False
    migrate.ensure(cn)
    assert migrate.sql_state(cn)["ok"] is True
    assert scalar_done(cn, "SELECT COUNT(*) FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA = DATABASE()"
                           " AND DEFINER = 'gone_818@localhost'") == 0
