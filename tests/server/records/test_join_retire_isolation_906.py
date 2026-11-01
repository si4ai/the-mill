"""F195 / card 906: join must not mint a token for a desk retired while join waited.

mill_join_upsert must read name.deleted in the same SELECT ... FOR UPDATE that
takes the name lock (not a later plain SELECT). A plain re-check depends on
isolation and on stored-program read quirks; the locking read makes the wrong
move impossible under REPEATABLE READ without setting a session level.

SPIN N03 (PR #236) models the plain re-check as reading the pre-lock snapshot.
This suite locks that down in SQL and in a two-connection join-vs-retire race.
"""
from __future__ import annotations

import re
import threading
import time
from pathlib import Path

import mysql.connector
import pytest
from agent_coord.client.tokens import token_hash
from agent_coord.server.records import join as rec_join
from agent_coord.server.records import name as rec_name
from agent_coord.server.records.db import conn_kwargs, rows_done
from tests.server.records.conftest import admin_desk, seed_names

pytestmark = pytest.mark.sql

@pytest.fixture(scope="module", autouse=True)
def _restore_tip_routines_after_trust(cn):
    """set_trust rewrites b_trust; put tip routines back for the shared book."""
    yield
    from tests import sql_book
    sql_book.restore_tip_routines(cn)

ROSTER = "jri906"
ADMIN = "jri906-adm"
DESK = "jri906-d"

_SP_JOIN = Path(__file__).resolve().parents[3] / "agent_coord" / "server" / "sql" / "sp_join.sql"


def _mill_join_upsert_body() -> str:
    text = _SP_JOIN.read_text(encoding="utf-8")
    m = re.search(
        r"CREATE PROCEDURE mill_join_upsert\b.*?^END //",
        text,
        flags=re.M | re.S,
    )
    assert m, "mill_join_upsert not found in sp_join.sql"
    return m.group(0)


def test_join_name_lock_reads_deleted_in_for_update():
    """The name-row lock must fetch deleted in the locking read itself (F195)."""
    body = _mill_join_upsert_body()
    # One locking read of id and deleted; no separate plain re-check of deleted.
    assert re.search(
        r"SELECT\s+id\s*,\s*deleted\s+INTO\s+\w+\s*,\s*\w+\s+FROM\s+name\s+"
        r"WHERE\s+id\s*=\s*\w+\s+FOR\s+UPDATE",
        body,
        flags=re.I,
    ), "mill_join_upsert must SELECT id, deleted ... FOR UPDATE on name"
    assert not re.search(
        r"IF\s*\(\s*SELECT\s+deleted\s+FROM\s+name\s+WHERE\s+id\s*=",
        body,
        flags=re.I,
    ), "plain SELECT deleted re-check after the lock must go; read deleted under FOR UPDATE"


def _second(cn):
    cur = cn.cursor()
    cur.execute("SELECT DATABASE()")
    db = cur.fetchone()[0]
    cur.close()
    kw = conn_kwargs()
    kw.update(database=db, autocommit=False, use_pure=True)
    other = mysql.connector.connect(**kw)
    c = other.cursor()
    c.execute("SET SESSION innodb_lock_wait_timeout = 20")
    c.execute("SET SESSION transaction_isolation = 'REPEATABLE-READ'")
    c.close()
    return other


def _run(cn, sql: str, args=()) -> None:
    cur = cn.cursor()
    try:
        cur.execute(sql, args)
        while True:
            if cur.with_rows:
                cur.fetchall()
            if not cur.nextset():
                break
    finally:
        cur.close()


def _waiting(cn, thread_id: int, limit: float = 10.0) -> bool:
    kw = conn_kwargs()
    cur = cn.cursor()
    cur.execute("SELECT DATABASE()")
    db = cur.fetchone()[0]
    cur.close()
    kw.update(database=db, autocommit=True, use_pure=True)
    probe = mysql.connector.connect(**kw)
    try:
        deadline = time.time() + limit
        while time.time() < deadline:
            c = probe.cursor(dictionary=True)
            c.execute(
                "SELECT TRX_QUERY, TRX_STATE FROM information_schema.INNODB_TRX"
                " WHERE TRX_MYSQL_THREAD_ID = %s",
                (thread_id,),
            )
            row = c.fetchone()
            c.close()
            if row and row.get("TRX_STATE") == "LOCK WAIT":
                return True
            time.sleep(0.05)
        return False
    finally:
        probe.close()


def _desk_id(cn, desk: str) -> int:
    rows = rows_done(cn, "SELECT id FROM name WHERE type='desk' AND name=%s", (desk,))
    return int(rows[0]["id"])


def _token(cn, desk: str):
    rows = rows_done(
        cn,
        "SELECT token_hash FROM seat WHERE desk_id = %s",
        (_desk_id(cn, desk),),
    )
    return rows[0]["token_hash"] if rows else None


@pytest.fixture
def book(cn):
    from tests.beta_book import set_trust

    seed_names(cn, (ROSTER, "roster"))
    admin_desk(cn, ADMIN)
    rec_name.get_or_insert(cn, DESK, "desk")
    cn.commit()
    assert _token(cn, DESK) is None
    set_trust(cn, "high")
    cur = cn.cursor()
    cur.execute("SET SESSION transaction_isolation = 'REPEATABLE-READ'")
    cur.close()
    yield cn


def test_join_waiting_on_name_lock_sees_a_concurrent_retire(book):
    """A retire that commits while join waits on the name row must refuse the join."""
    retire, joiner = _second(book), _second(book)
    digest = token_hash("fresh-after-retire-" + DESK)
    err: list[BaseException] = []
    ready = threading.Event()
    try:
        desk_id = _desk_id(book, DESK)
        _run(retire, "START TRANSACTION")
        _run(retire, "SELECT id, deleted FROM name WHERE id = %s FOR UPDATE", (desk_id,))

        def do_join():
            try:
                ready.set()
                rec_join.upsert(joiner, ROSTER, DESK, "", digest, None)
                joiner.commit()
            except BaseException as e:  # noqa: BLE001
                err.append(e)
                try:
                    joiner.rollback()
                except Exception:
                    pass

        t = threading.Thread(target=do_join)
        t.start()
        assert ready.wait(5)
        assert _waiting(book, joiner.connection_id), "join should block on name FOR UPDATE"

        _run(retire, "UPDATE name SET deleted = NOW(6) WHERE id = %s", (desk_id,))
        _run(
            retire,
            "UPDATE seat SET token_hash = NULL, time_disconnect = NOW(6) WHERE desk_id = %s",
            (desk_id,),
        )
        _run(retire, "COMMIT")

        t.join(20)
        assert t.is_alive() is False
        assert err, "join must refuse after a concurrent retire"
        assert any("retired" in str(e).lower() for e in err), err
        book.rollback()
        assert _token(book, DESK) is None
    finally:
        try:
            retire.rollback()
        except Exception:
            pass
        retire.close()
        joiner.close()
