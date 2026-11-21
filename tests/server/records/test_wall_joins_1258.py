"""Cards 1258, 1259, 1260: Wall and list join fixes from the labels/trees joins audit.

1258: Wall score and todo reads drop retired rows, as the CLI does, and a role/lan
wall lists one row per score (not one per roster the desk is on).
1259: a letter on several trees takes its crumb from its room tree only.
1260: mill inbox --label matches in SQL before --limit.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.sql

from agent_coord.client.tokens import token_hash
from agent_coord.helpers import activity_label as al
from agent_coord.server.api.mill import rpc
from agent_coord.server.records import join as rec_join
from agent_coord.server.records import label as rec_label
from agent_coord.server.records import mail as rec_mail
from agent_coord.server.records import score as rec_score
from agent_coord.server.records import todo as rec_todo
from agent_coord.server.records import tree as rec_tree
from agent_coord.server.records.db import call
from tests.server.records.conftest import seed_member, seed_names


class _Book:
    def __init__(self, cn):
        self._cn = cn


def _seat(cn, *desks):
    for d in desks:
        rec_join.upsert(cn, "Office", d, "", token_hash("seat-" + d))
    cn.commit()


def _fp(cn, kind, ident, part):
    rows = call(cn, "mill_floor_fp", [kind, ident, part])
    return str(rows[0]["fp"])


# 1258 -----------------------------------------------------------------------


def test_role_wall_lists_one_row_per_score(cn) -> None:
    seed_names(cn, ("w1258a", "roster"), ("w1258b", "roster"))
    _seat(cn, "d1258")
    seed_member(cn, "w1258a", "d1258")
    seed_member(cn, "w1258b", "d1258")
    rec_score.point_add(cn, "w1258a", "d1258", "k1258", 1.0)
    cn.commit()
    rows = [r for r in call(cn, "mill_floor_part", ["role", "w1258b", "scores"]) if r.get("kpi") == "k1258"]
    assert [r.get("roster_id") for r in rows] == ["w1258b"]


def test_lan_wall_lists_one_row_per_score(cn) -> None:
    seed_names(cn, ("w1258c", "roster"), ("w1258d", "roster"))
    _seat(cn, "e1258")
    seed_member(cn, "w1258d", "e1258")
    seed_member(cn, "w1258c", "e1258")
    cur = cn.cursor()
    cur.execute(
        "UPDATE seat s JOIN name n ON n.id = s.desk_id SET s.lan_ip = '192.0.2.58' WHERE n.name = 'e1258'"
    )
    cur.close()
    rec_score.point_add(cn, "w1258c", "e1258", "k1258lan", 2.0)
    cn.commit()
    rows = [r for r in call(cn, "mill_floor_part", ["lan", "192.0.2.58", "scores"]) if r.get("kpi") == "k1258lan"]
    # The lowest-id roster that is not Office: w1258c was minted first.
    assert [r.get("roster_id") for r in rows] == ["w1258c"]


def test_wall_score_reads_drop_a_retired_score(cn) -> None:
    seed_names(cn, ("w1258s", "roster"))
    _seat(cn, "s1258")
    seed_member(cn, "w1258s", "s1258")
    rec_score.point_add(cn, "w1258s", "s1258", "live1258", 1.0)
    rec_score.point_add(cn, "w1258s", "s1258", "gone1258", 3.0)
    cn.commit()
    fp_before = _fp(cn, "project", "w1258s", "scores")
    role_fp_before = _fp(cn, "role", "w1258s", "scores")
    rec_score.retire(cn, "w1258s", "s1258", "gone1258")
    cn.commit()

    def kpis(rows):
        return sorted(str(r.get("kpi")) for r in rows if str(r.get("kpi")).endswith("1258"))

    assert kpis(rec_score.points(cn, "w1258s", "", 10)) == ["live1258"]  # the CLI read
    assert kpis(rec_score.select(cn, "w1258s")) == ["live1258"]
    assert kpis(r for _n, r in rec_score.select_rosters(cn, ["w1258s"])) == ["live1258"]
    assert kpis(call(cn, "mill_floor_part", ["role", "w1258s", "scores"])) == ["live1258"]
    # A retire writes activity only; the part fps must still move so a polling Wall drops the row.
    assert _fp(cn, "project", "w1258s", "scores") != fp_before
    assert _fp(cn, "role", "w1258s", "scores") != role_fp_before


def test_role_wall_todos_drop_a_retired_card(cn) -> None:
    seed_names(cn, ("w1258t", "roster"))
    _seat(cn, "t1258")
    seed_member(cn, "w1258t", "t1258")
    keep = int(rec_todo.insert(cn, "w1258t", "t1258", "open", "keep")[0]["id"])
    gone = int(rec_todo.insert(cn, "w1258t", "t1258", "open", "gone")[0]["id"])
    cn.commit()
    rec_todo.retire(cn, gone, "t1258")
    cn.commit()
    ids = {int(r["id"]) for r in call(cn, "mill_floor_part", ["role", "w1258t", "todos"])}
    assert keep in ids and gone not in ids


# 1259 -----------------------------------------------------------------------


def _two_tree_letter(cn, tag: str):
    seed_names(cn, ("w1259" + tag, "roster"))
    _seat(cn, "a1259" + tag, "b1259" + tag)
    r = "w1259" + tag
    m1 = int(rec_mail.insert(cn, r, "a1259" + tag, "b1259" + tag, "root")[0]["id"])
    m2 = int(rec_mail.insert(cn, r, "b1259" + tag, "a1259" + tag, "reply")[0]["id"])
    cn.commit()
    rec_tree.create(cn, "room-1259" + tag, "mail", m1)
    rec_tree.add(cn, "mail", m1, "mail", m2, "room-1259" + tag)
    cn.commit()
    return r, m1, m2


def test_crumb_on_one_tree_is_unchanged(cn) -> None:
    _r, m1, m2 = _two_tree_letter(cn, "x")
    want = {"tree": "room-1259x", "root_id": m1, "root_type": "mail", "parent_id": m1, "parent_type": "mail"}
    assert rec_mail.tree_crumbs(cn, m2) == want
    assert rec_mail.tree_crumbs_batch(cn, [m2])[m2] == want
    assert rec_mail.tree_crumbs(cn, m1) == {"tree": "room-1259x", "root_id": m1, "root_type": "mail"}


def test_crumb_of_a_letter_on_two_trees_reads_its_room(cn) -> None:
    r, m1, m2 = _two_tree_letter(cn, "y")
    t1 = int(rec_todo.insert(cn, r, "a1259y", "open", "plan card")[0]["id"])
    cn.commit()
    rec_tree.create(cn, "plan-1259y", "todo", t1)
    rec_tree.add(cn, "todo", t1, "mail", m2, "plan-1259y")
    cn.commit()
    want = {"tree": "room-1259y", "root_id": m1, "root_type": "mail", "parent_id": m1, "parent_type": "mail"}
    assert rec_mail.tree_crumbs(cn, m2) == want
    assert rec_mail.tree_crumbs_batch(cn, [m1, m2])[m2] == want


# 1260 -----------------------------------------------------------------------


def _inbox(cn, owner: str, labels: list[str], limit: int, *, any_mode: bool = False, all_mail: bool = True):
    book = _Book(cn)
    body = {"labels": labels, "limit": limit}
    if all_mail:
        body["all"] = True
    if any_mode:
        body["label_any"] = True
    got = al.run_labeled(book, "inbox", body, owner, lambda: rpc._h_inbox(book, body, "", owner))
    rows = got["rows"] if isinstance(got, dict) else got
    return [int(r.get("id")) for r in rows]


def test_inbox_label_matches_before_the_limit(cn) -> None:
    seed_names(cn, ("w1260", "roster"), ("urgent1260", "label"), ("ops1260", "label"))
    _seat(cn, "ia1260", "ib1260")
    both = int(rec_mail.insert(cn, "w1260", "ia1260", "ib1260", "old, both labels")[0]["id"])
    rec_label.put(cn, "mail", both, "urgent1260")
    rec_label.put(cn, "mail", both, "ops1260")
    one = int(rec_mail.insert(cn, "w1260", "ia1260", "ib1260", "ops only")[0]["id"])
    rec_label.put(cn, "mail", one, "ops1260")
    focus = int(rec_mail.insert(cn, "w1260", "ia1260", "ib1260", "on ia1260's list")[0]["id"])
    rec_label.put(cn, "mail", focus, "ia1260")  # a desk name is that desk's focus list
    for i in range(3):
        rec_mail.insert(cn, "w1260", "ia1260", "ib1260", "newer %d" % i)
    cn.commit()
    assert _inbox(cn, "ib1260", ["urgent1260"], 2) == [both]
    assert _inbox(cn, "ib1260", ["urgent1260", "ops1260"], 2) == [both]
    assert _inbox(cn, "ib1260", ["urgent1260", "ops1260"], 2, any_mode=True) == [one, both]
    assert _inbox(cn, "ib1260", ["ia1260"], 1) == [focus]
    # Unread page (the default) cuts the same way.
    assert _inbox(cn, "ib1260", ["ops1260"], 1, all_mail=False) == [one]
    # No label: the page is the newest letters, as before.
    assert len(_inbox(cn, "ib1260", [], 2)) == 2
