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

# own xdist_group so this module's room fixture stays on one loadgroup worker
pytestmark = [pytest.mark.sql, pytest.mark.xdist_group("add_remove_265")]

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
def office(cn):
    """Names, seats, and roster membership shared by every case in this module."""
    seed_names(cn, (R, "roster"), ("ar_r", "roster"),
               ("ar_a", "desk"), ("ar_b", "desk"), ("ar_c", "desk"), ("ar_d", "desk"), ("ar_e", "desk"))
    # 0.8.0: watcher.desk_id FKs to seat; every desk in the fixture needs a seat.
    for d in ("ar_a", "ar_b", "ar_c", "ar_d", "ar_e"):
        rec_join.upsert(cn, R, d, "", token_hash("ar-" + d))
    cn.commit()
    rec_member.put(cn, "ar_r", "ar_c", "roster")
    rec_member.put(cn, "ar_r", "ar_d", "roster")


def _mail_chain(cn, tree: str):
    """Fresh m1->m2->m3 chain plus sibling m4 on tree; m5 off-tree. Own letters only."""
    m1 = int(rec_mail.insert(cn, R, "ar_a", "ar_b", "root")[0]["id"])
    m2 = int(rec_mail.insert(cn, R, "ar_b", "ar_a", "child")[0]["id"])
    m3 = int(rec_mail.insert(cn, R, "ar_a", "ar_b", "grandchild")[0]["id"])
    m4 = int(rec_mail.insert(cn, R, "ar_b", "ar_a", "sibling")[0]["id"])
    m5 = int(rec_mail.insert(cn, R, "ar_a", "ar_b", "off tree")[0]["id"])
    rec_tree.create(cn, tree, "mail", m1)
    rec_tree.add(cn, "mail", m1, "mail", m2, tree)
    rec_tree.add(cn, "mail", m2, "mail", m3, tree)
    rec_tree.add(cn, "mail", m1, "mail", m4, tree)
    return {"m1": m1, "m2": m2, "m3": m3, "m4": m4, "m5": m5}


@pytest.fixture(scope="module")
def room(cn, office):
    """Tree used only by the order-coupled add/remove/orphan sequence."""
    return _mail_chain(cn, "ar265room")


def test_add_at_node_then_remove_subtree_and_refuse_orphan(cn, room):
    """add/remove/orphan share one room mutation sequence; one failure fails the case."""
    out = _go(cn, "add", "mail", room["m2"], "ar_c")
    assert (out["added"], out["letters"], out["desks"]) == (2, 2, 1)
    assert _tos(cn, room["m2"])["ar_c"] == 1  # node row unread
    assert _tos(cn, room["m3"])["ar_c"] == 0  # older row below it marked opened
    assert "ar_c" not in _tos(cn, room["m1"]) and "ar_c" not in _tos(cn, room["m4"])
    assert _go(cn, "add", "mail", room["m2"], "ar_c")["added"] == 0  # idempotent

    assert _go(cn, "remove", "mail", room["m2"], "ar_c")["removed"] == 2
    assert "ar_c" not in _tos(cn, room["m2"]) and "ar_c" not in _tos(cn, room["m3"])
    with pytest.raises(Exception, match="not a recipient"):
        _go(cn, "remove", "mail", room["m2"], "ar_c")

    before = _tos(cn, room["m3"])
    with pytest.raises(Exception, match=f"mail {room['m3']} would have no recipient"):
        _go(cn, "remove", "mail", room["m3"], "ar_b")
    assert _tos(cn, room["m3"]) == before


def test_add_skips_a_letters_own_sender(cn, office):
    room = _mail_chain(cn, "ar265-skip")
    _go(cn, "add", "mail", room["m1"], "ar_a")
    assert "ar_a" not in _tos(cn, room["m1"]) and "ar_a" not in _tos(cn, room["m3"])


def test_roster_on_mail_expands_to_members_now(cn, office):
    room = _mail_chain(cn, "ar265-roster")
    out = _go(cn, "add", "mail", room["m4"], "ar_r")
    assert out["desks"] == 2 and {"ar_c", "ar_d"} <= set(_tos(cn, room["m4"]))


def test_off_tree_letter_is_its_own_node(cn, office):
    mid = int(rec_mail.insert(cn, R, "ar_a", "ar_b", "off tree alone")[0]["id"])
    out = _go(cn, "add", "mail", mid, "ar_e")
    assert out["letters"] == 1 and "ar_e" in _tos(cn, mid)


def test_mail_never_writes_a_watcher_and_refuses_hint(cn, office):
    mid = int(rec_mail.insert(cn, R, "ar_a", "ar_b", "watcher gate")[0]["id"])
    with pytest.raises(CoordError, match="--hint"):
        _go(cn, "add", "mail", mid, "ar_c", hint="x")
    before = scalar(cn, "SELECT COUNT(*) FROM watcher")
    _go(cn, "add", "mail", mid, "ar_d")
    _go(cn, "remove", "mail", mid, "ar_d")
    assert scalar(cn, "SELECT COUNT(*) FROM watcher") == before
    col = scalar(cn, "SELECT COLUMN_TYPE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE()"
                     " AND TABLE_NAME = 'watcher' AND COLUMN_NAME = 'type'")
    assert "mail" not in str(col)


def test_missing_target_and_unknown_who_refused(cn, office):
    mid = int(rec_mail.insert(cn, R, "ar_a", "ar_b", "refuse who")[0]["id"])
    with pytest.raises(CoordError, match="no mail 999999"):
        _go(cn, "add", "mail", 999999, "ar_c")
    with pytest.raises(CoordError, match="no such desk or roster ghost265"):
        _go(cn, "add", "mail", mid, "ghost265")
    with pytest.raises(CoordError, match="TARGET is type:id"):
        _go(cn, "add", "name", 1, "ar_c")


def _wake(cn, typ, nid):
    return {r["desk"]: r.get("hint") for r in call(cn, "mill_watcher_select", [typ, nid])}


def _new_card(cn, slug: str) -> int:
    return int(rec_todo.insert(cn, R, "ar_a", "open", slug)[0]["id"])


def test_watch_add_remove_self(cn, office):
    card = _new_card(cn, "ar265card-watch")
    out = _go(cn, "add", "todo", card, hint="look at the diff")
    assert out["who"] == "ar_a" and out["hint"] == "look at the diff"
    assert _wake(cn, "todo", card)["ar_a"] == "look at the diff"
    assert _go(cn, "remove", "todo", card)["removed"] == 1
    assert "ar_a" not in _wake(cn, "todo", card)
    with pytest.raises(CoordError, match="ar_a is not watching todo:"):
        _go(cn, "remove", "todo", card)


def test_roster_watcher_is_refused(cn, office):
    """0.8.0: a watcher is a desk (fk_watcher_desk -> seat); a roster who is refused (F172 / lane C)."""
    card = _new_card(cn, "ar265card-roster")
    with pytest.raises(CoordError, match="no seat|roster|refused"):
        _go(cn, "add", "todo", card, "ar_r", hint="roster recipe")


def test_hold_is_watchable(cn, office):
    rec_hold.upsert(cn, R, "ar_a", "ar265-file")
    hid = int(scalar(cn, "SELECT MAX(id) FROM hold"))
    _go(cn, "add", "hold", hid, "ar_b")
    assert "ar_b" in _wake(cn, "hold", hid)


def test_other_desk_follows_member_add_trust(cn, office, monkeypatch):
    card = _new_card(cn, "ar265card-trust")
    monkeypatch.setenv("AGENT_COORD_TRUST", "limited")
    monkeypatch.setattr("agent_coord.server.admin.guard.is_role_admin", lambda cn, desk: False)
    with pytest.raises(CoordError, match="Admin"):
        _go(cn, "add", "todo", card, "ar_b")
    with pytest.raises(CoordError, match="Admin"):
        _go(cn, "add", "todo", card, "ar_r")
    assert _go(cn, "add", "todo", card)["who"] == "ar_a"  # self is always allowed
