"""Beta book for the 0.8.0 score/activity/push/glance lane (card 868, lane C).

Until the 0.8.0 tables.sql lands, this builds a book from the beta DDL plus the
routine files in apply_order.txt, so the existing SQL suites and the lane C tests
run against the beta schema:

    python -m pytest -p tests.server.records.lane_c_beta tests/server -m sql

The DDL is, in order: MILL_BETA_DDL when set; agent_coord/server/sql/tables.sql
when it is already the beta DDL (seat.doing_id / doing.evidence); else
docs/requirements/beta/beta_ddl.sql. beta_sp.sql runs after the routine files.

A desk name gets its seat row in the same statement (a test-only trigger), as
the beta mint path does (sp_name_mint_desk writes the seat with the name).

When MySQL answers but a statement of the apply fails, the test fails (it is
not skipped): the error is raised as pytest's Failed, which `except Exception`
in the shared fixture does not catch.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SQL_DIR = ROOT / "agent_coord" / "server" / "sql"
BETA_DIR = ROOT / "docs" / "requirements" / "beta"
# Main's order without its DDL and wipe; name_type.sql and the 070/818 migrations are not in it.
_SKIP = {"wipe.sql", "tables.sql", "name_type.sql", "migrate_070_roster.sql", "migrate_818_doing.sql"}
_NEW_TABLES = ("glance_cache", "sp_deploy", "vote_cast", "vote_option", "vote", "doing_now", "todo_event")
_NEW_TRIGGERS = ("name_fixed", "vote_cast_open", "vote_cast_change", "lane_c_seat_with_desk")

SEAT_SHIM = """
DROP TRIGGER IF EXISTS lane_c_seat_with_desk;
DELIMITER //
CREATE TRIGGER lane_c_seat_with_desk AFTER INSERT ON name
FOR EACH ROW
BEGIN
  IF NEW.type = 'desk' THEN
    INSERT IGNORE INTO seat (desk_id) VALUES (NEW.id);
  END IF;
END //
DELIMITER ;
"""


def beta_ddl_path() -> Path:
    env = (os.environ.get("MILL_BETA_DDL") or "").strip()
    if env:
        return Path(env)
    tables = SQL_DIR / "tables.sql"
    body = tables.read_text(encoding="utf-8-sig")
    if "doing_id" in body and "evidence" in body:
        return tables
    return BETA_DIR / "beta_ddl.sql"


def _wipe_text() -> str:
    main = (SQL_DIR / "wipe.sql").read_text(encoding="utf-8-sig")
    extra = "".join(f"DROP TABLE IF EXISTS {t};\n" for t in _NEW_TABLES)
    extra += "".join(f"DROP TRIGGER IF EXISTS {t};\n" for t in _NEW_TRIGGERS)
    head, sep, tail = main.partition("SET FOREIGN_KEY_CHECKS = 1;")
    assert sep, "wipe.sql: no FOREIGN_KEY_CHECKS = 1 line"
    return head + extra + sep + tail


_TMP: Path | None = None


def beta_apply_order() -> list[Path]:
    """The beta book's file list, written once per process into a temp dir."""
    global _TMP
    if _TMP is None:
        _TMP = Path(tempfile.mkdtemp(prefix="lane_c_beta_"))
        (_TMP / "wipe.sql").write_text(_wipe_text(), encoding="utf-8")
        (_TMP / "zz_seat_shim.sql").write_text(SEAT_SHIM, encoding="utf-8")
    order = [_TMP / "wipe.sql", beta_ddl_path()]
    for line in (SQL_DIR / "apply_order.txt").read_text(encoding="utf-8-sig").splitlines():
        name = line.strip()
        if name and not name.startswith("#") and name not in _SKIP:
            order.append(SQL_DIR / name)
    # beta_sp overlays pack SPs for the proposal DDL only. When tables.sql is
    # already 0.8.0, pack SPs (sp_beta_name last in apply_order) are the source.
    # sp_glance.sql is in apply_order.txt (F191); do not append it here.
    if beta_ddl_path().resolve() != (SQL_DIR / "tables.sql").resolve():
        order.append(BETA_DIR / "beta_sp.sql")
    order.append(_TMP / "zz_seat_shim.sql")
    return order


def _fail_not_skip(real):
    def run(cur, stmt):
        try:
            return real(cur, stmt)
        except Exception as exc:  # MySQL answered; the beta apply itself is wrong.
            pytest.fail(f"beta book apply failed: {exc}\n{stmt[:300]}", pytrace=False)

    return run


_PLUGIN = False


def install() -> None:
    from agent_coord.install import migrate

    if getattr(migrate, "_lane_c_beta", False):
        return
    migrate._lane_c_beta_prev = (migrate.sql_apply_order, migrate._apply_stmt)
    migrate.sql_apply_order = beta_apply_order
    migrate._apply_stmt = _fail_not_skip(migrate._apply_stmt)
    migrate._lane_c_beta = True


def uninstall() -> None:
    """Restore pack apply_order so modules like book_schema_parity stay on tip SQL."""
    from agent_coord.install import migrate

    if not getattr(migrate, "_lane_c_beta", False):
        return
    prev = getattr(migrate, "_lane_c_beta_prev", None)
    if prev:
        migrate.sql_apply_order, migrate._apply_stmt = prev
    migrate._lane_c_beta = False
    migrate._lane_c_beta_prev = None


def pytest_configure(config):  # plugin hook: -p tests.server.records.lane_c_beta
    global _PLUGIN
    _PLUGIN = True
    install()


def make_book(prefix: str):
    """A fresh beta book (wiped schema `prefix_<pid>`). Skips only when MySQL does not answer."""
    import mysql.connector

    from agent_coord.server.records import apply, connect
    from agent_coord.server.records.db import conn_kwargs
    from tests.sql_isolate import throwaway_db

    install()
    db = throwaway_db(prefix)
    kw = conn_kwargs()
    kw.pop("database", None)
    kw["autocommit"] = True
    try:
        try:
            adm = mysql.connector.connect(**kw)
        except Exception as exc:
            pytest.skip(f"mysql not answering: {exc}")
        cur = adm.cursor()
        cur.execute(f"DROP DATABASE IF EXISTS `{db}`")
        cur.execute(f"CREATE DATABASE `{db}` DEFAULT CHARACTER SET utf8mb4 DEFAULT COLLATE utf8mb4_0900_ai_ci")
        cur.close()
        adm.close()
        saved = os.environ.pop("AGENT_COORD_DATABASE", None)
        try:
            cn = connect(db)
        finally:
            if saved is not None:
                os.environ["AGENT_COORD_DATABASE"] = saved
        apply(cn, wipe=True)
        return cn, db
    finally:
        if not _PLUGIN:
            uninstall()


def drop_book(cn, db: str) -> None:
    try:
        if not os.environ.get("MILL_KEEP_TEST_DB"):
            cur = cn.cursor()
            cur.execute(f"DROP DATABASE IF EXISTS `{db}`")
            cur.close()
    finally:
        cn.close()
