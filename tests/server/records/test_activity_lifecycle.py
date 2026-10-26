"""Activity stays with its id. Updates bump it. Deletes of the five details do not free the id."""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.sql

from agent_coord.server.records import hold, join as here, mail, name, opened, score, todo
from agent_coord.server.records import apply, connect
from agent_coord.server.records.db import conn_kwargs as _conn_kwargs
from agent_coord.server.records.db import scalar
from tests.server.records.conftest import admin_desk
from tests.server.records.conftest import seed_names

from tests.sql_isolate import throwaway_db

TEST_DB = throwaway_db("mill_activity_life_test")


def _cn():
    import mysql.connector

    kw = _conn_kwargs()
    kw.pop("database", None)
    kw["autocommit"] = True
    admin = mysql.connector.connect(**kw)
    cur = admin.cursor()
    cur.execute(
        f"CREATE DATABASE IF NOT EXISTS `{TEST_DB}` "
        "DEFAULT CHARACTER SET utf8mb4 DEFAULT COLLATE utf8mb4_0900_ai_ci"
    )
    cur.close()
    admin.close()
    os.environ["AGENT_COORD_DATABASE"] = TEST_DB
    cn = connect(TEST_DB)
    apply(cn, wipe=True)
    return cn


@pytest.fixture(scope="module")
def cn():
    try:
        c = _cn()
    except Exception as e:
        pytest.skip(f"mysql mill records: {e}")
    yield c
    c.close()


def _n(cn, typ: str, nid: int) -> int:
    rec = scalar(cn, "SELECT n FROM activity WHERE type=%s AND id=%s", (typ, nid))
    assert rec is not None, f"missing activity {typ} {nid}"
    return int(rec)


def _gone(cn, table: str, nid: int) -> bool:
    rec = scalar(cn, f"SELECT id FROM `{table}` WHERE id=%s", (nid,))
    return rec is None


def test_mail_update_then_delete_keeps_activity_and_id(cn) -> None:
    seed_names(cn, ("life_mail", "roster"), ("life_mail", "desk"), ("life_reader", "desk"))
    mid = int(mail.insert(cn, "life_mail", "life_mail", "life_reader", "one")[0]["id"])
    assert _n(cn, "mail", mid) == 1
    mail.update(cn, mid, "life_mail", body="two")
    assert _n(cn, "mail", mid) == 2
    aff = scalar(cn, "SELECT roster_id FROM activity WHERE type='mail' AND id=%s", (mid,))
    desk = scalar(cn, "SELECT desk_id FROM activity WHERE type='mail' AND id=%s", (mid,))
    opened.insert(cn, mid, "life_reader")
    assert _n(cn, "mail", mid) == 2
    assert scalar(cn, "SELECT roster_id FROM activity WHERE type='mail' AND id=%s", (mid,)) == aff
    assert scalar(cn, "SELECT desk_id FROM activity WHERE type='mail' AND id=%s", (mid,)) == desk
    desk_before = desk
    n_before = _n(cn, "mail", mid)
    mail.delete(cn, mid, "life_mail")
    assert _gone(cn, "mail", mid)
    assert _n(cn, "mail", mid) == n_before
    assert scalar(cn, "SELECT deleted FROM activity WHERE type='mail' AND id=%s", (mid,)) is not None
    assert scalar(cn, "SELECT desk_id FROM activity WHERE type='mail' AND id=%s", (mid,)) == desk_before
    assert scalar(cn, "SELECT roster_id FROM activity WHERE type='mail' AND id=%s", (mid,)) == aff
    nxt = int(mail.insert(cn, "life_mail", "life_mail", "life_reader", "three")[0]["id"])
    assert nxt > mid
    assert _n(cn, "mail", mid) == n_before
    assert _n(cn, "mail", nxt) == 1


def test_todo_update_then_delete_keeps_activity_and_id(cn) -> None:
    seed_names(cn, ("life_todo", "roster"), ("life_todo", "desk"))
    tid = int(todo.insert(cn, "life_todo", "life_todo", "open", "card")[0]["id"])
    assert _n(cn, "todo", tid) == 1
    todo.update(cn, tid, "life_todo", status="claimed", volunteer="life_todo")
    assert _n(cn, "todo", tid) == 2
    desk_before = scalar(cn, "SELECT desk_id FROM activity WHERE type='todo' AND id=%s", (tid,))
    n_before = _n(cn, "todo", tid)
    todo.delete(cn, tid, "life_todo")
    assert _gone(cn, "todo", tid)
    assert _n(cn, "todo", tid) == n_before
    assert scalar(cn, "SELECT deleted FROM activity WHERE type='todo' AND id=%s", (tid,)) is not None
    assert scalar(cn, "SELECT desk_id FROM activity WHERE type='todo' AND id=%s", (tid,)) == desk_before
    nxt = int(todo.insert(cn, "life_todo", "life_todo", "open", "next")[0]["id"])
    assert nxt > tid
    assert _n(cn, "todo", tid) == n_before


def test_hold_release_nulls_desk_and_keeps_the_row(cn) -> None:
    seed_names(cn, ("life_hold", "roster"), ("life_hold", "desk"), ("life_hold_b", "desk"))
    first = hold.upsert(cn, "life_hold", "life_hold", "gym")
    hid = int(first[0]["id"])
    assert int(first[0]["ok"]) == 1
    assert _n(cn, "hold", hid) == 1
    again = hold.upsert(cn, "life_hold", "life_hold", "gym")
    assert int(again[0]["id"]) == hid
    assert int(again[0]["ok"]) == 1
    assert _n(cn, "hold", hid) == 1
    blocked = hold.upsert(cn, "life_hold", "life_hold_b", "gym")
    assert int(blocked[0]["ok"]) == 0
    assert _n(cn, "hold", hid) == 1
    refused = hold.delete(cn, hid, "life_hold_b")
    assert int(refused[0]["ok"]) == 0
    assert not _gone(cn, "hold", hid)
    assert _n(cn, "hold", hid) == 1
    released = hold.delete(cn, hid, "life_hold")
    assert int(released[0]["ok"]) == 1
    assert not _gone(cn, "hold", hid)
    assert scalar(cn, "SELECT desk_id FROM hold WHERE id=%s", (hid,)) is None
    assert _n(cn, "hold", hid) == 2
    taken = hold.upsert(cn, "life_hold", "life_hold_b", "gym")
    assert int(taken[0]["id"]) == hid
    assert int(taken[0]["ok"]) == 1
    assert _n(cn, "hold", hid) == 3
    nxt = int(hold.upsert(cn, "life_hold", "life_hold", "pool")[0]["id"])
    assert nxt > hid


def test_score_update_then_delete_keeps_activity_and_id(cn) -> None:
    seed_names(cn, ("life_score", "roster"), ("life_score", "desk"))
    kid = int(score.upsert(cn, "life_score", "life_score", "KPI_life", "0", "1", "a")[0]["id"])
    assert _n(cn, "score", kid) == 1
    same = int(score.upsert(cn, "life_score", "life_score", "KPI_life", "1", "1", "b")[0]["id"])
    assert same == kid
    assert _n(cn, "score", kid) == 2
    desk_before = scalar(cn, "SELECT desk_id FROM activity WHERE type='score' AND id=%s", (kid,))
    n_before = _n(cn, "score", kid)
    score.delete(cn, kid, "life_score")
    # #95 score keep: card row stays so score_evidence history stays attached.
    assert not _gone(cn, "score", kid)
    assert _n(cn, "score", kid) == n_before
    assert scalar(cn, "SELECT deleted FROM activity WHERE type='score' AND id=%s", (kid,)) is not None
    assert scalar(cn, "SELECT desk_id FROM activity WHERE type='score' AND id=%s", (kid,)) == desk_before
    nxt = int(score.upsert(cn, "life_score", "life_score", "KPI_life_2", "0", "1", "c")[0]["id"])
    assert nxt > kid
    assert _n(cn, "score", kid) == n_before


def test_join_updates_bump_activity_and_row_stays(cn) -> None:
    """#818: seat events bump the current doing entry's activity; doing appends."""
    seed_names(cn, ("life_join", "roster"), ("life_join", "desk"))
    token = "a" * 64
    jid = int(here.upsert(cn, "life_join", "life_join", "", token, "working")[0]["id"])
    assert _n(cn, "doing", jid) == 1
    nxt = int(here.upsert(cn, "life_join", "life_join", "", None, "still working")[0]["id"])
    assert nxt > jid and _n(cn, "doing", nxt) == 1
    assert scalar(cn, "SELECT text FROM doing WHERE id=%s", (jid,)) == "working"
    here.delete(cn, "life_join", "life_join")
    cur = int(scalar(cn, "SELECT MAX(id) FROM doing WHERE desk_id=(SELECT desk_id FROM doing WHERE id=%s)", (jid,)))
    assert cur > nxt and scalar(cn, "SELECT text FROM doing WHERE id=%s", (cur,)) == ""
    assert _n(cn, "doing", cur) == 1
    here.reset(cn, "life_join", "life_join")
    seat = "SELECT {} FROM seat WHERE desk_id=(SELECT desk_id FROM doing WHERE id=%s)"
    assert scalar(cn, seat.format("token_hash"), (jid,)) is None
    assert not _gone(cn, "doing", jid)
    assert _n(cn, "doing", cur) == 2
    here.mark_socket(cn, "life_join", up=True)
    assert scalar(cn, seat.format("time_connect"), (jid,)) is not None
    assert _n(cn, "doing", cur) == 3
    here.set_lan_ip(cn, "life_join", "203.0.113.10")
    assert scalar(cn, seat.format("lan_ip"), (jid,)) == "203.0.113.10"
    assert _n(cn, "doing", cur) == 4
    again = int(here.upsert(cn, "life_join", "life_join", "", None, "back")[0]["id"])
    assert again > cur and scalar(cn, "SELECT text FROM doing WHERE id=%s", (again,)) == "back"


def test_join_refuses_role_admin(cn) -> None:
    seed_names(cn, ("life_admin_proj", "roster"), ("life_admin", "desk"))
    with pytest.raises(Exception) as ei:
        here.upsert(cn, "life_admin_proj", "life_admin", "Admin", token_hash="c" * 64)
    assert "Admin is not granted by join" in str(ei.value)


def test_name_rename_retire_reclaim_keep_id(cn) -> None:
    nid = name.get_or_insert(cn, "life_nm", "roster")
    assert scalar(cn, "SELECT type FROM name WHERE id=%s", (nid,)) == "roster"
    assert scalar(cn, "SELECT name FROM name WHERE id=%s", (nid,)) == "life_nm"
    assert scalar(cn, "SELECT 1 FROM activity WHERE type='name' AND id=%s", (nid,)) is None
    name.rename(cn, "life_nm", "life_nm2", "roster", by=admin_desk(cn))
    assert name.get(cn, "life_nm2", "roster") == nid
    name.retire(cn, "life_nm2", "roster", by=admin_desk(cn))
    assert scalar(cn, "SELECT deleted FROM name WHERE id=%s", (nid,)) is not None
    assert name.get(cn, "life_nm2", "roster") is None
    other = name.get_or_insert(cn, "life_nm3", "roster")
    assert other != nid
    assert scalar(cn, "SELECT id FROM name WHERE id=%s", (nid,)) == nid
    name.reclaim(cn, "life_nm2", "roster", by=admin_desk(cn))
    assert name.get(cn, "life_nm2", "roster") == nid


def test_membership_does_not_write_a_name_activity(cn) -> None:
    assert scalar(cn, "SELECT 1 FROM activity WHERE type='name' AND id=1") is None
    here.upsert(cn, "Office", "life_office", "", "b" * 64, "")
    assert scalar(cn, "SELECT 1 FROM activity WHERE type='name' AND id=1") is None
    here.upsert(cn, "life_role", "life_role", "life_role", "c" * 64, "")
    rid = name.get(cn, "life_role", "roster")
    assert rid is not None
    assert scalar(cn, "SELECT type FROM name WHERE id=%s", (rid,)) == "roster"
    assert scalar(cn, "SELECT name FROM name WHERE id=%s", (rid,)) == "life_role"
    assert scalar(cn, "SELECT 1 FROM activity WHERE type='name' AND id=%s", (rid,)) is None


def test_hard_activity_delete_leaves_the_card(cn) -> None:
    """#216: activity is the timeline, not a parent. No payload FK, so no cascade either:
    a hard activity delete (never done by mill; delete is a soft stamp) leaves the card."""
    seed_names(cn, ("life_cascade", "roster"), ("life_cascade", "desk"))
    tid = int(todo.insert(cn, "life_cascade", "life_cascade", "open", "cascade")[0]["id"])
    cur = cn.cursor()
    try:
        cur.execute("DELETE FROM watcher WHERE type='todo' AND id=%s", (tid,))
        cur.execute("DELETE FROM activity WHERE type='todo' AND id=%s", (tid,))
        cn.commit()
    finally:
        cur.close()
    assert scalar(cn, "SELECT COUNT(*) FROM todo WHERE id=%s", (tid,)) == 1
    assert scalar(cn, "SELECT COUNT(*) FROM activity WHERE type='todo' AND id=%s", (tid,)) == 0
    nxt = int(todo.insert(cn, "life_cascade", "life_cascade", "open", "after")[0]["id"])
    assert nxt > tid
