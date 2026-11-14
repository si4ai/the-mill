"""Card 1207: apply_1207 on an existing (pre-1207) book, the cases Validator's pre-fold measure found
(take-over, a DST-split book, a tree node on a name row, the connect anchor, a compressed hold) plus the
evidence and tw card steps, each on its own rows of one fresh book reshaped to the old doing columns before
every test.

Times: doing.created is the book clock (the session zone); transition.at is UTC.
"""
from __future__ import annotations

import uuid
from datetime import datetime

import pytest

pytestmark = [pytest.mark.sql, pytest.mark.fresh_schema]

_OLD_COLS = (
    ("on_type", "VARCHAR(8) NULL"), ("on_id", "BIGINT UNSIGNED NULL"),
    ("act", "VARCHAR(16) NOT NULL DEFAULT 'task'"), ("peer_id", "BIGINT UNSIGNED NULL"),
    ("evidence", "VARCHAR(2000) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL"),
    ("waiting_type", "VARCHAR(8) NULL"), ("waiting_id", "BIGINT UNSIGNED NULL"), ("waiting_why", "VARCHAR(255) NULL"),
)
_ZONE = "Mill/T1207"


@pytest.fixture(scope="module")
def book():
    try:
        from tests.beta_book import drop_db, make_fresh_book

        cn, db = make_fresh_book("mill_m1207up")
    except Exception as exc:  # no MySQL here
        pytest.skip(f"no MySQL for the 1207 upgrade tests: {exc}")
    yield cn
    drop_db(cn, db)


@pytest.fixture()
def cn(book):
    """The book with the pre-1207 doing columns back (apply_1207 dropped them last time), on UTC."""
    cur = book.cursor()
    cur.execute("SET time_zone = '+00:00'")
    for col, ddl in _OLD_COLS:
        cur.execute("SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE()"
                    " AND TABLE_NAME = 'doing' AND COLUMN_NAME = %s", (col,))
        if not cur.fetchone()[0]:
            cur.execute(f"ALTER TABLE doing ADD COLUMN {col} {ddl}")
    cur.close()
    book.commit()
    yield book
    book.cursor().execute("SET time_zone = '+00:00'")


def _q(cn, sql, args=()):
    cur = cn.cursor()
    cur.execute(sql, args)
    rows = cur.fetchall()
    cur.close()
    return rows


def _x(cn, sql, args=()) -> int:
    cur = cn.cursor()
    cur.execute(sql, args)
    last = cur.lastrowid
    cur.close()
    return int(last or 0)


def _desk(cn, tag: str) -> int:
    did = _x(cn, "INSERT INTO name (type, name) VALUES ('desk', %s)", (f"u1207-{tag}-{uuid.uuid4().hex[:6]}",))
    _x(cn, "INSERT INTO seat (desk_id) VALUES (%s)", (did,))
    return did


def _card(cn, desk: int, status: str = "claimed", meta: str | None = None) -> int:
    tid = _x(cn, "INSERT INTO todo (updated_id, roster_id, creator_id, status, assigned_id, body, meta)"
                 " VALUES (%s, 1, %s, %s, %s, 'c', %s)",
             (desk, desk, status, desk if status == "claimed" else None, meta))
    _x(cn, "INSERT INTO activity (type, id, desk_id, roster_id, act) VALUES ('todo', %s, %s, 1, 'create')", (tid, desk))
    return tid


def _move(cn, desk: int, card: int, act: str, created: str, *, peer: int | None = None, ev: str | None = None,
          on_type: str = "todo", text: str = "") -> int:
    return _x(cn, "INSERT INTO doing (created, desk_id, roster_id, text, on_type, on_id, act, peer_id, evidence)"
                  " VALUES (%s, %s, 1, %s, %s, %s, %s, %s, %s)",
              (created, desk, text, on_type, card, act, peer, ev))


def _tr(cn, atype: str, aid: int, frm: str, to: str, reason: str, desk: int, at: str, meta: str | None = None):
    _x(cn, "INSERT INTO transition (at, activity_type, activity_id, from_state, to_state, reason, desk_id, meta)"
           " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)", (at, atype, aid, frm, to, reason, desk, meta))


def _trail(cn, card: int) -> list[tuple]:
    return [(str(r[0]), str(r[1]), str(r[2]), int(r[3]), r[4]) for r in _q(
        cn, "SELECT from_state, to_state, reason, desk_id, at FROM transition"
            " WHERE activity_type = 'todo' AND activity_id = %s ORDER BY at, id", (card,))]


def _apply(cn) -> dict:
    from agent_coord.install.migrate import apply_1207

    rep: dict = {}
    apply_1207(cn, rep)
    return rep


def _at(s: str) -> datetime:
    return datetime.fromisoformat(s)


# take-over ----------------------------------------------------------------------------------------------------

def test_a_take_over_is_one_take_over_and_no_second_claim(cn):
    a, b = _desk(cn, "a"), _desk(cn, "b")
    covered = _card(cn, b)
    _move(cn, a, covered, "claim", "2026-09-01 10:00:00")
    _tr(cn, "todo", covered, "open", "claimed", "claim", a, "2026-09-01 10:00:01")
    _move(cn, b, covered, "claim", "2026-09-01 11:00:00", peer=a)
    _tr(cn, "todo", covered, "claimed", "claimed", "take_over", b, "2026-09-01 11:00:02")
    bare = _card(cn, b)  # no transition rows at all: both moves are backfilled
    _move(cn, a, bare, "claim", "2026-09-02 10:00:00")
    _move(cn, b, bare, "claim", "2026-09-02 11:00:00", peer=a)
    self_peer = _card(cn, a)  # migrate_080 wrote the claimer itself as the peer: a plain claim
    _move(cn, a, self_peer, "claim", "2026-09-03 10:00:00", peer=a)
    cn.commit()
    _apply(cn)
    assert [r[:4] for r in _trail(cn, covered)] == [("open", "claimed", "claim", a),
                                                    ("claimed", "claimed", "take_over", b)]
    assert [r[:4] for r in _trail(cn, bare)] == [("open", "claimed", "claim", a),
                                                 ("claimed", "claimed", "take_over", b)]
    assert [r[:4] for r in _trail(cn, self_peer)] == [("open", "claimed", "claim", a)]


# DST ----------------------------------------------------------------------------------------------------------

def _dst_zone(cn) -> str:
    """A named zone with Pacific rules: the server's own tables (the mysql:8.4 image loads them), else a minimal
    zone written for this test (PDT until 2026-11-01 09:00 UTC, PST after). Skips when neither is possible."""
    def ok(z: str) -> bool:
        r = _q(cn, "SELECT CONVERT_TZ('2026-10-15 10:00:00', %s, '+00:00'),"
                   " CONVERT_TZ('2026-12-01 10:00:00', %s, '+00:00')", (z, z))[0]
        return r == (_at("2026-10-15 17:00:00"), _at("2026-12-01 18:00:00"))

    if ok("America/Los_Angeles"):
        return "America/Los_Angeles"
    try:
        if not _q(cn, "SELECT 1 FROM mysql.time_zone_name WHERE Name = %s", (_ZONE,)):
            zid = _x(cn, "INSERT INTO mysql.time_zone (Use_leap_seconds) VALUES ('N')")
            _x(cn, "INSERT INTO mysql.time_zone_name (Name, Time_zone_id) VALUES (%s, %s)", (_ZONE, zid))
            _x(cn, "INSERT INTO mysql.time_zone_transition_type (Time_zone_id, Transition_type_id, Offset, Is_DST,"
                   " Abbreviation) VALUES (%s, 0, -28800, 0, 'PST'), (%s, 1, -25200, 1, 'PDT')", (zid, zid))
            _x(cn, "INSERT INTO mysql.time_zone_transition (Time_zone_id, Transition_time, Transition_type_id)"
                   " VALUES (%s, 1772964000, 1), (%s, 1793523600, 0)", (zid, zid))
            cn.commit()
    except Exception as exc:
        pytest.skip(f"no named DST zone on this MySQL and none can be written: {exc}")
    if not ok(_ZONE):
        pytest.skip("no named DST zone on this MySQL")
    return _ZONE


def test_a_dst_split_book_is_converted_per_row(cn):
    zone = _dst_zone(cn)
    d = _desk(cn, "dst")
    oct_card, dec_card, gap = _card(cn, d), _card(cn, d), _card(cn, d)
    # Book clock rows from both halves of the year, each with its transition at the true UTC time.
    _move(cn, d, oct_card, "claim", "2026-10-15 10:00:00")
    _tr(cn, "todo", oct_card, "open", "claimed", "claim", d, "2026-10-15 17:00:01")
    _move(cn, d, dec_card, "claim", "2026-12-01 10:00:00")
    _tr(cn, "todo", dec_card, "open", "claimed", "claim", d, "2026-12-01 18:00:01")
    _move(cn, d, gap, "claim", "2026-10-20 09:30:00")  # no transition: backfilled at its own UTC
    task = _x(cn, "INSERT INTO doing (created, desk_id, roster_id, text, act) VALUES ('2026-10-16 08:00:00', %s, 1,"
                  " '', 'task')", (d,))
    _x(cn, "INSERT INTO activity (type, id, desk_id, roster_id, act) VALUES ('doing', %s, %s, 1, 'task')", (task, d))
    cn.commit()
    cn.cursor().execute("SET time_zone = %s", (zone,))
    _apply(cn)
    assert [r[4] for r in _trail(cn, oct_card)] == [_at("2026-10-15 17:00:01")]
    assert [r[4] for r in _trail(cn, dec_card)] == [_at("2026-12-01 18:00:01")]
    assert [r[4] for r in _trail(cn, gap)] == [_at("2026-10-20 16:30:00")]
    # The live doings reader converts per row too: a PDT run read in PST is still its true UTC time.
    from agent_coord.server.records.doing import live_doings

    desk = _q(cn, "SELECT name FROM name WHERE id = %s", (d,))[0][0]
    got = live_doings(cn, [desk])[desk]
    assert [(x["id"], x["created"]) for x in got["doings"]] == [(task, "2026-10-16T15:00:00Z")]


def test_a_zone_that_cannot_convert_stops_before_any_change(cn, monkeypatch):
    from agent_coord.install import migrate
    from agent_coord.server.connect_activity import anchor_id

    d = _desk(cn, "tz")
    c = _card(cn, d)
    _move(cn, d, c, "claim", "2026-10-15 10:00:00")
    # Early-step rows: a name-delete transition, a connect row on activity('doing', desk_id),
    # and the rename edge removed so a premature insert would show.
    named = _x(cn, "INSERT INTO doing (created, desk_id, roster_id, text, act) VALUES"
                   " ('2026-10-15 09:00:00', %s, 1, 'roster:tmp', 'delete')", (d,))
    _x(cn, "INSERT INTO activity (type, id, desk_id, roster_id, act) VALUES ('doing', %s, %s, 1, 'delete')",
       (named, d))
    _tr(cn, "doing", named, "any", "cleared", "name_delete", d, "2026-10-15 09:00:01")
    _x(cn, "INSERT INTO activity (type, id, desk_id, roster_id, act) VALUES ('doing', %s, %s, 1, 'focus')", (d, d))
    _tr(cn, "doing", d, "seated", "connected", "connect", d, "2026-10-15 08:00:00")
    _x(cn, "UPDATE transition SET join_key = %s WHERE activity_id = %s AND reason = 'connect'",
       (f"connect:{d}:1", d))
    _x(cn, "DELETE FROM transition_edge WHERE activity_type = 'todo' AND from_state = 'any'"
           " AND to_state = 'same' AND reason = 'rename'")
    cn.commit()
    tables = ("doing", "transition", "activity", "tree", "seat", "label", "watcher", "todo", "hold",
              "transition_edge")

    def _sums():
        return {t: _q(cn, f"CHECKSUM TABLE `{t}`")[0][1] for t in tables}

    before = _sums()
    monkeypatch.setattr(migrate, "_BOOK_TO_UTC_1207", "CONVERT_TZ(d.created, 'No/Such_Zone', '+00:00')")
    with pytest.raises(RuntimeError, match="cannot convert"):
        _apply(cn)
    assert _sums() == before
    assert _q(cn, "SELECT act FROM doing WHERE on_id = %s AND on_type = 'todo'", (c,)) == [("claim",)]
    assert _trail(cn, c) == []
    assert _q(cn, "SELECT reason FROM transition WHERE activity_id = %s AND activity_type = 'doing'"
                  " AND reason = 'name_delete'", (named,)) == [("name_delete",)]
    assert _q(cn, "SELECT activity_id FROM transition WHERE join_key = %s", (f"connect:{d}:1",)) == [(d,)]
    assert _q(cn, "SELECT COUNT(*) FROM activity WHERE type = 'doing' AND id = %s", (anchor_id(d),)) == [(0,)]
    assert _q(cn, "SELECT COUNT(*) FROM transition_edge WHERE activity_type = 'todo' AND from_state = 'any'"
                  " AND to_state = 'same' AND reason = 'rename'") == [(0,)]
    monkeypatch.undo()
    _apply(cn)  # leave the book upgraded for the next test
    assert len(_trail(cn, c)) == 1


# tree node on a name row ---------------------------------------------------------------------------------------

def test_a_tree_node_on_a_name_row_keeps_its_node_and_the_upgrade_runs(cn):
    d = _desk(cn, "tree")
    plan = _x(cn, "INSERT INTO name (type, name) VALUES ('tree', %s)", (f"u1207-plan-{uuid.uuid4().hex[:6]}",))
    named = _move(cn, d, None, "delete", "2026-09-05 10:00:00", on_type=None, text="roster:gone")
    bare = _move(cn, d, None, "purge", "2026-09-05 10:01:00", on_type=None, text="roster:gone")
    for i in (named, bare):
        _x(cn, "INSERT INTO activity (type, id, desk_id, roster_id, act) VALUES ('doing', %s, %s, 1, 'delete')", (i, d))
    _x(cn, "INSERT INTO tree (name_id, type, id, lft, rgt) VALUES (%s, 'doing', %s, 1, 2)", (plan, named))
    cn.commit()
    rep = _apply(cn)
    assert rep["kept_for_tree"] == 1
    # The node, its activity row and its doing row stay; the row is ended, so it is never a live doing.
    assert _q(cn, "SELECT COUNT(*) FROM tree WHERE type = 'doing' AND id = %s", (named,)) == [(1,)]
    assert _q(cn, "SELECT type, id FROM activity WHERE type = 'doing' AND id IN (%s, %s)", (named, bare)) == [
        ("doing", named)]
    assert _q(cn, "SELECT id FROM doing WHERE id IN (%s, %s)", (named, bare)) == [(named,)]
    assert _q(cn, "SELECT to_state, reason, JSON_UNQUOTE(JSON_EXTRACT(meta, '$.cause')) FROM transition"
                  " WHERE activity_type = 'doing' AND activity_id = %s", (named,)) == [("cleared", "clear", "migrate_1207")]
    from agent_coord.server.records.doing import live_doings

    desk = _q(cn, "SELECT name FROM name WHERE id = %s", (d,))[0][0]
    assert live_doings(cn, [desk])[desk] == {"n": 0, "doings": []}
    _apply(cn)  # a rerun adds no second row
    assert _q(cn, "SELECT COUNT(*) FROM transition WHERE activity_type = 'doing' AND activity_id = %s", (named,)) == [(1,)]


# connect anchor -----------------------------------------------------------------------------------------------

def test_connect_rows_leave_a_tw_run_that_shares_the_desk_id(cn):
    from agent_coord.server.connect_activity import anchor_id
    from agent_coord.server.records.doing import live_doings

    sat, runner = _desk(cn, "sat"), _desk(cn, "run")
    # A tw run whose doing id equals the other desk's id, and that desk's old connect rows on the same id.
    _x(cn, "INSERT INTO doing (id, created, desk_id, roster_id, text, act) VALUES (%s, UTC_TIMESTAMP(6), %s, 1,"
           " '', 'task')", (sat, runner))
    _x(cn, "INSERT INTO activity (type, id, desk_id, roster_id, act) VALUES ('doing', %s, %s, 1, 'task')",
       (sat, runner))
    _tr(cn, "doing", sat, "seated", "connected", "connect", sat, "2026-11-01 10:00:00")
    _x(cn, "UPDATE transition SET join_key = %s WHERE activity_id = %s AND reason = 'connect'", (f"connect:{sat}:1", sat))
    _tr(cn, "doing", sat, "none", "active", "tw_start", runner, "2026-11-02 10:00:00")
    _tr(cn, "doing", sat, "connected", "seated", "disconnect", sat, "2026-11-03 10:00:00")
    _x(cn, "UPDATE transition SET join_key = %s WHERE activity_id = %s AND reason = 'disconnect'",
       (f"connect:{sat}:1", sat))
    cn.commit()
    rep = _apply(cn)
    assert rep["connect_rows_moved"] == 2
    assert _q(cn, "SELECT reason FROM transition WHERE activity_type = 'doing' AND activity_id = %s", (sat,)) == [
        ("tw_start",)]
    assert _q(cn, "SELECT reason FROM transition WHERE activity_type = 'doing' AND activity_id = %s ORDER BY id",
              (anchor_id(sat),)) == [("connect",), ("disconnect",)]
    assert _q(cn, "SELECT desk_id FROM activity WHERE type = 'doing' AND id = %s",
              (anchor_id(sat),)) == [(sat,)]
    name = _q(cn, "SELECT name FROM name WHERE id = %s", (runner,))[0][0]
    assert [x["state"] for x in live_doings(cn, [name])[name]["doings"]] == ["active"]
    assert _apply(cn).get("connect_rows_moved") == 0  # a rerun moves nothing


# compressed hold (MU15) ---------------------------------------------------------------------------------------

def test_a_compressed_hold_row_covers_the_hold_move(cn):
    """A hold move whose item already has a compressed transition (n>1, n<=100) is covered, not backfilled.

    The compressed row is more than 5 seconds after the move, so the time-window
    clause does not cover it; only the n>1 clause does (MU15 mutates n>1 to n>100).
    """
    d = _desk(cn, "hld")
    res = _x(cn, "INSERT INTO name (type, name) VALUES ('res', %s)", (f"u1207-res-{uuid.uuid4().hex[:6]}",))
    hid = _x(cn, "INSERT INTO hold (desk_id, resource_id) VALUES (%s, %s)", (d, res))
    _x(cn, "INSERT INTO activity (type, id, desk_id, roster_id, act) VALUES ('hold', %s, %s, 1, 'hold')", (hid, d))
    _move(cn, d, hid, "hold", "2026-09-20 10:00:00", on_type="hold")
    _x(cn, "INSERT INTO transition (at, activity_type, activity_id, from_state, to_state, reason, desk_id, n)"
           " VALUES ('2026-09-20 10:10:00', 'hold', %s, 'free', 'held', 'hold_grant', %s, 2)", (hid, d))
    cn.commit()
    _apply(cn)
    assert _q(cn, "SELECT from_state, to_state, reason, n, desk_id FROM transition"
                  " WHERE activity_type = 'hold' AND activity_id = %s ORDER BY id", (hid,)) == [
        ("free", "held", "hold_grant", 2, d)]


# evidence and the tw card -------------------------------------------------------------------------------------

def test_evidence_is_the_newest_byte_for_byte_and_meta_keys_stay(cn):
    import json

    d = _desk(cn, "ev")
    newest = _card(cn, d, "done", meta=json.dumps({"slug": "s1207", "eta_at": "2026-12-01"}))
    long_ev = ("evidence \u00e9\u4e2d " * 200)[:1800]
    _move(cn, d, newest, "ship", "2026-09-10 10:00:00", ev="older ship")
    _move(cn, d, newest, "done", "2026-09-11 10:00:00", ev=long_ev)
    preset = _card(cn, d, "shipped", meta=json.dumps({"evidence": "already in meta"}))
    _move(cn, d, preset, "ship", "2026-09-12 10:00:00", ev="from the doing row")
    cn.commit()
    _apply(cn)
    meta = json.loads(_q(cn, "SELECT meta FROM todo WHERE id = %s", (newest,))[0][0])
    assert meta == {"slug": "s1207", "eta_at": "2026-12-01", "evidence": long_ev}
    assert json.loads(_q(cn, "SELECT meta FROM todo WHERE id = %s", (preset,))[0][0]) == {"evidence": "already in meta"}


def test_a_tw_runs_card_goes_to_its_tw_start_meta(cn):
    import json

    d = _desk(cn, "twc")
    card = _card(cn, d)
    run = _move(cn, d, card, "task", "2026-11-10 10:00:00")
    _x(cn, "INSERT INTO activity (type, id, desk_id, roster_id, act) VALUES ('doing', %s, %s, 1, 'task')", (run, d))
    _tr(cn, "doing", run, "none", "active", "tw_start", d, "2026-11-10 10:00:00")
    cn.commit()
    _apply(cn)
    meta = _q(cn, "SELECT meta FROM transition WHERE activity_type = 'doing' AND activity_id = %s", (run,))[0][0]
    assert json.loads(meta) == {"card": card}
    assert _q(cn, "SELECT COUNT(*) FROM doing WHERE id = %s", (run,)) == [(1,)]


# assign: the assignee rode on doing.peer_id (Validator W1, letter 6278) ----------------------------------------

def _assign_meta(cn, card: int) -> list:
    import json

    return [json.loads(r[0]) if r[0] is not None else None for r in _q(
        cn, "SELECT meta FROM transition WHERE activity_type = 'todo' AND activity_id = %s AND reason = 'assign'"
            " ORDER BY id", (card,))]


def test_an_uncovered_assign_gets_the_assignee_in_meta_to(cn):
    a, b = _desk(cn, "asg"), _desk(cn, "asgee")
    card = _card(cn, b)
    row = _move(cn, a, card, "assign", "2026-09-05 10:00:00", peer=b)
    cn.commit()
    _apply(cn)
    meta = _assign_meta(cn, card)
    assert meta == [{"to": b}]
    assert isinstance(meta[0]["to"], int)
    assert _q(cn, "SELECT COUNT(*) FROM doing WHERE id = %s", (row,)) == [(0,)]


def test_a_covered_assign_keeps_its_meta_and_gains_to(cn):
    a, b = _desk(cn, "asgc"), _desk(cn, "asgcee")
    card = _card(cn, b)
    row = _move(cn, a, card, "assign", "2026-09-06 10:00:00", peer=b)
    _tr(cn, "todo", card, "open", "claimed", "assign", a, "2026-09-06 10:00:01", meta='{"fx": 1}')
    plain = _card(cn, b)
    _move(cn, a, plain, "assign", "2026-09-07 10:00:00", peer=b)
    _tr(cn, "todo", plain, "open", "claimed", "assign", a, "2026-09-07 10:00:01")
    cn.commit()
    rep = _apply(cn)
    assert rep["moves_covered"] >= 2
    assert _assign_meta(cn, card) == [{"fx": 1, "to": b}]
    assert _assign_meta(cn, plain) == [{"to": b}]
    assert _q(cn, "SELECT COUNT(*) FROM doing WHERE id = %s", (row,)) == [(0,)]


def test_a_missing_or_zero_peer_invents_no_to(cn):
    a = _desk(cn, "asgn")
    unc_null, unc_zero, cov_null = _card(cn, a), _card(cn, a), _card(cn, a)
    _move(cn, a, unc_null, "assign", "2026-09-08 10:00:00")
    _move(cn, a, unc_zero, "assign", "2026-09-08 11:00:00", peer=0)
    _move(cn, a, cov_null, "assign", "2026-09-08 12:00:00")
    _tr(cn, "todo", cov_null, "open", "claimed", "assign", a, "2026-09-08 12:00:01")
    cn.commit()
    _apply(cn)
    for card in (unc_null, unc_zero, cov_null):
        metas = _assign_meta(cn, card)
        assert len(metas) == 1 and "to" not in (metas[0] or {})


def test_an_existing_meta_to_is_not_overwritten(cn):
    a, b, c = _desk(cn, "asgo"), _desk(cn, "asgo2"), _desk(cn, "asgo3")
    card = _card(cn, b)
    _move(cn, a, card, "assign", "2026-09-09 10:00:00", peer=c)
    _tr(cn, "todo", card, "open", "claimed", "assign", a, "2026-09-09 10:00:01", meta='{"to": %d}' % b)
    cn.commit()
    _apply(cn)
    assert _assign_meta(cn, card) == [{"to": b}]


def test_a_rerun_on_a_migrated_book_is_a_no_op(cn):
    a, b = _desk(cn, "asgr"), _desk(cn, "asgree")
    card = _card(cn, b)
    _move(cn, a, card, "assign", "2026-09-10 10:00:00", peer=b)
    cn.commit()
    _apply(cn)
    _apply(cn)
    assert _assign_meta(cn, card) == [{"to": b}]
