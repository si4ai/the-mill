"""A fresh book and an upgraded book end in the same schema (card 840, F133).

Fresh: migrate.ensure on an empty database (tables.sql plus every routine).
Upgraded: the 0.7.6 book (the SQL of the first public commit, read from git),
then tip migrate.ensure, which is what `mill install sql --apply` runs on an
older stamp. The shapes (tables, columns with enum values, indexes, foreign
keys, triggers, routine bodies) must match. A second test puts the drift seen
on the cloud office book into an upgraded copy and requires the diff to name
each part, so the check cannot pass by reading too little.

Card 1068: the previous release is a second upgrade source. It is the newest
final `vX.Y.Z` tag (MILL_PARITY_PREV names another ref), so it moves on by
itself when a release is tagged. A second migrate.ensure on every book must
change nothing. What the upgrade from the previous release dropped or
narrowed is printed and kept as a junit property for a person's schema review;
it never fails the test.
"""
from __future__ import annotations

import json
import os
import re
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
PREV_DB = throwaway_db("mill_parity_prev")
_FINAL_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


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


def _git(*args: str) -> str:
    r = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True)
    if r.returncode:
        raise LookupError(r.stderr.strip()[:200])
    return r.stdout


def _git_show(ref: str, path: str) -> str:
    return _git("show", f"{ref}:{path}")


def previous_release() -> str:
    """MILL_PARITY_PREV, else the newest final vX.Y.Z tag (no rc)."""
    pinned = (os.environ.get("MILL_PARITY_PREV") or "").strip()
    if pinned:
        return pinned
    tags = [t for t in _git("tag", "--list", "v*").split() if _FINAL_TAG.match(t)]
    if not tags:
        raise LookupError("no vX.Y.Z tag")
    return max(tags, key=lambda t: tuple(int(x) for x in _FINAL_TAG.match(t).groups()))


def _old_sql(ref: str, label: str) -> list[tuple[str, str]]:
    """(file, text) for REF's apply order. CI has full history and tags; a
    checkout without them skips, except in CI where it fails."""
    try:
        order = _git_show(ref, "agent_coord/server/sql/apply_order.txt").split()
        return [(n, _git_show(ref, f"agent_coord/server/sql/{n}")) for n in order]
    except (LookupError, OSError) as e:
        if os.environ.get("GITHUB_ACTIONS") == "true":
            raise AssertionError(f"{label} SQL not readable from git in CI: {e}")
        pytest.skip(f"{label} SQL not in this checkout: {e}")


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
    files = _old_sql(OLD, "0.7.6")
    try:
        prev_ref = previous_release()
    except (LookupError, OSError) as e:
        prev_ref = f"(none: {e})"
    prev_files = _old_sql(prev_ref, f"previous release {prev_ref}")
    try:
        fresh = _new_db(FRESH_DB)
        up = _new_db(UP_DB)
        drift = _new_db(DRIFT_DB)
        prev = _new_db(PREV_DB)
    except Exception as e:
        pytest.skip(f"mysql mill records: {e}")
    migrate.ensure(fresh)
    for cn in (up, drift):
        _build_old(cn, files)
        migrate.ensure(cn)
    _build_old(prev, prev_files)
    prev_shape = book_shape.shape(prev)
    migrate.ensure(prev)
    yield {
        "fresh": fresh, "up": up, "drift": drift, "prev": prev,
        "prev_ref": prev_ref, "prev_shape": prev_shape,
    }
    for cn in (fresh, up, drift, prev):
        cn.close()
    admin = _admin()
    cur = admin.cursor()
    for name in (FRESH_DB, UP_DB, DRIFT_DB, PREV_DB):
        cur.execute(f"DROP DATABASE IF EXISTS `{name}`")
    cur.close()
    admin.close()


def test_upgraded_book_has_the_fresh_shape(books) -> None:
    a, b = book_shape.shape(books["fresh"]), book_shape.shape(books["up"])
    assert a, "the fresh shape read nothing"
    for kind in ("table", "column", "index", "fk", "trigger", "routine"):
        assert any(k.startswith(kind + " ") for k in a), kind
    assert book_shape.diff(a, b) == []


def test_previous_release_upgrades_to_the_fresh_shape(books, record_testsuite_property) -> None:
    old = books["prev_shape"]
    assert any(k.startswith("column ") for k in old), books["prev_ref"]
    new = book_shape.shape(books["prev"])
    # For the schema review only: printed and kept in the junit xml, never asserted.
    summary = {"from": books["prev_ref"], **book_shape.review(old, new)}
    record_testsuite_property("schema_review", json.dumps(summary))
    print(f"schema review (card 1068): {json.dumps(summary, indent=1)}")
    assert book_shape.diff(book_shape.shape(books["fresh"]), new) == []


@pytest.mark.parametrize("which", ["fresh", "up", "prev"])
def test_second_ensure_is_a_no_op(books, which) -> None:
    cn = books[which]
    before = book_shape.shape(cn)
    # The shape, not `applied`: some steps re-run refreshes that leave it as is.
    migrate.ensure(cn)
    assert book_shape.diff(before, book_shape.shape(cn)) == []


def test_review_names_dropped_and_narrowed() -> None:
    old = {
        "column t.gone": "int null=YES default=None extra= coll=None",
        "column t.e": "enum('a','b') null=NO default=None extra= coll=x",
        "column t.v": "varchar(64) null=NO default=None extra= coll=x",
        "column t.n": "bigint null=NO default=None extra= coll=None",
        "column t.w": "varchar(10) null=NO default=None extra= coll=x",
        "column t.j": "json null=YES default=None extra= coll=None",
        "column t.same": "int null=NO default=None extra= coll=None",
        "index t.PRIMARY": "unique=1 (id)",
    }
    new = {
        "column t.e": "enum('a') null=NO default=None extra= coll=x",
        "column t.v": "varchar(32) null=NO default=None extra= coll=x",
        "column t.n": "int null=NO default=None extra= coll=None",
        "column t.w": "varchar(20) null=NO default=None extra= coll=x",
        "column t.j": "text null=YES default=None extra= coll=x",
        "column t.same": "int null=YES default=None extra= coll=None",
    }
    assert book_shape.review(old, new) == {
        "dropped": ["column t.gone"],
        "narrowed": [
            "column t.e: enum('a','b') -> enum('a')",
            "column t.n: bigint -> int",
            "column t.v: varchar(64) -> varchar(32)",
        ],
        "changed": ["column t.j: json -> text"],
    }


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
    fresh, drift = books["fresh"], books["drift"]
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
