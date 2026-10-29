"""0.8.0: a desk name mints its seat; cmd_pass never writes todo.evidence (F191, F192).

Lane A dropped todo.evidence and FKs every desk column to seat. mill_name_put must
insert the seat with the desk name (BETA-CHANGES Q3). cmd_pass still UPDATEd the
dropped column after SELECT ... FOR UPDATE; on CI that left the session wedged and
pytest_sql hung past test_doing_flag_818 (~24%) until the job cancelled (~15 min).
"""
from __future__ import annotations

import pytest

from agent_coord.helpers.errors import CoordError
from agent_coord.server.api.mill import rpc
from agent_coord.server.records import name as rec_name
from agent_coord.server.records import todo as rec_todo
from agent_coord.server.records.db import rows_done, scalar_done
from tests.server.records.conftest import seed_names

pytestmark = pytest.mark.sql


class _Book:
    def __init__(self, cn):
        self._cn = cn


def test_mill_name_put_desk_mints_a_seat_row(cn):
    """F191: MILL_NAME_PUT of a desk inserts seat(desk_id) with token NULL."""
    desk = "seatmint-a"
    did = rec_name.get_or_insert(cn, desk, "desk")
    seats = rows_done(cn, "SELECT desk_id, token_hash FROM seat WHERE desk_id = %s", (did,))
    assert seats == [{"desk_id": did, "token_hash": None}], seats


def test_mill_name_put_roster_does_not_mint_a_seat(cn):
    rid = rec_name.get_or_insert(cn, "seatmint-roster", "roster")
    assert scalar_done(cn, "SELECT COUNT(*) FROM seat WHERE desk_id = %s", (rid,)) == 0


def test_cmd_pass_ship_with_evidence_does_not_name_todo_evidence(cn):
    """F192: ship with evidence must not UPDATE the dropped todo.evidence column.

    Repro of the CI hang: FOR UPDATE then UPDATE todo.evidence fails mid-procedure and
    can leave the connection unusable for the rest of the module.
    """
    seed_names(cn, ("unit", "roster"), ("ask189", "desk"), ("vol189", "desk"))
    book = _Book(cn)
    rpc._h_open(book, {"need": "ev189"}, "unit", "ask189")
    rpc._h_claim(book, {"need": "ev189"}, "unit", "vol189")
    # Must not raise Unknown column 'evidence' (the hang precursor).
    got = rpc._h_pass(book, {"need": "ev189", "evidence": "proof-189"}, "unit", "vol189")
    assert got["status"] == "shipped"
    hit = rec_todo.find(cn, "unit", "ev189")
    assert hit["status"] == "shipped"
    # Connection still usable (the hang was the next statement never returning).
    assert scalar_done(cn, "SELECT 1") == 1
    # Evidence lives on the ship move when the write path stores it; either way the
    # SELECT shape must not read todo.evidence.
    cols = {r["COLUMN_NAME"] for r in rows_done(
        cn,
        "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'todo'",
    )}
    assert "evidence" not in cols


def test_cmd_pass_leaves_no_open_row_lock_for_a_peer(cn):
    """After a ship, a second connection must not wait forever on the card row."""
    import mysql.connector
    import threading
    import time

    from agent_coord.server.records.db import conn_kwargs

    seed_names(cn, ("unit", "roster"), ("ask189b", "desk"), ("vol189b", "desk"))
    book = _Book(cn)
    rpc._h_open(book, {"need": "lock189"}, "unit", "ask189b")
    rpc._h_claim(book, {"need": "lock189"}, "unit", "vol189b")
    rpc._h_pass(book, {"need": "lock189", "evidence": "x"}, "unit", "vol189b")
    tid = int(rec_todo.find(cn, "unit", "lock189")["id"])

    kw = dict(conn_kwargs())
    kw.update(database=cn.database, autocommit=True)
    other = mysql.connector.connect(**kw)
    cur = other.cursor()
    cur.execute("SET SESSION innodb_lock_wait_timeout = 3")
    cur.close()
    got = {}

    def peer():
        c = other.cursor()
        try:
            c.execute("SELECT status FROM todo WHERE id = %s FOR UPDATE", (tid,))
            got["row"] = c.fetchone()
            other.commit()
        except Exception as e:
            got["err"] = e
        finally:
            c.close()

    t = threading.Thread(target=peer)
    t.start()
    t.join(10)
    other.close()
    assert t.is_alive() is False, "peer still waiting on a leftover FOR UPDATE"
    assert "err" not in got, got
    assert got.get("row") is not None
