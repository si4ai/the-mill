"""mill records regression with data. Throwaway DB. CALL mill_* only."""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.sql

from agent_coord.server.records.db import conn_kwargs as _conn_kwargs
from agent_coord.server.records import apply, connect
from agent_coord.server.records import activity, hold, join as here, mail, name, opened, score, todo
from agent_coord.server.records import tree as rec_tree
from tests.server.records.conftest import seed_names

from tests.sql_isolate import throwaway_db

TEST_DB = throwaway_db("mill_records_test")


def _presence_row(cn, typ: str, nid: int) -> dict | None:
    rows = activity.select(cn, limit=200)
    for r in rows:
        if r.get("type") == typ and int(r.get("id") or 0) == int(nid):
            return r
    return None


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


def test_name_get_or_insert_idempotent(cn) -> None:
    a = name.get_or_insert(cn, "unit", "roster")
    b = name.get_or_insert(cn, "unit", "roster")
    assert a == b
    assert name.get(cn, "unit", "roster") == a
    assert any(r["type"] == "roster" and r["name"] == "unit" for r in name.select(cn))


def test_mail_crud_dests_list_and_presence_n(cn) -> None:
    from agent_coord.server.records import member as rec_member

    seed_names(cn, ("unit", "roster"), ("a", "desk"), ("builder", "roster"))
    rec_member.put(cn, "unit", "a")
    ins = mail.insert(cn, "unit", "a", "unit", "hello everyone", dst_kind="roster")
    mid = int(ins[0]["id"])
    assert mail.get(cn, mid)[0]["body"] == "hello everyone"
    pr = _presence_row(cn, "mail", mid)
    assert pr is not None
    n1 = int(pr["n"])
    mail.update(cn, mid, "a", body="hello2")
    assert mail.get(cn, mid)[0]["body"] == "hello2"
    n2 = int(_presence_row(cn, "mail", mid)["n"])
    assert n2 == n1 + 1
    box = mail.select(cn, "a")
    assert any(int(r["id"]) == mid for r in box)
    listed = mail.list_project(cn, "unit")
    assert any(int(r["id"]) == mid for r in listed)
    mail.delete(cn, mid, "a")
    assert mail.get(cn, mid) == []
    assert _presence_row(cn, "mail", mid) is not None


def test_opened_n_and_unread(cn) -> None:
    seed_names(cn, ("unit", "roster"), ("a", "desk"), ("b", "desk"))
    ins = mail.insert(cn, "unit", "a", "b", "private")
    mid = int(ins[0]["id"])
    assert opened.read_ids(cn, [mid], "b") == set()
    rows = opened.insert(cn, mid, "b")
    assert rows and int(rows[0]["n"]) == 1
    assert opened.read_ids(cn, [mid], "b") == {mid}
    assert _presence_row(cn, "mail", mid) is not None
    opened.insert(cn, mid, "b")
    assert opened.read_ids(cn, [mid], "b") == {mid}
    mail.delete(cn, mid, "a")
    assert opened.read_ids(cn, [mid], "b") == set()


def test_todo_kanban_status_select(cn) -> None:
    seed_names(cn, ("unit", "roster"), ("a", "desk"))
    ins = todo.insert(cn, "unit", "a", "parked", '{"slug":"card-1","title":"card"}')
    tid = int(ins[0]["id"])
    todo.update(cn, tid, "a", status="open")
    assert todo.get(cn, tid)[0]["status"] == "open"
    assert any(int(r["id"]) == tid for r in todo.select(cn, "unit", "open"))
    assert all(int(r["id"]) != tid for r in todo.select(cn, "unit", "parked"))
    todo.update(cn, tid, "a", status="claimed", volunteer="a")
    assert todo.get(cn, tid)[0]["status"] == "claimed"
    todo.update(cn, tid, "a", status="done")
    todo.delete(cn, tid, "a")
    assert todo.get(cn, tid) == []
    assert _presence_row(cn, "todo", tid) is not None


def test_doing_appends_a_row_per_entry(cn) -> None:
    """#818: each doing is its own row; a pipe in the text is just text."""
    from agent_coord.server.records.db import rows_done

    here.upsert(cn, "unit", "stack", "", token_hash="b" * 64, doing="present")
    here.upsert(cn, "unit", "stack", "", token_hash="b" * 64, doing="a | b")
    rows = rows_done(
        cn,
        "SELECT g.text FROM doing g JOIN name n ON n.id = g.desk_id "
        "WHERE n.type='desk' AND n.name=%s ORDER BY g.id",
        ("stack",),
    )
    # #818 PR B: the join placeholder writes no doing text.
    assert [r["text"] for r in rows if r["text"]] == ["a | b"]


def test_hold_unique(cn) -> None:
    from agent_coord.server.records.db import scalar

    seed_names(cn, ("unit", "roster"), ("other", "roster"), ("a", "desk"), ("b", "desk"))
    a = hold.upsert(cn, "unit", "a", "weights.pt")
    assert int(a[0]["ok"]) == 1
    hid = int(a[0]["id"])
    again = hold.upsert(cn, "unit", "a", "weights.pt")
    assert int(again[0]["ok"]) == 1
    assert int(again[0]["id"]) == hid
    other = hold.upsert(cn, "other", "b", "weights.pt")
    assert int(other[0]["ok"]) == 0
    assert int(other[0]["id"]) == hid
    held = [r for r in hold.select(cn, "other") if int(r["id"]) == hid]
    assert held and held[0]["desk_id"] is not None
    stranger = hold.delete(cn, hid, "b")
    assert int(stranger[0]["ok"]) == 0
    assert scalar(cn, "SELECT desk_id FROM hold WHERE id=%s", (hid,)) is not None
    hold.delete(cn, hid, "a")
    assert scalar(cn, "SELECT id FROM hold WHERE id=%s", (hid,)) == hid
    assert scalar(cn, "SELECT desk_id FROM hold WHERE id=%s", (hid,)) is None
    taken = hold.upsert(cn, "other", "b", "weights.pt")
    assert int(taken[0]["ok"]) == 1
    assert int(taken[0]["id"]) == hid


def test_hold_drop_res_prefix(cn) -> None:
    from agent_coord.server.records.db import scalar

    seed_names(cn, ("unit", "roster"), ("a", "desk"), ("b", "desk"))
    hold.upsert(cn, "unit", "a", "coord.py")
    missed = hold.drop(cn, "other", "b", "coord.py")
    assert missed["ok"] is False
    hit = hold.drop(cn, "unit", "a", "coord.py")
    assert hit["ok"] is True
    assert hit.get("id")
    row = next(r for r in hold.select(cn, "") if int(r["id"]) == int(hit["id"]))
    assert row["desk_id"] is None
    assert scalar(cn, "SELECT resource_id FROM hold WHERE id=%s", (int(hit["id"]),)) is not None


def test_score_upsert_value(cn) -> None:
    from agent_coord.server.records.db import scalar

    a = score.upsert(cn, "unit", "a", "KPI_false", "0", "0", "ok")
    kid = int(a[0]["id"])
    score.upsert(cn, "unit", "a", "KPI_false", "1", "0", "bump")
    rows = score.select(cn, "unit")
    assert any(int(r["id"]) == kid and r["value"] == "1" for r in rows)
    score.delete(cn, kid, "a")
    # #95 score keep: the card stays (evidence RESTRICT); activity carries the soft-delete stamp.
    assert scalar(cn, "SELECT id FROM score WHERE id=%s", (kid,)) == kid
    assert scalar(cn, "SELECT deleted FROM activity WHERE type='score' AND id=%s", (kid,)) is not None


def test_floor_office_kpis(cn) -> None:
    from agent_coord.server.records.floor import floor as rec_floor

    cur = cn.cursor()
    cur.execute(
        "UPDATE score SET value='7' "
        "WHERE roster_id=1 AND desk_id IS NULL AND kpi='mill-wall.ticks'"  # beta 0.8.0
    )
    cn.commit()
    cur.close()
    d = rec_floor(cn, "the-mill")
    hit = [k for k in (d.get("kpis") or []) if k.get("kpi") == "mill-wall.ticks"]
    assert hit, d.get("kpis")
    assert hit[0].get("value") == "7"


def test_mail_insert_is_an_activity_row(cn) -> None:
    mail.insert(cn, "unit", "a", "unit", "wire", dst_kind="roster")
    sess = activity.select(cn, limit=20)
    assert any(r.get("type") == "mail" for r in sess)


def test_delete_mail_keeps_activity(cn) -> None:
    mid = int(mail.insert(cn, "unit", "a", "unit", "gone", dst_kind="roster")[0]["id"])
    mail.delete(cn, mid, "a")
    assert mail.get(cn, mid) == []
    assert _presence_row(cn, "mail", mid) is not None


def test_mail_list_is_call_not_insert(cn) -> None:
    mail.insert(cn, "unit", "a", "unit", "listed", dst_kind="roster")
    rows = mail.list_project(cn, "unit")
    assert rows and any(r.get("body") == "listed" for r in rows)


def test_tree_create_add_prune(cn) -> None:
    rec_tree.delete(cn, "unit-celko")
    root_row = todo.insert(cn, "unit", "a", "open", '{"slug":"root"}')
    rid = int(root_row[0]["id"])
    root = rec_tree.create(cn, "unit-celko", "todo", rid)
    hit = next(r for r in root if r.get("lft") is not None)
    assert int(hit["lft"]) == 1 and int(hit["rgt"]) == 2
    t1 = todo.insert(cn, "unit", "a", "open", '{"slug":"leaf"}')
    tid = int(t1[0]["id"])
    rec_tree.add(cn, "todo", rid, "todo", tid, tree="unit-celko")
    rows = rec_tree.select(cn, "unit-celko")
    assert len(rows) == 2
    assert int(rows[0]["lft"]) == 1 and int(rows[0]["rgt"]) == 4
    assert int(rows[1]["lft"]) == 2 and int(rows[1]["rgt"]) == 3
    anc = rec_tree.ancestors(cn, "unit-celko", "todo", tid)
    assert len(anc) == 2
    rec_tree.prune(cn, "todo", tid, tree="unit-celko")
    rows = rec_tree.select(cn, "unit-celko")
    assert len(rows) == 1 and int(rows[0]["rgt"]) == 2
    rec_tree.delete(cn, "unit-celko")
    todo.delete(cn, rid, "a")
    todo.delete(cn, tid, "a")


def test_tree_add_grandchild_with_right_sibling(cn) -> None:
    """#57 idx_rgt: UNIQUE(name_id,rgt) collides if rgt shift is not DESC."""
    rec_tree.delete(cn, "unit-idx-rgt")
    root_row = todo.insert(cn, "unit", "a", "open", '{"slug":"root"}')
    rid = int(root_row[0]["id"])
    rec_tree.create(cn, "unit-idx-rgt", "todo", rid)
    a = todo.insert(cn, "unit", "a", "open", '{"slug":"left"}')
    b = todo.insert(cn, "unit", "a", "open", '{"slug":"right"}')
    g = todo.insert(cn, "unit", "a", "open", '{"slug":"grand"}')
    aid, bid, gid = int(a[0]["id"]), int(b[0]["id"]), int(g[0]["id"])
    rec_tree.add(cn, "todo", rid, "todo", aid, tree="unit-idx-rgt")
    rec_tree.add(cn, "todo", rid, "todo", bid, tree="unit-idx-rgt")
    rec_tree.add(cn, "todo", aid, "todo", gid, tree="unit-idx-rgt")
    rows = rec_tree.select(cn, "unit-idx-rgt")
    rgts = [int(r["rgt"]) for r in rows]
    lfts = [int(r["lft"]) for r in rows]
    assert len(rows) == 4
    assert sorted(lfts) == lfts
    assert len(set(rgts)) == 4
    rec_tree.delete(cn, "unit-idx-rgt")
    todo.delete(cn, rid, "a")
    todo.delete(cn, aid, "a")
    todo.delete(cn, bid, "a")
    todo.delete(cn, gid, "a")


def test_tree_remove_keeps_children(cn) -> None:
    rec_tree.delete(cn, "unit-promote")
    root_row = todo.insert(cn, "unit", "a", "open", '{"slug":"root"}')
    rid = int(root_row[0]["id"])
    rec_tree.create(cn, "unit-promote", "todo", rid)
    mid = todo.insert(cn, "unit", "a", "open", '{"slug":"mid"}')
    leaf = todo.insert(cn, "unit", "a", "open", '{"slug":"leaf2"}')
    mid_id, leaf_id = int(mid[0]["id"]), int(leaf[0]["id"])
    rec_tree.add(cn, "todo", rid, "todo", mid_id, tree="unit-promote")
    rec_tree.add(cn, "todo", mid_id, "todo", leaf_id, tree="unit-promote")
    rec_tree.remove(cn, "todo", mid_id, tree="unit-promote")
    rows = rec_tree.select(cn, "unit-promote")
    ids = {(r["type"], int(r["id"])) for r in rows}
    assert ("todo", mid_id) not in ids
    assert ("todo", leaf_id) in ids
    assert ("todo", rid) in ids
    rec_tree.delete(cn, "unit-promote")
    todo.delete(cn, rid, "a")
    todo.delete(cn, mid_id, "a")
    todo.delete(cn, leaf_id, "a")


def test_tree_auto_and_named_plans(cn) -> None:
    rec_tree.delete(cn, "PROJECT_A_PLAN")
    rec_tree.delete(cn, "PROJECT_B_PLAN")
    a = todo.insert(cn, "unit", "a", "open", '{"slug":"parent"}')
    b = todo.insert(cn, "unit", "a", "open", '{"slug":"child"}')
    pid, cid = int(a[0]["id"]), int(b[0]["id"])
    auto = rec_tree.add(cn, "todo", pid, "todo", cid)
    auto_nid = int((auto[-1] or auto[0])["name_id"])
    rec_tree.add(cn, "todo", pid, "todo", cid, tree="PROJECT_A_PLAN")
    rec_tree.add(cn, "todo", pid, "todo", cid, tree="PROJECT_B_PLAN")
    try:
        rec_tree.add(cn, "todo", pid, "todo", cid)
        raise AssertionError("two plans must ask which plan")
    except Exception as e:
        assert "plan" in str(e).lower()
    from agent_coord.server.records.name import by_id as name_by_id

    rec_tree.delete(cn, name_by_id(cn, auto_nid) or "x")
    rec_tree.delete(cn, "PROJECT_A_PLAN")
    rec_tree.delete(cn, "PROJECT_B_PLAN")
    todo.delete(cn, pid, "a")
    todo.delete(cn, cid, "a")


def test_touch_bumps_the_seat_and_writes_no_entry(cn) -> None:
    """#635 / #818: a command that writes nothing else bumps the seat; no doing row."""
    from agent_coord.server.records.db import scalar

    here.upsert(cn, "unit", "trail635", "", token_hash="c" * 64, doing="present")
    cn.cursor().execute(
        "UPDATE seat j JOIN name n ON n.id = j.desk_id SET "
        "j.updated = '2000-01-01' WHERE n.type='desk' AND n.name=%s",
        ("trail635",),
    )
    cn.commit()
    count = "SELECT COUNT(*) FROM doing g JOIN name n ON n.id = g.desk_id WHERE n.type='desk' AND n.name=%s"
    before = scalar(cn, count, ("trail635",))
    here.touch(cn, "unit", "trail635")
    updated = scalar(
        cn,
        "SELECT j.updated FROM seat j JOIN name n ON n.id = j.desk_id "
        "WHERE n.type='desk' AND n.name=%s",
        ("trail635",),
    )
    assert str(updated) > "2001"
    assert scalar(cn, count, ("trail635",)) == before
