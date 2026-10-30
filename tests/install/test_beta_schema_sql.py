"""Beta book (roster = room) on a real MySQL: the schema, its routines, the installer, migration and rollback. Row F143.

The book enforces what 0.7 enforced in rpc.py: who may move a card, Office membership, one room per letter, a span
that says when it was cut, a 7-day wake queue, votes that close and hand a tie to the human, and an app user that
can only EXECUTE the public routines.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets

import pytest

from agent_coord.install import beta_migrate as bm
from agent_coord.install import migrate as m07
from tests.sql_isolate import throwaway_db

pytestmark = pytest.mark.sql


def _admin():
    import mysql.connector

    from agent_coord.server.records.db import conn_kwargs

    kw = conn_kwargs()
    kw.pop("database", None)
    kw["autocommit"] = True
    return mysql.connector.connect(**kw), kw


class Book:
    def __init__(self, cn, db):
        self.cn, self.db = cn, db
        self.cur = cn.cursor(buffered=True)

    def call(self, name, *args):
        self.cur.execute("CALL " + name + "(" + ", ".join(["%s"] * len(args)) + ")", args)
        sets = []
        while True:
            if self.cur.with_rows:
                sets.append([dict(zip(self.cur.column_names, r)) for r in self.cur.fetchall()])
            if not self.cur.nextset():
                break
        return sets

    def one(self, name, *args):
        return self.call(name, *args)[0][0]

    def q(self, sql, args=()):
        self.cur.execute(sql, args)
        return self.cur.fetchall() if self.cur.with_rows else None

    def refused(self, text, name, *args):
        import mysql.connector

        with pytest.raises(mysql.connector.Error) as exc:
            self.call(name, *args)
        assert text in str(exc.value), str(exc.value)

    def desk(self, name):
        return self.one("cmd_desk_create", name, hashlib.sha256(name.encode()).hexdigest())["desk"]


@pytest.fixture(scope="module")
def bk():
    try:
        cn, _ = _admin()
    except Exception as e:  # pragma: no cover - no server
        pytest.skip(f"mysql: {e}")
    db = throwaway_db("mill_beta")
    cur = cn.cursor()
    cur.execute("DROP DATABASE IF EXISTS " + db)
    cur.execute("CREATE DATABASE " + db)
    cur.execute("USE " + db)
    cur.close()
    bm.install(cn)
    b = Book(cn, db)
    yield b
    b.q("DROP DATABASE IF EXISTS " + db)
    cn.close()


def test_stamp_and_hello(bk):
    assert bk.q("SELECT mill_sp_version()")[0][0] == bm.sp_version()
    assert bk.q("SELECT version FROM sp_deploy ORDER BY id DESC LIMIT 1")[0][0] == bm.sp_version()
    assert bk.one("mill_hello", bm.sp_version(), "refuse")["status"] == "ok"
    assert bk.one("mill_hello", "sp-000000000000", "warn")["status"].startswith("warn:")
    bk.refused("sp version mismatch", "mill_hello", "sp-000000000000", "refuse")


def test_office_is_a_roster_every_desk_is_on(bk):
    a, b = bk.desk("f143-a"), bk.desk("f143-b")
    assert bk.q("SELECT kind, name FROM room WHERE id = 1")[0] == ("roster", "Office")
    assert bk.q("SELECT COUNT(*) FROM room_member WHERE room_id = 1 AND desk_id IN (%s, %s) AND left_at IS NULL", (a, b))[0][0] == 2
    bk.refused("Office", "cmd_member", a, 1, a, 0)
    with pytest.raises(Exception):
        bk.q("UPDATE room SET kind = 'room' WHERE id = 1")
    # Admin is a role, not a room; no lead role exists
    assert bk.q("SELECT id, name FROM role")[0] == (2, "Admin")
    assert bk.q("SELECT COUNT(*) FROM role")[0][0] == 1


def test_roster_is_its_room_and_a_desk_is_on_many(bk):
    a, b, c = bk.desk("f143-ra"), bk.desk("f143-rb"), bk.desk("f143-rc")
    r1 = bk.one("cmd_roster_create", a, "f143-r1", json.dumps([b]))["roster"]
    r2 = bk.one("cmd_roster_create", a, "f143-r2", json.dumps([b]))["roster"]
    assert {r for (r,) in bk.q("SELECT room_id FROM room_member WHERE desk_id = %s AND left_at IS NULL", (b,))} >= {1, r1, r2}
    sent = bk.one("cmd_send", a, r1, None, "to the roster", 0)
    assert sent["recipients"] == 1
    bk.refused("not a current member", "cmd_send", c, r1, None, "not a member", 0)
    room = bk.one("cmd_room_create", a, "f143-talk", r1, json.dumps([b]))["room"]
    assert bk.q("SELECT kind, roster_id FROM room WHERE id = %s", (room,))[0] == ("room", r1)
    reply = bk.one("cmd_reply", b, sent["letter"], "back", None)
    assert bk.q("SELECT room_id, reply_to_id FROM letter WHERE id = %s", (reply["letter"],))[0] == (r1, sent["letter"])
    with pytest.raises(Exception):  # a reply never changes room or parent
        bk.q("UPDATE letter SET room_id = 1 WHERE id = %s", (reply["letter"],))


def test_card_guards_done_when_and_evidence(bk):
    asker, vol, other = bk.desk("f143-ask"), bk.desk("f143-vol"), bk.desk("f143-oth")
    c = bk.one("cmd_card", asker, 1, "a card", "tests green", None, None, None, 0)
    assert c["status"] == "open"
    bk.refused("who-may", "cmd_card_accept", other, c["card"], "x")
    bk.one("cmd_claim", vol, c["card"])
    bk.refused("", "cmd_claim", other, c["card"])
    bk.refused("who-may", "cmd_pass", other, c["card"], "ship", None)
    assert bk.one("cmd_pass", vol, c["card"], "ship", "ci run 1 green")["status"] == "shipped"
    bk.refused("who-may", "cmd_pass", vol, c["card"], "done", None)
    assert bk.one("cmd_pass", asker, c["card"], "done", None)["status"] == "done"
    ev = bk.q("SELECT to_status, evidence FROM card_event WHERE card_id = %s ORDER BY id", (c["card"],))
    assert ("shipped", "ci run 1 green") in ev
    card = bk.call("uc_card", c["card"])[0][0]
    assert card["done_when"] == "tests green" and card["status"] == "done"
    p = bk.one("cmd_card", asker, 1, "parked one", None, None, None, None, 1)
    assert p["status"] == "parked"
    assert bk.one("cmd_park", asker, p["card"], 0)["status"] == "open"


def _order(bk, parent):
    return [r[0] for r in bk.q("SELECT id FROM card WHERE from_card_id = %s ORDER BY ord, id", (parent,))]


def test_move_keeps_order_and_renumbers_only_when_a_gap_runs_out(bk):
    d = bk.desk("f143-mv")
    root = bk.one("cmd_card", d, 1, "plan", None, None, None, None, 0)["card"]
    kids = [bk.one("cmd_card", d, 1, f"step {i}", None, None, root, None, 0)["card"] for i in range(5)]
    assert _order(bk, root) == kids
    renumbered = 0
    want = list(kids)
    for i in range(45):  # front-insert after the first: halves one gap each time until it runs out
        mover = want[-1]
        r = bk.one("cmd_move", d, mover, root, want[0])
        renumbered += int(r["renumbered"])
        want = [want[0], mover] + [k for k in want[1:] if k != mover]
        assert _order(bk, root) == want
    assert renumbered > 0
    bk.one("cmd_move", d, want[2], root, 0)
    assert _order(bk, root)[0] == want[2]
    bk.refused("cycle", "cmd_move", d, root, kids[0], None)
    assert bk.one("cmd_move", d, kids[1], None, None)["parent"] is None
    assert kids[1] not in _order(bk, root)
    outsider = bk.desk("f143-mv-out")
    r = bk.one("cmd_roster_create", d, "f143-mv-r", json.dumps([]))["roster"]
    other = bk.one("cmd_card", d, r, "roster card", None, None, None, None, 0)["card"]
    bk.refused("who-may", "cmd_move", outsider, other, None, None)


def test_vote_closes_on_majority_tie_and_no_quorum(bk):
    a, b, c = bk.desk("f143-va"), bk.desk("f143-vb"), bk.desk("f143-vc")
    r = bk.one("cmd_roster_create", a, "f143-vote", json.dumps([b, c]))["roster"]
    v = bk.one("cmd_vote_open", a, r, "ship today?", "yes_no", 60)
    for who in (a, b, c):
        last = bk.one("cmd_vote_cast", who, v["vote"], "yes" if who != c else "no")
    assert last["outcome"] == "yes"  # everyone voted: closed early, 2-1
    bk.refused("closed", "cmd_vote_cast", a, v["vote"], "no")
    bk.refused("", "cmd_vote_cast", a, bk.one("cmd_vote_open", a, r, "keep?", "keep_drop", 60)["vote"], "yes")
    t = bk.one("cmd_vote_open", a, r, "tie?", "keep_drop", 60)["vote"]
    bk.one("cmd_vote_cast", a, t, "keep")
    bk.one("cmd_vote_cast", b, t, "drop")
    bk.q("UPDATE vote SET opened_at = NOW(6) - INTERVAL 2 HOUR, deadline = NOW(6) - INTERVAL 1 SECOND WHERE id = %s", (t,))
    bk.call("sp_vote_close_due")
    row = bk.call("uc_vote", t)[0][0]
    assert (row["outcome"], row["needs_human"]) == ("tie", 1)
    n = bk.one("cmd_vote_open", a, r, "anyone?", "yes_no", 60)["vote"]
    bk.refused("member", "cmd_vote_cast", bk.desk("f143-vx"), n, "yes")
    bk.q("UPDATE vote SET opened_at = NOW(6) - INTERVAL 2 HOUR, deadline = NOW(6) - INTERVAL 1 SECOND WHERE id = %s", (n,))
    bk.call("sp_vote_close_due")
    row = bk.call("uc_vote", n)
    assert (row[0][0]["outcome"], row[0][0]["needs_human"]) == ("no_quorum", 1)
    assert len(row[2]) == 3  # not voted
    glance = bk.call("uc_glance")
    assert any(g["vote"] == t and g["needs_human"] == 1 for g in glance[2])
    assert glance[0][0]["votes_need_human"] >= 2


def test_span_says_when_it_was_cut(bk):
    d = bk.desk("f143-span")
    root = bk.one("cmd_card", d, 1, "big plan", None, None, None, None, 0)["card"]
    bk.q("SET SESSION cte_max_recursion_depth = 30000")
    bk.q(
        "INSERT INTO card (created, creator_id, roster_id, status, body, from_card_id, ord) "
        "WITH RECURSIVE n (i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < 20100) "
        "SELECT NOW(6), %s, 1, 'open', 'leaf', %s, i * 1048576 FROM n",
        (d, root),
    )
    sets = bk.call("mill_span", "card", root, 5)
    assert sets[-1][0]["truncated"] == 1 and sets[-1][0]["cap"] == 20000
    assert len(sets[0]) == 20000
    small = bk.one("cmd_card", d, 1, "small", None, None, None, None, 0)["card"]
    sets = bk.call("mill_span", "card", small, 5)
    assert sets[-1][0]["truncated"] == 0 and sets[-1][0]["nodes"] == len(sets[0])


def test_push_kept_until_sent_and_purged_after_7_days(bk):
    a, b = bk.desk("f143-pa"), bk.desk("f143-pb")
    bk.call("cmd_connect", b)
    l1 = bk.one("cmd_send", a, 1, json.dumps([b]), "old", 1)["letter"]
    l2 = bk.one("cmd_send", a, 1, json.dumps([b]), "new", 1)["letter"]
    bk.q("UPDATE push SET created = NOW(6) - INTERVAL 8 DAY WHERE letter_id = %s", (l1,))
    bk.call("sp_push_purge")
    sets = bk.call("cmd_connect", b)
    assert [p["letter"] for p in sets[0]] == [l2]
    assert sets[1][0]["expired"] == 1
    bk.one("cmd_push_sent", b, json.dumps([p["push"] for p in sets[0]]))
    assert bk.call("cmd_connect", b)[0] == []


def test_execute_only_grant(bk):
    import mysql.connector

    user = "f143_app_" + secrets.token_hex(3)
    pw = secrets.token_urlsafe(18)
    for host in ("%", "localhost"):
        bk.q("CREATE USER %s@%s IDENTIFIED BY %s", (user, host, pw))
    try:
        assert bm.grant_execute(bk.cn, bk.db, user, "%") > 40
        bm.grant_execute(bk.cn, bk.db, user, "localhost")
        _, kw = _admin()
        kw.update(user=user, password=pw, database=bk.db)
        app = mysql.connector.connect(**kw)
        cur = app.cursor(buffered=True)
        cur.execute("CALL uc_here()")
        while cur.nextset():
            pass
        for stmt in ("SELECT * FROM desk", "INSERT INTO tag (name) VALUES ('x')", "CALL sp_push_purge()", "CALL mill_i_vote_close(1)"):
            with pytest.raises(mysql.connector.Error):
                cur.execute(stmt)
        app.close()
        grants = " ".join(r[0] for r in bk.q("SHOW GRANTS FOR %s@%s", (user, "%")))
        assert "SELECT" not in grants.replace("EXECUTE", "") and "INSERT" not in grants
    finally:
        for host in ("%", "localhost"):
            bk.q("DROP USER IF EXISTS %s@%s", (user, host))


def test_read_committed(bk):
    was = bk.q("SELECT @@GLOBAL.transaction_isolation")[0][0]
    try:
        scope = bm.set_read_committed(bk.cn)
        assert scope in ("persist", "global", "session")
        if scope != "session":
            assert bk.q("SELECT @@GLOBAL.transaction_isolation")[0][0] == "READ-COMMITTED"
    finally:  # the shared test server keeps what the other suites expect
        try:
            bk.q("RESET PERSIST IF EXISTS transaction_isolation")
        except Exception:
            pass
        bk.q("SET GLOBAL transaction_isolation = %s", (was,))


# --- migration and rollback on a small 0.7 book built by this pack's installer -------------------------------------

SEED_07 = """
INSERT INTO name (id, type, name) VALUES (10, 'desk', 'm07-a'), (11, 'desk', 'm07-b'), (12, 'desk', 'm07-c'),
  (20, 'roster', 'm07-r'), (30, 'tree', 'm07-talk'), (31, 'tree', 'm07-plan'), (40, 'label', 'm07-a'), (41, 'label', 'beta'), (50, 'res', 'ci');
INSERT INTO member (name_id, desk_id) VALUES (1, 10), (1, 11), (1, 12), (2, 10), (20, 10), (20, 11);
INSERT INTO activity (type, id, desk_id, roster_id) VALUES ('mail', 1, 10, 20), ('mail', 2, 11, 20), ('mail', 3, 12, 1),
  ('todo', 1, 10, 20), ('todo', 2, 10, 20), ('todo', 3, 10, 20), ('score', 900, 20, 20);
INSERT INTO mail (id, desk_id, body, roster_id) VALUES (1, 10, 'root', 20), (2, 11, 'reply', 20), (3, 12, 'office', 1);
INSERT INTO mail_to (id, desk_id, asked) VALUES (1, 11, 1), (2, 10, 1), (3, 10, 0);
INSERT INTO todo (id, updated_id, roster_id, creator_id, status, assigned_id, claimed_at, body) VALUES
  (1, 10, 20, 10, 'claimed', 11, NOW(6), 'plan'), (2, 10, 20, 10, 'open', NULL, NULL, 'second'), (3, 10, 20, 10, 'open', NULL, NULL, 'first');
INSERT INTO tree (name_id, type, id, lft, rgt) VALUES (30, 'mail', 1, 1, 4), (30, 'mail', 2, 2, 3),
  (31, 'todo', 1, 1, 6), (31, 'todo', 3, 2, 3), (31, 'todo', 2, 4, 5);
INSERT INTO label (type, id, name_id, ord) VALUES ('todo', 2, 40, 1), ('todo', 1, 41, 65535);
INSERT INTO tree_read (desk_id, tree_id, last_id) VALUES (11, 30, 1);
INSERT INTO score (id, desk_id, roster_id, kpi, value, target, note) VALUES (900, 20, 20, 'm07.kpi', '', '3', 'roster-owned');
INSERT INTO push_queue (desk_id, kind, payload, outcome) VALUES (11, 'mail', JSON_OBJECT('id', 1, 'kind', 'mail'), 'missed');
"""


@pytest.fixture(scope="module")
def book07():
    try:
        cn, _ = _admin()
    except Exception as e:  # pragma: no cover
        pytest.skip(f"mysql: {e}")
    src = throwaway_db("mill_b07")
    dbs = [src, src + "_b", src + "_r"]
    cur = cn.cursor()
    for d in dbs:
        cur.execute("DROP DATABASE IF EXISTS " + d)
    cur.execute("CREATE DATABASE " + src)
    cur.execute("USE " + src)
    m07.ensure(cn)
    for stmt in m07.split_script(SEED_07):
        cur.execute(stmt)
    cur.close()
    yield cn, src
    cur = cn.cursor()
    for d in dbs:
        cur.execute("DROP DATABASE IF EXISTS " + d)
    cn.close()


def test_migrate_then_rollback_round_trip(book07):
    cn, src = book07
    out = bm.migrate(cn, src, src + "_b")
    b = Book(cn, src + "_b")
    assert b.q("SELECT kind, roster_id FROM room WHERE id = 30")[0] == ("room", 20)
    assert b.q("SELECT room_id, reply_to_id FROM letter WHERE id = 2")[0] == (30, 1)
    assert b.q("SELECT room_id FROM letter WHERE id = 3")[0][0] == 1
    # the thread's cast are current members, so they can keep replying
    assert {d for (d,) in b.q("SELECT desk_id FROM room_member WHERE room_id = 30 AND left_at IS NULL")} == {10, 11}
    assert b.q("SELECT read_at IS NOT NULL FROM letter_to WHERE letter_id = 1 AND desk_id = 11")[0][0] == 1
    assert [r[0] for r in b.q("SELECT id FROM card WHERE from_card_id = 1 ORDER BY ord")] == [3, 2]
    assert b.q("SELECT status, volunteer_id FROM card WHERE id = 1")[0] == ("claimed", 11)
    assert b.q("SELECT desk_id, roster_id, target FROM score WHERE id = 900")[0] == (None, 20, 3.0)
    assert b.q("SELECT card_id FROM focus WHERE desk_id = 10")[0][0] == 2
    assert b.q("SELECT COUNT(*) FROM card_tag")[0][0] == 1
    assert b.q("SELECT role_id FROM role_member WHERE desk_id = 10")[0][0] == 2
    assert b.q("SELECT COUNT(*) FROM push")[0][0] == 1
    assert out["repairs"].get("unread recipient rows a tree_read cursor had covered (marked read)") == 1
    assert b.q("SELECT mill_sp_version()")[0][0] == bm.sp_version()
    # a new desk and a new roster after cutover do not take an old id
    d = b.desk("m07-new")
    assert d > 50
    b.call("cmd_send", 11, 30, None, "after cutover", 0)
    # a plan deeper than 25 levels: its rollback paths pass MySQL's default 1024-byte sort key
    parent, chain = 1, []
    for i in range(40):
        parent = b.one("cmd_card", 10, 20, f"deep {i}", None, None, parent, None, 0)["card"]
        chain.append(parent)
    b.one("cmd_card", 10, 20, "deep sibling", None, None, chain[30], None, 0)
    back = bm.rollback(cn, src + "_b", src + "_r")
    assert back["seconds"] >= 0
    r = Book(cn, src + "_r")
    q_parent = ("SELECT t.type, t.id, (SELECT CONCAT(p.type, ':', p.id) FROM {db}.tree p WHERE p.name_id = t.name_id AND p.lft < t.lft"
                " AND p.rgt > t.rgt ORDER BY p.lft DESC LIMIT 1) FROM {db}.tree t")
    before = {x for x in r.q(q_parent.format(db=src)) if x[2]}
    after = {x for x in r.q(q_parent.format(db=src + "_r")) if x[2]}
    assert before <= after  # every old parent link is back; the new reply adds one
    overlap = r.q("SELECT COUNT(*) FROM tree a JOIN tree b ON b.name_id = a.name_id AND (a.type, a.id) <> (b.type, b.id)"
                  " WHERE a.lft < b.lft AND b.lft < a.rgt AND a.rgt < b.rgt")[0][0]
    assert overlap == 0
    deep = {x for x in after if x[0] == "todo" and x[1] in chain}
    assert ("todo", chain[-1], f"todo:{chain[-2]}") in deep and len(deep) == len(chain)
    assert r.q("SELECT roster_id, desk_id FROM mail WHERE id = 2")[0] == (20, 11)
    assert r.q("SELECT status, assigned_id FROM todo WHERE id = 1")[0] == ("claimed", 11)
    assert r.q("SELECT desk_id, roster_id FROM score WHERE id = 900")[0] == (20, 20)
    assert r.q("SELECT COUNT(*) FROM mail")[0][0] == 4
    assert r.q("SELECT type FROM name WHERE id = %s", (d,))[0][0] == "desk"
    assert {x for x in r.q("SELECT name_id, desk_id FROM member")} >= {(1, 10), (2, 10), (20, 11)}
