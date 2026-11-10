"""Card 1113: one desk writing cards from several sessions at once never deadlocks.

mill_todo_rename read the card FOR UPDATE, then its UPDATE todo set updated_id to the
renaming desk; the FK check took a shared lock on that desk's seat row, and
mill_doing_move then wanted the seat exclusive (an S-to-X upgrade, deadlock 1213). It
also locked card then seat while every other card write locks seat then card. Each
race here calls the procedure directly: no call() retry, no whole-race retry.
"""
from __future__ import annotations

import json
import threading

import pytest

pytestmark = pytest.mark.sql

from tests import sql_book

from agent_coord.server.records import todo as rec_todo
from agent_coord.server.records.db import _run_proc
from agent_coord.server.records.db import conn_kwargs as _conn_kwargs
from tests.server.records.conftest import seed_names

SESSIONS = 4
PER = 5


def _direct():
    import mysql.connector

    kw = dict(_conn_kwargs())
    kw["database"] = sql_book.shared_db_name()
    return mysql.connector.connect(**kw)


@pytest.fixture(scope="module")
def cn():
    try:
        c = sql_book.connect_shared(reset=True)
    except Exception as e:
        pytest.skip(f"mysql mill records: {e}")
    seed_names(c, ("unit", "roster"), ("a", "desk"), ("b", "desk"))
    yield c
    c.close()


def _proc(c, name: str, args: list) -> None:
    """One CALL on this session: no call() retry, no request transaction."""
    cur = c.cursor()
    try:
        _run_proc(cur, name, args)
    finally:
        cur.close()


def _race(work) -> list[BaseException]:
    errs: list[BaseException] = []

    def run(i: int) -> None:
        c = None
        try:
            c = _direct()
            cur = c.cursor()
            cur.execute("SET SESSION innodb_lock_wait_timeout = 3")
            cur.close()
            work(c, i)
        except BaseException as e:  # noqa: BLE001
            errs.append(e)
        finally:
            if c is not None:
                c.close()

    threads = [threading.Thread(target=run, args=(i,)) for i in range(SESSIONS)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(60)
    return errs


def _cards(cn, n: int, tag: str) -> list[int]:
    # Filed by desk b, so a rename by desk a changes updated_id (the FK check runs).
    return [int(rec_todo.insert(cn, "unit", "b", "open", json.dumps({"need_id": f"{tag}-{k}"}))[0]["id"])
            for k in range(n)]


def test_one_desk_renames_cards_from_four_sessions_without_deadlock(cn) -> None:
    ids = _cards(cn, SESSIONS * PER, "rn")
    cn.commit()

    def work(c, i: int) -> None:
        for j in range(PER):
            cid = ids[i * PER + j]
            new = f"rn-{cid}-new"
            _proc(c, "mill_todo_rename",
                  [cid, "a", f"rn-{i * PER + j}", new, json.dumps({"need_id": new}), "race"])

    errs = _race(work)
    assert not errs, errs
    cn.commit()
    cur = cn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM todo WHERE id IN ({','.join(map(str, ids))}) AND updated_id ="
                " (SELECT id FROM name WHERE type='desk' AND name='a')")
    assert int(cur.fetchone()[0]) == len(ids)
    cur.close()


def test_rename_and_note_on_one_card_by_one_desk_without_deadlock(cn) -> None:
    # Rename locked card then seat; a note (mill_todo_update) locks seat then card.
    ids = _cards(cn, PER * 2, "mx")
    cn.commit()

    def work(c, i: int) -> None:
        for j, cid in enumerate(ids):
            if i % 2 == 0:
                new = f"mx-{cid}-{i}-{j}"
                _proc(c, "mill_todo_rename", [cid, "a", "old", new, json.dumps({"need_id": new}), "race"])
            else:
                _proc(c, "mill_todo_update", [cid, "a", "", "", json.dumps({"need_id": f"mx-{cid}", "note": f"{i}.{j}"})])

    errs = _race(work)
    assert not errs, errs
