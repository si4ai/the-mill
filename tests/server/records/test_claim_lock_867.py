"""cmd_claim reads the card FOR UPDATE (card 867, Validator letter 2944).

Two connections. A claims inside an open transaction and holds the row. B
claims the same card without --take-over. With the row lock B waits, then reads
A's claim and is refused (card:claimed_by). Without it B reads the old open row,
waits only at the UPDATE, and overwrites A's claim. The take-over line names the
prior volunteer read under that lock: a stale prior is refused and re-read.
"""
from __future__ import annotations

import threading
import time

import pytest

from agent_coord.helpers.errors import CoordError
from agent_coord.server.api.mill import rpc
from agent_coord.server.records import todo as rec_todo
from tests.server.records.conftest import seed_names

pytestmark = pytest.mark.sql

R = "lock867"
ASKER, A, B, C = "la867", "lka867", "lkb867", "lkc867"


class _Book:
    def __init__(self, cn):
        self._cn = cn


def _second(cn):
    import mysql.connector

    from agent_coord.server.records.db import conn_kwargs

    cur = cn.cursor()
    cur.execute("SELECT DATABASE()")
    db = cur.fetchone()[0]
    cur.close()
    kw = conn_kwargs()
    kw.update(database=db, autocommit=False, use_pure=True)
    other = mysql.connector.connect(**kw)
    c = other.cursor()
    c.execute("SET SESSION innodb_lock_wait_timeout = 20")
    c.close()
    return other


def _call(cn, sql, args):
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


def _waits_on_a_lock(cn, t, thread_id, hold=1.0, limit=15.0):
    """True once B's connection has sat in cmd_claim's guard read for `hold` seconds.

    With FOR UPDATE, B blocks on the guard SELECT until A commits.
    Without it, B reads past the guards and blocks in the UPDATE instead.
    The processlist shows which statement B is stuck in, so the test can tell
    the two apart without depending on timing.
    """
    end = time.monotonic() + limit
    since = None
    while time.monotonic() < end and t.is_alive():
        cur = cn.cursor()
        try:
            cur.execute(
                "SELECT INFO FROM information_schema.PROCESSLIST WHERE ID = %s",
                (thread_id,),
            )
            row = cur.fetchone()
        finally:
            cur.close()
        info = (row[0] or "") if row else ""
        if info.lstrip().startswith("SELECT t.status"):
            since = since or time.monotonic()
            if time.monotonic() - since >= hold:
                return True
        else:
            since = None
        time.sleep(0.05)
    return False


@pytest.fixture()
def book(cn, monkeypatch):
    seed_names(cn, (R, "roster"), (ASKER, "desk"), (A, "desk"), (B, "desk"), (C, "desk"))
    monkeypatch.setattr(rpc, "_poke", lambda *a, **k: None)
    return _Book(cn)


def test_a_second_claim_waits_on_the_row_lock_and_is_refused(book, cn):
    rpc._h_open(book, {"need": "race"}, R, ASKER)
    tid = int(rec_todo.find(cn, R, "race")["id"])
    # Pure-Python connections: the C extension is not used across threads here.
    first, second, watch = _second(cn), _second(cn), _second(cn)
    claim = "CALL cmd_claim(MILL_DESK_ID(%s), %s, 0, '', NULL)"
    got: dict = {}
    try:
        _call(first, claim, (A, tid))  # holds the card row until the commit below

        def other():
            try:
                _call(second, claim, (B, tid))
                second.commit()
                got["ok"] = True
            except Exception as e:  # the refusal
                second.rollback()
                got["err"] = str(e)

        t = threading.Thread(target=other)
        t.start()
        assert _waits_on_a_lock(watch, t, second.connection_id), "B did not wait on A's row lock"
        first.commit()
        t.join(30)
        assert "card:claimed_by:" + A in got.get("err", ""), got
        assert rec_todo.find(cn, R, "race")["assigned"] == A
    finally:
        for x in (first, second, watch):
            x.close()


def test_take_over_names_the_prior_read_under_the_lock(book, cn, monkeypatch):
    """The handler read A as the volunteer; C took the card before the CALL. The line names C."""
    rpc._h_open(book, {"need": "stale"}, R, ASKER)
    rpc._h_claim(book, {"need": "stale"}, R, A)
    stale = dict(rec_todo.find(cn, R, "stale"))
    rpc._h_claim(book, {"need": "stale", "take_over": True}, R, C)
    real = rpc._card_hit
    reads = []

    def card_hit(c, project, need):
        reads.append(need)
        return dict(stale) if len(reads) == 1 else real(c, project, need)

    monkeypatch.setattr(rpc, "_card_hit", card_hit)
    rec = rpc._h_claim(book, {"need": "stale", "take_over": True}, R, B)
    assert rec["prior_volunteer"] == C
    detail = rec_todo.unpack(rec_todo.find(cn, R, "stale")["body"], None)["detail"]
    assert detail.splitlines()[-1] == f"took over from {C}"
    assert f"took over from {A}\ntook over from {A}" not in detail
    assert len(reads) == 2


def test_a_take_over_that_keeps_going_stale_is_refused(book, cn, monkeypatch):
    rpc._h_open(book, {"need": "flaky"}, R, ASKER)
    rpc._h_claim(book, {"need": "flaky"}, R, A)
    stale = dict(rec_todo.find(cn, R, "flaky"))
    rpc._h_claim(book, {"need": "flaky", "take_over": True}, R, C)
    monkeypatch.setattr(rpc, "_card_hit", lambda c, project, need: dict(stale))
    with pytest.raises(CoordError, match=f"claim: {R}/flaky changed volunteer while claiming; nothing changed"):
        rpc._h_claim(book, {"need": "flaky", "take_over": True}, R, B)
    assert rec_todo.find(cn, R, "flaky")["assigned"] == C
