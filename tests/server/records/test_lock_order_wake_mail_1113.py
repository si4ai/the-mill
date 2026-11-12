"""Card 1113: wake, mail, join, plan and status procedures never deadlock or lock what they only read.

Each race calls the procedures directly on separate sessions: no call() retry, no whole-race
retry. A refused call (a row another session already took) is fine; only 1213 (deadlock) or
1205 (lock wait timeout) fails a race. The data_locks tests hold one call's transaction open
and read performance_schema.data_locks for that session.
"""
from __future__ import annotations

import json
import threading

import pytest

pytestmark = pytest.mark.sql

from tests import sql_book

from agent_coord.server.records import mail as rec_mail
from agent_coord.server.records import todo as rec_todo
from agent_coord.server.records.db import _run_proc
from agent_coord.server.records.db import conn_kwargs as _conn_kwargs
from tests.server.records.conftest import seed_names

ROUNDS = 6


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
    seed_names(c, ("unit", "roster"), ("a", "desk"), ("b", "desk"), ("c", "desk"))
    cur = c.cursor()
    # A joined seat (join_* refuse a desk that never joined). Test schema only.
    cur.execute("UPDATE seat SET token_hash = REPEAT('0', 64)"
                " WHERE desk_id IN (SELECT id FROM name WHERE type = 'desk' AND name IN ('a', 'b', 'c'))")
    cur.close()
    c.commit()
    yield c
    c.close()


def _call(c, name: str, args: list) -> list[dict]:
    """One CALL, then commit: no call() retry, no request transaction."""
    cur = c.cursor()
    try:
        rows = _run_proc(cur, name, args)
        c.commit()
        return rows
    finally:
        cur.close()


def _lock_error(e: BaseException) -> bool:
    return getattr(e, "errno", None) in (1213, 1205)


def _race(works) -> list[BaseException]:
    errs: list[BaseException] = []

    def run(fn) -> None:
        c = None
        try:
            c = _direct()
            cur = c.cursor()
            cur.execute("SET SESSION innodb_lock_wait_timeout = 3")
            cur.close()
            fn(c)
        except BaseException as e:  # noqa: BLE001
            if _lock_error(e):
                errs.append(e)
        finally:
            if c is not None:
                c.close()

    threads = [threading.Thread(target=run, args=(w,)) for w in works]
    for th in threads:
        th.start()
    for th in threads:
        th.join(60)
    return errs


def _tolerant(c, name: str, args: list) -> None:
    try:
        _call(c, name, args)
    except Exception as e:  # noqa: BLE001
        if _lock_error(e):
            raise
        c.rollback()


def _desk_id(cn, desk: str) -> int:
    cur = cn.cursor()
    cur.execute("SELECT id FROM name WHERE type = 'desk' AND name = %s", (desk,))
    (v,) = cur.fetchone()
    cur.close()
    cn.commit()
    return int(v)


def _wakes(cn, desk: str, kind: str, keys, state: str = "queued") -> list[int]:
    for k in keys:
        _call(cn, "mill_push_put", [desk, kind, json.dumps({"id": k}), "queued"])
    cur = cn.cursor()
    cur.execute("SELECT w.id FROM wake w JOIN name n ON n.id = w.desk_id"
                " WHERE n.name = %s AND w.state = 'queued' ORDER BY w.id", (desk,))
    ids = [int(r[0]) for r in cur.fetchall()]
    cur.close()
    cn.commit()
    if state == "sent":
        for i in ids:
            _call(cn, "cmd_push_mark", [i, "sent"])
    return ids


def test_push_mark_alongside_push_take(cn) -> None:
    # The push worker marks one wake row while the desk's sync takes all of them: each copied the
    # rows into transition (shared) before updating them (exclusive).
    errs: list[BaseException] = []
    for r in range(ROUNDS):
        ids = _wakes(cn, "a", "hint", range(1000 + r * 10, 1006 + r * 10))

        def take(c) -> None:
            for _ in range(3):
                _call(c, "mill_push_take", ["a"])

        def mark(c, ids=ids) -> None:
            for i in ids:
                _call(c, "cmd_push_mark", [i, "sent"])

        errs += _race([take, mark, take, mark])
    assert not errs, errs


def test_push_sent_and_put_back_on_one_desks_rows(cn) -> None:
    desk = _desk_id(cn, "b")
    errs: list[BaseException] = []
    for r in range(ROUNDS):
        ids = _wakes(cn, "b", "hint", range(2000 + r * 10, 2006 + r * 10), state="sent")

        def sent(c, ids=ids) -> None:
            _call(c, "cmd_push_sent", [desk, json.dumps(ids)])

        def back(c, ids=ids) -> None:
            for i in ids:
                _call(c, "cmd_push_put_back", [i, json.dumps({"id": i, "idem": "k"})])

        errs += _race([back, back, sent, back])
    assert not errs, errs


def test_two_mail_deletes_at_once(cn) -> None:
    # The wake filter is on the payload JSON: the shared copy locked every wake row it scanned.
    errs: list[BaseException] = []
    for r in range(ROUNDS):
        mids = [int(rec_mail.insert(cn, "unit", "a", "b", f"del {r}.{k}")[0]["id"]) for k in range(8)]
        cn.commit()
        _wakes(cn, "b", "mail", mids)

        def dele(c, part) -> None:
            for m in part:
                _call(c, "mill_mail_delete", [m, "a"])

        halves = [[m for k, m in enumerate(mids) if k % 2 == side] for side in (0, 1)]
        errs += _race([lambda c, p=half: dele(c, p) for half in halves])
    assert not errs, errs


def test_mail_replace_from_four_sessions(cn) -> None:
    mid = int(rec_mail.insert(cn, "unit", "a", "b", "edit me")[0]["id"])
    cn.commit()

    def edit(c) -> None:
        for k in range(10):
            cur = c.cursor()
            cur.execute("SELECT IFNULL(body_updated, created) FROM mail WHERE id = %s", (mid,))
            (stamp,) = cur.fetchone()
            cur.close()
            _tolerant(c, "mill_body_replace", ["mail", mid, "a", f"edit {k}", stamp])

    assert not _race([edit] * 4)


def test_join_heartbeats_from_four_sessions(cn) -> None:
    # The joined-seat check read the seat shared, then the heartbeat updated it.
    def beat(c) -> None:
        for k in range(10):
            _call(c, "mill_join_touch", ["c"])
            _call(c, "mill_join_connect", ["c"])

    def wake(c) -> None:
        for k in range(10):
            _call(c, "mill_join_wake_arm", ["c", "https://host.test/w", "k", "addressed"])
            _call(c, "mill_join_wake_off", ["c"])

    assert not _race([beat, beat, wake, wake])


def _plan(cn, tag: str, n: int) -> list[int]:
    ids = [int(rec_todo.insert(cn, "unit", "a", "open", json.dumps({"need_id": f"{tag}-{k}"}))[0]["id"])
           for k in range(n + 1)]
    cn.commit()
    _call(cn, "mill_tree_create", [tag, "todo", ids[0]])
    for cid in ids[1:]:
        _call(cn, "mill_tree_add", [tag, "todo", ids[0], "todo", cid])
    return ids[1:]


def test_plan_removes_of_different_cards_at_once(cn) -> None:
    # The node check read the card's tree row shared; a remove of another card on the plan then
    # shifted that row (exclusive) under the plan lock.
    errs: list[BaseException] = []
    for r in range(ROUNDS):
        ids = _plan(cn, f"plr{r}", 8)
        errs += _race([lambda c, p=ids[k::4], r=r: [_tolerant(c, "mill_tree_remove", [f"plr{r}", "todo", i])
                                                     for i in p] for k in range(4)])
    assert not errs, errs


def test_card_deletes_on_one_plan_at_once(cn) -> None:
    errs: list[BaseException] = []
    for r in range(ROUNDS):
        ids = _plan(cn, f"pld{r}", 8)
        errs += _race([lambda c, p=ids[k::4]: [_tolerant(c, "mill_todo_delete", [i, "a"]) for i in p]
                       for k in range(4)])
    assert not errs, errs


def _locks_held(cn, proc: str, args: list) -> set[tuple[str, str, str]]:
    """(table, index, mode) record locks one call holds before its commit (request tx kept open)."""
    pf = _direct()
    c = _direct()
    try:
        k = c.cursor()
        k.execute("SET @mill_req_tx = 1")
        k.execute("START TRANSACTION")
        k.execute("SELECT PS_CURRENT_THREAD_ID()")
        (tid,) = k.fetchone()
        _run_proc(k, proc, args)
        p = pf.cursor()
        p.execute("SELECT OBJECT_NAME, INDEX_NAME, LOCK_MODE FROM performance_schema.data_locks"
                  " WHERE THREAD_ID = %s AND LOCK_TYPE = 'RECORD'", (tid,))
        rows = {(str(t), str(i), str(m)) for t, i, m in p.fetchall()}
        p.close()
        c.rollback()
        return rows
    finally:
        c.close()
        pf.close()


def test_plan_detach_reads_the_tree_without_a_shared_lock(cn) -> None:
    # mill_tree_remove's node check and mill_tree_detach's plan lookup read the item's tree rows
    # shared; the detach then shifts those rows exclusive under the plan lock.
    ids = _plan(cn, "pls", 3)
    for proc, args in (("mill_tree_remove", ["pls", "todo", ids[0]]), ("mill_todo_delete", [ids[1], "a"])):
        held = _locks_held(cn, proc, args)
        # Only the rows the reads find (by the item: idx_activity, then PRIMARY). The lft/rgt shift's
        # own unique checks on idx_lft / idx_rgt are part of the UPDATE, not a read.
        assert not {h for h in held if h[0] == "tree" and h[1] in ("PRIMARY", "idx_activity")
                    and h[2].startswith("S")}, (proc, held)


def test_mail_delete_locks_only_its_own_wake_rows(cn) -> None:
    # The payload filter has no index: a locking read there locked every wake row it scanned.
    mid = int(rec_mail.insert(cn, "unit", "a", "b", "one wake")[0]["id"])
    cn.commit()
    _wakes(cn, "b", "mail", [mid, 900001, 900002, 900003])
    held = _locks_held(cn, "mill_mail_delete", [mid, "a"])
    wake = {h for h in held if h[0] == "wake"}
    assert not {h for h in wake if h[2].startswith("S")}, held
    cur = _direct()
    try:
        k = cur.cursor()
        k.execute("SELECT COUNT(*) FROM wake WHERE cause = 'mail' AND state <> 'taken'"
                  " AND CAST(JSON_UNQUOTE(JSON_EXTRACT(payload, '$.id')) AS UNSIGNED) <> %s", (mid,))
        (others,) = k.fetchone()
    finally:
        cur.close()
    assert others >= 3


def test_doing_now_takes_no_row_locks(cn) -> None:
    # The desk list went through INSERT INTO a temp table ... SELECT FROM seat JOIN name, a locking
    # read: a status read held shared locks on every listed seat and name row.
    assert _locks_held(cn, "mill_doing_now", ["a", "", 0]) == set()
    assert _locks_held(cn, "mill_doing_now", ["", "", 1]) == set()


def test_mail_recipient_remove_locks_only_what_it_writes(cn) -> None:
    root = int(rec_mail.insert(cn, "unit", "a", "b", "root")[0]["id"])
    cn.commit()
    _call(cn, "mill_mail_to_node_put", [root, _desk_id(cn, "c")])
    held = _locks_held(cn, "mill_mail_to_node_delete", [root, _desk_id(cn, "c")])
    shared = {h for h in held if h[2].startswith("S")}
    assert not shared, held
