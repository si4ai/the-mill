"""A fresh book and an upgraded book end in the same schema (card 840, F133).

Fresh: migrate.ensure on an empty database (tables.sql plus every routine).
Upgraded: the 0.7.6 book (the SQL of the first public commit, read from git),
then tip migrate.ensure, which is what `mill install sql --apply` runs on an
older stamp. The shapes (tables, columns with enum values, indexes, foreign
keys, triggers, routine bodies) must match. A second test puts the drift seen
on the cloud office book into an upgraded copy and requires the diff to name
each part, so the check cannot pass by reading too little.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

# fresh_schema: builds three books (fresh/upgrade/drift) and diffs tip shapes
pytestmark = [pytest.mark.sql, pytest.mark.fresh_schema]

from agent_coord.install import migrate
from agent_coord.server.records import connect
from agent_coord.server.records.db import conn_kwargs as _conn_kwargs
from tests.sql_isolate import throwaway_db
from tools import book_shape

ROOT = Path(__file__).resolve().parents[3]
# The first public commit: the 0.7.6 pack, the oldest book this repo can build.
OLD = "cf260893da57e8578813123d76ded8109eec664f"
FRESH_DB = throwaway_db("mill_parity_fresh")
UP_DB = throwaway_db("mill_parity_up")
DRIFT_DB = throwaway_db("mill_parity_drift")


def _admin():
    import mysql.connector

    kw = _conn_kwargs()
    kw.pop("database", None)
    kw["autocommit"] = True
    return mysql.connector.connect(**kw)


def _new_db(name: str):
    admin = _admin()
    cur = admin.cursor()
    cur.execute(f"DROP DATABASE IF EXISTS `{name}`")
    cur.execute(
        f"CREATE DATABASE `{name}` DEFAULT CHARACTER SET utf8mb4 DEFAULT COLLATE utf8mb4_0900_ai_ci"
    )
    cur.close()
    admin.close()
    return connect(name)


def _git_show(path: str) -> str:
    r = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{OLD}:{path}"], capture_output=True, text=True
    )
    if r.returncode:
        raise LookupError(r.stderr.strip()[:200])
    return r.stdout


def _old_sql() -> list[tuple[str, str]]:
    """(file, text) for the 0.7.6 apply order. CI has full history; a checkout
    without the commit skips, except in CI where it fails."""
    try:
        order = _git_show("agent_coord/server/sql/apply_order.txt").split()
        return [(n, _git_show(f"agent_coord/server/sql/{n}")) for n in order]
    except (LookupError, OSError) as e:
        if os.environ.get("GITHUB_ACTIONS") == "true":
            raise AssertionError(f"0.7.6 SQL not readable from git in CI: {e}")
        pytest.skip(f"0.7.6 SQL not in this checkout: {e}")


def _build_old(cn, files) -> None:
    cur = cn.cursor()
    try:
        try:
            cur.execute("SET GLOBAL log_bin_trust_function_creators = 1")
        except Exception:
            pass
        for _name, text in files:
            for stmt in migrate.split_script(text):
                migrate._apply_stmt(cur, stmt)
        cn.commit()
    finally:
        cur.close()


@pytest.fixture(scope="module")
def books():
    files = _old_sql()
    try:
        fresh = _new_db(FRESH_DB)
        up = _new_db(UP_DB)
        drift = _new_db(DRIFT_DB)
    except Exception as e:
        pytest.skip(f"mysql mill records: {e}")
    migrate.ensure(fresh)
    for cn in (up, drift):
        _build_old(cn, files)
        migrate.ensure(cn)
    yield fresh, up, drift
    for cn in (fresh, up, drift):
        cn.close()
    admin = _admin()
    cur = admin.cursor()
    for name in (FRESH_DB, UP_DB, DRIFT_DB):
        cur.execute(f"DROP DATABASE IF EXISTS `{name}`")
    cur.close()
    admin.close()


def test_upgraded_book_has_the_fresh_shape(books) -> None:
    fresh, up, _drift = books
    a, b = book_shape.shape(fresh), book_shape.shape(up)
    assert a, "the fresh shape read nothing"
    for kind in ("table", "column", "index", "fk", "trigger", "routine"):
        assert any(k.startswith(kind + " ") for k in a), kind
    assert book_shape.diff(a, b) == []


# The drift seen on the cloud office book (dump copy, after ensure at 0.7.16).
# Reported, not dropped, in 0.7.17: dropping it is a format change.
_LIVE_DRIFT_SQL = [
    *(
        f"CREATE TRIGGER {t}_ad_activity AFTER DELETE ON {t} FOR EACH ROW BEGIN\n"
        f"  DELETE FROM activity WHERE type = '{t}' AND id = OLD.id;\nEND"
        for t in ("mail", "todo", "hold", "score")
    ),
    "ALTER TABLE watcher MODIFY type ENUM('todo','doing','hold','score','name') NOT NULL",
    "ALTER TABLE doing ADD COLUMN directory_sub VARCHAR(255) NULL",
    "ALTER TABLE tree DROP FOREIGN KEY fk_tree_name",
    "ALTER TABLE tree ADD CONSTRAINT fk_tree_name FOREIGN KEY (name_id) REFERENCES name(id)"
    " ON DELETE NO ACTION",
]
_LIVE_DRIFT_KEYS = [
    "column doing.directory_sub",
    "column watcher.type",
    "fk tree.fk_tree_name",
    "trigger hold_ad_activity",
    "trigger mail_ad_activity",
    "trigger score_ad_activity",
    "trigger todo_ad_activity",
]


def test_diff_names_the_live_drift(books) -> None:
    fresh, _up, drift = books
    cur = drift.cursor()
    try:
        for stmt in _LIVE_DRIFT_SQL:
            cur.execute(stmt)
        drift.commit()
    finally:
        cur.close()
    got = book_shape.diff(book_shape.shape(fresh), book_shape.shape(drift))
    assert [line.split(":")[0] for line in got] == _LIVE_DRIFT_KEYS
    assert book_shape.drift_keys(got) == _LIVE_DRIFT_KEYS
    assert set(_LIVE_DRIFT_KEYS) <= set(book_shape.KNOWN_LIVE_DRIFT)
