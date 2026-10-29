"""0.8.0 lane B: doing is the history of card and hold moves (the owner, 2026-10-26).

F174 focus rows and move rows: seat.doing_id names the desk's newest focus row, never a move row; a
card move by another desk never ends an entry; the desk's own ship, done or drop on its focus item ends
it as finished; a move with --doing writes the move row, then the focus row.
F175 the fold: reading an item's move rows in id order rebuilds todo.status, todo.assigned_id and
hold.desk_id.
F182 (Validator check 3): concurrent card writes read the old state FOR UPDATE, so the chain of moves
stays whole. Mutant: drop FOR UPDATE from mill_todo_write's read; the second writer reads the stale
state, writes no move and the fold no longer matches the card.
F183 (Validator check 7): the deadlock pairs (retire vs hold take; card pass vs doing finish) take the
seat first and never deadlock.
F184 (Validator check 6): a re-open keeps the first opened time and pushes one receipt; opening a
letter and the heartbeats (connect, touch, socket, LAN) leave activity and doing unchanged.
F185: hold take and drop write move rows, a refresh writes none, reset's drop rows name the acting
desk; evidence over 512 characters is refused (where longer evidence goes is pending the owner).
"""
from __future__ import annotations

import threading

import mysql.connector
import pytest

from agent_coord.client.tokens import token_hash
from agent_coord.server.records import doing as rec_doing
from agent_coord.server.records import hold as rec_hold
from agent_coord.server.records import join as rec_join
from agent_coord.server.records import mail as rec_mail
from agent_coord.server.records import name as rec_name
from agent_coord.server.records import opened as rec_opened
from agent_coord.server.records import todo as rec_todo
from agent_coord.server.records.db import call, rows_done, scalar_done
from tests.server.records.conftest import seed_names

pytestmark = pytest.mark.sql

ROSTER = "mv080"
ADMIN = "mv080-adm"
ANN = "mv080-ann"
BOB = "mv080-bob"


def _seat(cn, desk: str) -> str:
    digest = token_hash("seat-" + desk)
    rec_join.upsert(cn, ROSTER, desk, "", digest, None)
    cn.commit()
    return digest


@pytest.fixture(scope="module")
def book(cn):
    from tests.beta_book import set_trust

    seed_names(cn, (ROSTER, "roster"))
    for d in (ADMIN, ANN, BOB):
        _seat(cn, d)
    call(cn, "sp_admin_set", [None, ADMIN, 1])
    set_trust(cn, "high")
    yield cn


def _id(cn, desk: str) -> int:
    return int(scalar_done(cn, "SELECT id FROM name WHERE type='desk' AND name=%s", (desk,)))


def _card(cn, slug: str, status: str = "open") -> int:
    rows = rec_todo.insert(cn, ROSTER, ANN, status, '{"slug": "%s"}' % slug)
    cn.commit()
    return int(rows[-1]["id"])


def _claim(cn, desk: str, card: int, take_over: int = 0, prior: str = "") -> None:
    call(cn, "cmd_claim", [_id(cn, desk), card, take_over, prior, None])
    cn.commit()


def _pass(cn, desk: str, card: int, step: str, ev=None):
    rows = call(cn, "cmd_pass", [_id(cn, desk), card, step, ev])
    cn.commit()
    return rows[-1]


def _moves(cn, on_type: str, on_id: int) -> list[dict]:
    return rows_done(
        cn,
        "SELECT id, act, desk_id, peer_id, text FROM doing"
        " WHERE on_type = %s AND on_id = %s AND act NOT IN ('focus', 'clear', 'finish') ORDER BY id",
        (on_type, on_id),
    )


def _seat_row(cn, desk: str):
    return scalar_done(cn, "SELECT doing_id FROM seat WHERE desk_id = %s", (_id(cn, desk),))


def _fold_card(rows: list[dict]) -> tuple:
    """The documented fold (BETA-CHANGES.md, the act list; C4): status and volunteer from the moves."""
    status, vol = None, None
    for r in rows:
        act, desk, peer = r["act"], r["desk_id"], r["peer_id"]
        if act == "create":
            status, vol = "open", None
        elif act == "park":
            status, vol = "parked", None
        elif act == "claim":
            status, vol = ("claimed" if status in ("open", "parked", "claimed") else status), desk
        elif act == "assign":
            status, vol = ("claimed" if status in ("open", "parked", "claimed") else status), peer
        elif act == "unclaim":
            status, vol = ("open" if status == "claimed" else status), None
        elif act == "unpark":
            status = "open"
        elif act == "ship":
            status = "shipped"
        elif act == "done":
            status = "done"
        elif act == "back":
            status = "shipped" if status == "done" else ("claimed" if vol is not None else "open")
    return status, vol


def _card_now(cn, card: int) -> tuple:
    r = rows_done(cn, "SELECT status, assigned_id FROM todo WHERE id = %s", (card,))[0]
    return r["status"], r["assigned_id"]


# ---------- F174 focus rows and move rows ----------

def test_a_move_never_moves_seat_doing_id(book):
    card = _card(book, "mv-seat")
    rec_doing.put(book, BOB, "on it", "todo", card)
    book.commit()
    focus = _seat_row(book, BOB)
    _claim(book, BOB, card)
    _pass(book, BOB, card, "ship", "sha 1")
    assert _seat_row(book, BOB) == focus
    assert scalar_done(book, "SELECT act FROM doing WHERE id = %s", (focus,)) == "focus"


def test_another_desks_move_does_not_end_the_entry_and_my_ship_finishes_it(book):
    card = _card(book, "mv-end")
    _claim(book, BOB, card)
    rec_doing.put(book, BOB, "fixing it", "todo", card)
    book.commit()
    # ANN's move on the card (an unclaim, then BOB claims back) does not end BOB's entry
    rec_todo.update(book, card, ANN, "open", "-", None)
    book.commit()
    _claim(book, BOB, card)
    rows = [r for r in rec_doing.now(book, BOB) if r.get("part") == "desk"]
    assert rows[0]["ended_by"] is None and rows[0]["act"] == "focus"
    _pass(book, BOB, card, "ship", "sha 2")
    rows = [r for r in rec_doing.now(book, BOB) if r.get("part") == "desk"]
    assert rows[0]["ended_by"] == "finished"
    hist = call(book, "mill_doing_history", [BOB, None, 1, 50, "", None])
    assert hist and all(h["act"] == "focus" for h in hist)


def test_a_move_with_doing_writes_the_move_then_the_focus(book):
    card = _card(book, "mv-two")
    _claim(book, BOB, card)
    _pass(book, BOB, card, "ship", "sha 3")
    rec_doing.put(book, BOB, "watching CI", "todo", card)  # what rpc's _doing_after does after the command
    book.commit()
    rows = rows_done(
        book, "SELECT id, act FROM doing WHERE desk_id = %s AND on_type = 'todo' AND on_id = %s ORDER BY id",
        (_id(book, BOB), card),
    )
    assert [r["act"] for r in rows][-2:] == ["ship", "focus"]
    assert _seat_row(book, BOB) == rows[-1]["id"]


# ---------- F175 the fold ----------

def test_folding_moves_rebuilds_status_volunteer_and_hold(book):
    a = _card(book, "mv-fold-a")
    _claim(book, BOB, a)
    _claim(book, ANN, a, 1, BOB)  # take-over is claim; peer = the previous volunteer
    _pass(book, ANN, a, "ship", "sha f1")
    _pass(book, ANN, a, "back")
    _pass(book, ANN, a, "ship", "sha f2")
    _pass(book, ANN, a, "done")
    _pass(book, ANN, a, "back")
    assert _fold_card(_moves(book, "todo", a)) == _card_now(book, a)
    take = [r for r in _moves(book, "todo", a) if r["act"] == "claim"][1]
    assert (take["desk_id"], take["peer_id"]) == (_id(book, ANN), _id(book, BOB))
    p = _card(book, "mv-fold-p", "parked")
    assert _fold_card(_moves(book, "todo", p)) == _card_now(book, p) == ("parked", None)
    h = int(rec_hold.upsert(book, ROSTER, BOB, "mv080-res")[-1]["id"])
    book.commit()
    rec_hold.delete(book, h, BOB)
    book.commit()
    rec_hold.upsert(book, ROSTER, ANN, "mv080-res")
    book.commit()
    held = None
    for r in _moves(book, "hold", h):
        held = r["desk_id"] if r["act"] == "hold" else None
    assert held == scalar_done(book, "SELECT desk_id FROM hold WHERE id = %s", (h,)) == _id(book, ANN)


# ---------- F185 hold rows, reset actor, evidence cap ----------

def test_hold_refresh_writes_no_row_and_reset_drops_by_the_acting_desk(book):
    desk = "mv080-hr"
    _seat(book, desk)
    h = int(rec_hold.upsert(book, ROSTER, desk, "mv080-hr-res")[-1]["id"])
    book.commit()
    rec_hold.upsert(book, ROSTER, desk, "mv080-hr-res")  # refresh
    book.commit()
    assert [r["act"] for r in _moves(book, "hold", h)] == ["hold"]
    rec_join.reset(book, ROSTER, desk)
    book.commit()
    last = _moves(book, "hold", h)[-1]
    assert (last["act"], last["desk_id"], last["peer_id"]) == ("drop", _id(book, desk), None)


def test_evidence_over_512_is_refused_pending_the_owner(book):
    card = _card(book, "mv-long")
    _claim(book, BOB, card)
    with pytest.raises(mysql.connector.Error) as ei:
        _pass(book, BOB, card, "ship", "x" * 513)
    book.rollback()
    assert "pending the owner" in str(ei.value)
    assert _card_now(book, card)[0] == "claimed"
    assert _pass(book, BOB, card, "ship", "\u00e9" * 512)["evidence"] == "\u00e9" * 512


def test_a_desk_cannot_retire_another_desk_with_its_own_seat(book):
    desk = "mv080-other"
    _seat(book, desk)
    mine = token_hash("seat-" + ANN)
    with pytest.raises(mysql.connector.Error):
        rec_name.retire(book, desk, "desk", by=ANN, by_hash=mine)
    book.rollback()
    assert rec_join.token_hash_for_desk(book, desk)


# ---------- F184 opens and heartbeats ----------

def _snap(cn, desk: str) -> tuple:
    d = _id(cn, desk)
    act = rows_done(cn, "SELECT type, id, updated, act, desk_id FROM activity ORDER BY type, id")
    return (tuple(tuple(r.values()) for r in act),
            scalar_done(cn, "SELECT COUNT(*) FROM doing WHERE desk_id = %s", (d,)))


def test_a_reopen_keeps_the_first_open_and_one_receipt(book, monkeypatch):
    import agent_coord.server.mail_push as mp

    pushed = []
    monkeypatch.setattr(mp, "push_receipt", lambda cn, row: pushed.append(row["id"]))
    mid = int(rec_mail.insert(book, ROSTER, ANN, BOB, "please look", 1)[-1]["id"])
    book.commit()
    before = _snap(book, BOB)
    first = rec_opened.insert(book, mid, BOB)[-1]["opened"]
    book.commit()
    again = rec_opened.insert(book, mid, BOB)[-1]["opened"]
    book.commit()
    stored = scalar_done(book, "SELECT opened FROM mail_to WHERE type='mail' AND id=%s AND desk_id=%s",
                         (mid, _id(book, BOB)))
    assert first == again == stored
    assert pushed == [mid]
    assert _snap(book, BOB) == before


def test_heartbeats_leave_activity_and_doing_alone(book):
    before = _snap(book, BOB)
    call(book, "mill_join_connect", [BOB])
    rec_join.touch(book, ROSTER, BOB)
    rec_join.mark_socket(book, BOB, up=True)
    rec_join.set_lan_ip(book, BOB, "192.0.2.10")
    book.commit()
    assert _snap(book, BOB) == before


# ---------- F182 and F183: two connections ----------

def _second(cn):
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
    import time

    from agent_coord.server.records.db import conn_kwargs

    # A fresh autocommit connection: the module-scoped book may be mid-result-set.
    kw = conn_kwargs()
    cur = cn.cursor()
    cur.execute("SELECT DATABASE()")
    db = cur.fetchone()[0]
    cur.close()
    kw.update(database=db, autocommit=True, use_pure=True)
    probe = mysql.connector.connect(**kw)
    try:
        end = time.monotonic() + limit
        while time.monotonic() < end:
            c = probe.cursor()
            try:
                c.execute(
                    "SELECT trx_state FROM information_schema.INNODB_TRX"
                    " WHERE trx_mysql_thread_id = %s",
                    (thread_id,),
                )
                row = c.fetchone()
            finally:
                c.close()
            if row and row[0] == "LOCK WAIT":
                return True
            time.sleep(0.05)
        return False
    finally:
        probe.close()


def test_concurrent_card_writes_keep_the_chain(book):
    card = _card(book, "mv-race")
    a, b = _second(book), _second(book)
    try:
        _run(a, "START TRANSACTION")
        _run(a, "SET @mill_req_tx = 1")
        # Lock the card first so the overlapping writer is sure to wait (seat lock alone can
        # race the poller on a fast host; the card row is what the fold protects).
        _run(a, "SELECT id FROM todo WHERE id = %s FOR UPDATE", (card,))
        _run(a, "CALL mill_todo_write(%s, %s, 'claimed', %s, NULL, NULL)", (card, ANN, BOB))
        err = []
        ready = threading.Event()

        def other():
            try:
                _run(b, "SET @mill_req_tx = NULL")
                ready.set()
                _run(b, "CALL mill_todo_write(%s, %s, 'open', '-', NULL, NULL)", (card, ANN))
            except Exception as e:  # noqa: BLE001
                err.append(e)

        t = threading.Thread(target=other)
        t.start()
        assert ready.wait(5)
        assert _waiting(book, b.connection_id)
        _run(a, "COMMIT")
        _run(a, "SET @mill_req_tx = NULL")
        t.join(20)
        assert not err, err
        book.commit()
        assert [r["act"] for r in _moves(book, "todo", card)] == ["create", "assign", "unclaim"]
        assert _fold_card(_moves(book, "todo", card)) == _card_now(book, card) == ("open", None)
    finally:
        try:
            a.rollback()
        except Exception:
            pass
        a.close()
        b.close()


def _pair(book, first, second, rounds: int = 6) -> list:
    errs = []
    for i in range(rounds):
        a, b = _second(book), _second(book)
        try:
            bar = threading.Barrier(2)

            def go(cn, fn):
                try:
                    bar.wait(5)
                    fn(cn, i)
                    cn.commit()
                except mysql.connector.Error as e:
                    if e.errno == 1213:
                        errs.append(e)
                    cn.rollback()

            ts = [threading.Thread(target=go, args=(a, first)), threading.Thread(target=go, args=(b, second))]
            for t in ts:
                t.start()
            for t in ts:
                t.join(30)
        finally:
            a.close()
            b.close()
    return errs


def test_retire_and_hold_take_never_deadlock(book):
    desks = [f"mv080-dl{i}" for i in range(6)]
    for d in desks:
        _seat(book, d)
        rec_hold.upsert(book, ROSTER, d, d + "-old")
        book.commit()

    def retire(cn, i):
        rec_name.retire(cn, desks[i], "desk", by=ADMIN)

    def take(cn, i):
        rec_hold.upsert(cn, ROSTER, desks[i], desks[i] + "-new")

    assert _pair(book, retire, take) == []


def test_card_pass_and_doing_finish_never_deadlock(book):
    cards = []
    for i in range(6):
        c = _card(book, f"mv-dl-{i}")
        _claim(book, BOB, c)
        rec_doing.put(book, BOB, "shipping", "todo", c)
        book.commit()
        cards.append(c)

    def ship(cn, i):
        call(cn, "cmd_pass", [_id(cn, BOB), cards[i], "ship", "sha dl"])

    def finish(cn, i):
        rec_doing.finish(cn, BOB, "todo", cards[i])
        rec_doing.put(cn, BOB, "next", "todo", cards[i])

    assert _pair(book, ship, finish) == []


# ---------- F186 Auditor guards ----------

def test_unpark_of_a_claimed_card_is_refused(book):
    card = _card(book, "mv-unpark-bad")
    _claim(book, BOB, card)
    with pytest.raises(mysql.connector.Error) as ei:
        call(book, "mill_todo_update", [card, ANN, "open", None, None])
        book.commit()
    book.rollback()
    assert "unpark_status" in str(ei.value)
    assert _card_now(book, card) == ("claimed", _id(book, BOB))


def test_assign_under_the_lock_refuses_a_claimed_card(book):
    card = _card(book, "mv-assign-bad")
    _claim(book, BOB, card)
    # Actor is Admin, assignee is ANN: volunteer <> actor, so this is assign; BOB still holds it.
    with pytest.raises(mysql.connector.Error) as ei:
        call(book, "mill_todo_update", [card, ADMIN, "claimed", ANN, None])
        book.commit()
    book.rollback()
    assert "assign_guard" in str(ei.value)
    assert _card_now(book, card) == ("claimed", _id(book, BOB))


def test_a_deleted_card_refuses_a_move(book):
    card = _card(book, "mv-del")
    rec_todo.retire(book, card, ANN)
    book.commit()
    with pytest.raises(mysql.connector.Error) as ei:
        _claim(book, BOB, card)
    book.rollback()
    assert "deleted" in str(ei.value).lower() or "card:deleted" in str(ei.value)


def test_retired_desk_cannot_take_a_hold_or_write_focus(book):
    desk = "mv080-ret"
    digest = _seat(book, desk)
    rec_name.retire(book, desk, "desk", by=ADMIN)
    book.commit()
    with pytest.raises(mysql.connector.Error):
        rec_hold.upsert(book, ROSTER, desk, "mv080-ret-res")
        book.commit()
    book.rollback()
    with pytest.raises(mysql.connector.Error):
        rec_doing.put(book, desk, "after retire", "todo", _card(book, "mv-ret-card"))
        book.commit()
    book.rollback()


def test_open_to_shipped_with_volunteer_is_act_ship(book):
    # Today's direct ship from open on a claimed card stays (the owner); act is ship.
    card = _card(book, "mv-open-ship")
    _claim(book, BOB, card)
    # Leave it claimed (open+volunteer path in cmd_pass allows open with volunteer too)
    _pass(book, BOB, card, "ship", "sha os")
    acts = [r["act"] for r in _moves(book, "todo", card)]
    assert acts == ["create", "claim", "ship"]


def test_noop_reclaim_writes_no_row(book):
    card = _card(book, "mv-noop")
    _claim(book, BOB, card)
    before = _moves(book, "todo", card)
    # Same volunteer again through mill_todo_write: no move.
    call(book, "mill_todo_update", [card, BOB, "claimed", BOB, None])
    book.commit()
    assert _moves(book, "todo", card) == before
