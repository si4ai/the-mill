"""mill add|remove TYPE:ID [WHO] (#265) on a real book.

mail: recipient rows on a node (the letter and every letter under it).
Every other kind: one watcher row; a roster watcher expands at wake time.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_coord.client.tokens import token_hash
from agent_coord.helpers.errors import CoordError
from agent_coord.server.api.mill.rpc import _h_add_remove
from agent_coord.server.records import hold as rec_hold
from agent_coord.server.records import join as rec_join
from agent_coord.server.records import mail as rec_mail
from agent_coord.server.records import member as rec_member
from agent_coord.server.records import todo as rec_todo
from agent_coord.server.records import tree as rec_tree
from agent_coord.server.records.db import call, scalar
from tests.server.records.conftest import seed_names

pytestmark = pytest.mark.sql

R = "ar265"


def _rows(cn, sql, args=()):
    cur = cn.cursor()
    try:
        cur.execute(sql, args)
        return list(cur.fetchall())
    finally:
        cur.close()


def _go(cn, command, typ, nid, who="", owner="ar_a", hint=None):
    body = {"verb": command, "type": typ, "id": nid}
    if who:
        body["who"] = who
    if hint is not None:
        body["hint"] = hint
    return _h_add_remove(SimpleNamespace(_cn=cn), body, R, owner)


def _tos(cn, mid):
    return {r[0]: r[1] for r in _rows(
        cn, "SELECT n.name, mt.opened IS NULL FROM mail_to mt JOIN name n ON n.id = mt.desk_id"
            " WHERE mt.type='mail' AND mt.id=%s", (mid,))}


@pytest.fixture(scope="module")
def room(cn):
    seed_names(cn, (R, "roster"), ("ar_r", "roster"),
               ("ar_a", "desk"), ("ar_b", "desk"), ("ar_c", "desk"), ("ar_d", "desk"), ("ar_e", "desk"))
    # 0.8.0: watcher.desk_id FKs to seat; every desk in the fixture needs a seat.
    for d in ("ar_a", "ar_b", "ar_c", "ar_d", "ar_e"):
        rec_join.upsert(cn, R, d, "", token_hash("ar-" + d), None)
    cn.commit()
    rec_member.put(cn, "ar_r", "ar_c", "roster")
    rec_member.put(cn, "ar_r", "ar_d", "roster")
    m1 = int(rec_mail.insert(cn, R, "ar_a", "ar_b", "root")[0]["id"])
    m2 = int(rec_mail.insert(cn, R, "ar_b", "ar_a", "child")[0]["id"])
    m3 = int(rec_mail.insert(cn, R, "ar_a", "ar_b", "grandchild")[0]["id"])
    m4 = int(rec_mail.insert(cn, R, "ar_b", "ar_a", "sibling")[0]["id"])
    m5 = int(rec_mail.insert(cn, R, "ar_a", "ar_b", "off tree")[0]["id"])
    rec_tree.create(cn, "ar265room", "mail", m1)
    rec_tree.add(cn, "mail", m1, "mail", m2, "ar265room")
    rec_tree.add(cn, "mail", m2, "mail", m3, "ar265room")
    rec_tree.add(cn, "mail", m1, "mail", m4, "ar265room")
    return {"m1": m1, "m2": m2, "m3": m3, "m4": m4, "m5": m5}


def test_add_at_node_backfills_subtree_only(cn, room):
    out = _go(cn, "add", "mail", room["m2"], "ar_c")
    assert (out["added"], out["letters"], out["desks"]) == (2, 2, 1)
    assert _tos(cn, room["m2"])["ar_c"] == 1  # node row unread
    assert _tos(cn, room["m3"])["ar_c"] == 0  # older row below it marked opened
    assert "ar_c" not in _tos(cn, room["m1"]) and "ar_c" not in _tos(cn, room["m4"])
    assert _go(cn, "add", "mail", room["m2"], "ar_c")["added"] == 0  # idempotent


def test_add_skips_a_letters_own_sender(cn, room):
    _go(cn, "add", "mail", room["m1"], "ar_a")
    assert "ar_a" not in _tos(cn, room["m1"]) and "ar_a" not in _tos(cn, room["m3"])


def test_roster_on_mail_expands_to_members_now(cn, room):
    out = _go(cn, "add", "mail", room["m4"], "ar_r")
    assert out["desks"] == 2 and {"ar_c", "ar_d"} <= set(_tos(cn, room["m4"]))


def test_off_tree_letter_is_its_own_node(cn, room):
    out = _go(cn, "add", "mail", room["m5"], "ar_e")
    assert out["letters"] == 1 and "ar_e" in _tos(cn, room["m5"])


def test_remove_at_node_drops_subtree_rows(cn, room):
    assert _go(cn, "remove", "mail", room["m2"], "ar_c")["removed"] == 2
    assert "ar_c" not in _tos(cn, room["m2"]) and "ar_c" not in _tos(cn, room["m3"])
    with pytest.raises(Exception, match="not a recipient"):
        _go(cn, "remove", "mail", room["m2"], "ar_c")


def test_remove_refuses_an_orphan_letter_and_changes_nothing(cn, room):
    before = _tos(cn, room["m3"])
    with pytest.raises(Exception, match=f"mail {room['m3']} would have no recipient"):
        _go(cn, "remove", "mail", room["m3"], "ar_b")
    assert _tos(cn, room["m3"]) == before


def test_mail_never_writes_a_watcher_and_refuses_hint(cn, room):
    with pytest.raises(CoordError, match="--hint"):
        _go(cn, "add", "mail", room["m1"], "ar_c", hint="x")
    before = scalar(cn, "SELECT COUNT(*) FROM watcher")
    _go(cn, "add", "mail", room["m1"], "ar_d")
    _go(cn, "remove", "mail", room["m1"], "ar_d")
    assert scalar(cn, "SELECT COUNT(*) FROM watcher") == before
    col = scalar(cn, "SELECT COLUMN_TYPE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE()"
                     " AND TABLE_NAME = 'watcher' AND COLUMN_NAME = 'type'")
    assert "mail" not in str(col)


def test_missing_target_and_unknown_who_refused(cn, room):
    with pytest.raises(CoordError, match="no mail 999999"):
        _go(cn, "add", "mail", 999999, "ar_c")
    with pytest.raises(CoordError, match="no such desk or roster ghost265"):
        _go(cn, "add", "mail", room["m1"], "ghost265")
    with pytest.raises(CoordError, match="TARGET is type:id"):
        _go(cn, "add", "name", 1, "ar_c")


@pytest.fixture(scope="module")
def card(cn, room):
    return int(rec_todo.insert(cn, R, "ar_a", "open", "ar265card")[0]["id"])


def _wake(cn, typ, nid):
    return {r["desk"]: r.get("hint") for r in call(cn, "mill_watcher_select", [typ, nid])}


def test_watch_add_remove_self(cn, card):
    out = _go(cn, "add", "todo", card, hint="look at the diff")
    assert out["who"] == "ar_a" and out["hint"] == "look at the diff"
    assert _wake(cn, "todo", card)["ar_a"] == "look at the diff"
    assert _go(cn, "remove", "todo", card)["removed"] == 1
    assert "ar_a" not in _wake(cn, "todo", card)
    with pytest.raises(CoordError, match="ar_a is not watching todo:"):
        _go(cn, "remove", "todo", card)


def test_roster_watcher_is_refused(cn, card):
    """0.8.0: a watcher is a desk (fk_watcher_desk -> seat); a roster who is refused (F172 / lane C)."""
    with pytest.raises(CoordError, match="no seat|roster|refused"):
        _go(cn, "add", "todo", card, "ar_r", hint="roster recipe")


def test_hold_is_watchable(cn, room):
    rec_hold.upsert(cn, R, "ar_a", "ar265-file")
    hid = int(scalar(cn, "SELECT MAX(id) FROM hold"))
    _go(cn, "add", "hold", hid, "ar_b")
    assert "ar_b" in _wake(cn, "hold", hid)


def test_other_desk_follows_member_add_trust(cn, card, monkeypatch):
    monkeypatch.setenv("AGENT_COORD_TRUST", "limited")
    monkeypatch.setattr("agent_coord.server.admin.guard.is_role_admin", lambda cn, desk: False)
    with pytest.raises(CoordError, match="Admin"):
        _go(cn, "add", "todo", card, "ar_b")
    with pytest.raises(CoordError, match="Admin"):
        _go(cn, "add", "todo", card, "ar_r")
    assert _go(cn, "add", "todo", card)["who"] == "ar_a"  # self is always allowed
