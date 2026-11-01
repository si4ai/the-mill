"""Soft-delete activity (#89) + mill_activity_select state (#90)."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.sql

from agent_coord.server.records import activity, mail, score, todo, tree as rec_tree
from agent_coord.server.records.db import conn_kwargs as _conn_kwargs
from agent_coord.server.records.db import scalar
from tests.server.records.conftest import seed_names

def test_activity_has_deleted_column(cn) -> None:
    assert (
        scalar(
            cn,
            "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME='activity' "
            "AND COLUMN_NAME='deleted'",
        )
        == "deleted"
    )

def test_mail_soft_delete_and_select_state(cn) -> None:
    seed_names(cn, ("sd_proj", "roster"), ("sd_desk", "desk"), ("sd_reader", "desk"))
    mid = int(mail.insert(cn, "sd_proj", "sd_desk", "sd_reader", "hello")[0]["id"])
    desk_id = scalar(cn, "SELECT desk_id FROM activity WHERE type='mail' AND id=%s", (mid,))
    rows = activity.select(cn, desk_id=int(desk_id), limit=50)
    hit = next(r for r in rows if int(r["id"]) == mid and r["type"] == "mail")
    assert hit.get("state") == "sent"
    assert scalar(cn, "SELECT deleted FROM activity WHERE type='mail' AND id=%s", (mid,)) is None

    mail.delete(cn, mid, "sd_desk")
    assert scalar(cn, "SELECT id FROM mail WHERE id=%s", (mid,)) is None
    assert scalar(cn, "SELECT deleted FROM activity WHERE type='mail' AND id=%s", (mid,)) is not None
    assert (
        scalar(cn, "SELECT desk_id FROM activity WHERE type='mail' AND id=%s", (mid,)) == desk_id
    )
    rows2 = activity.select(cn, desk_id=int(desk_id), limit=50)
    hit2 = next(r for r in rows2 if int(r["id"]) == mid and r["type"] == "mail")
    assert hit2.get("state") == "deleted"

def test_todo_score_soft_delete_state_deleted(cn) -> None:
    """#91: deleted state widens to every activity type (not only mail)."""
    seed_names(cn, ("sd_ts", "roster"), ("sd_ts_d", "desk"))
    tid = int(todo.insert(cn, "sd_ts", "sd_ts_d", "open", "card")[0]["id"])
    sid = int(score.upsert(cn, "sd_ts", "sd_ts_d", "kpi_sd", "1", "", "")[0]["id"])
    desk_id = scalar(cn, "SELECT desk_id FROM activity WHERE type='todo' AND id=%s", (tid,))
    todo.delete(cn, tid, "sd_ts_d")
    score.delete(cn, sid, "sd_ts_d")
    rows = activity.select(cn, desk_id=int(desk_id), limit=50)
    trow = next(r for r in rows if int(r["id"]) == tid and r["type"] == "todo")
    srow = next(r for r in rows if int(r["id"]) == sid and r["type"] == "score")
    assert trow.get("state") == "deleted"
    assert srow.get("state") == "deleted"
    assert scalar(cn, "SELECT deleted FROM activity WHERE type='todo' AND id=%s", (tid,)) is not None
    assert scalar(cn, "SELECT deleted FROM activity WHERE type='score' AND id=%s", (sid,)) is not None

def test_live_todo_state_null(cn) -> None:
    seed_names(cn, ("sd_lv", "roster"), ("sd_lv_d", "desk"))
    tid = int(todo.insert(cn, "sd_lv", "sd_lv_d", "open", "live card")[0]["id"])
    desk_id = scalar(cn, "SELECT desk_id FROM activity WHERE type='todo' AND id=%s", (tid,))
    rows = activity.select(cn, desk_id=int(desk_id), limit=50)
    trow = next(r for r in rows if int(r["id"]) == tid and r["type"] == "todo")
    assert trow.get("state") is None

def test_between_rows_carry_state(cn) -> None:
    """#91: mill_between returns state per row; mail joined only for mail rows."""
    from agent_coord.server.records.db import call

    seed_names(
        cn,
        ("bw_proj", "roster"),
        ("bw_a", "desk"),
        ("bw_b", "desk"),
    )
    call(cn, "mill_member_put", ["roster", "bw_proj", "bw_a"])
    live_mid = int(mail.insert(cn, "bw_proj", "bw_a", "bw_b", "live")[0]["id"])
    gone_mid = int(mail.insert(cn, "bw_proj", "bw_a", "bw_b", "gone")[0]["id"])
    live_tid = int(todo.insert(cn, "bw_proj", "bw_a", "open", "live card")[0]["id"])
    gone_tid = int(todo.insert(cn, "bw_proj", "bw_a", "open", "gone card")[0]["id"])
    sid = int(score.upsert(cn, "bw_proj", "bw_a", "kpi_bw", "1", "", "")[0]["id"])
    mail.delete(cn, gone_mid, "bw_a")
    todo.delete(cn, gone_tid, "bw_a")
    score.delete(cn, sid, "bw_a")

    rows = activity.between_rows(cn, "project", "bw_proj", 50)
    by = {}
    for r in rows:
        by.setdefault((r["type"], int(r["id"])), set()).add(r["state"])
    assert by[("mail", live_mid)] == {"sent"}
    assert by[("mail", gone_mid)] == {"deleted"}
    assert by[("todo", live_tid)] == {None}
    assert by[("todo", gone_tid)] == {"deleted"}
    assert by[("score", sid)] == {"deleted"}
    # A live letter still lists one row per recipient with its other desk.
    live = [r for r in rows if r["type"] == "mail" and int(r["id"]) == live_mid]
    assert [r["other"] for r in live] == ["bw_b"]

def test_build_events_carry_state(cn) -> None:
    from agent_coord.server.records import floor

    seed_names(cn, ("ev_proj", "roster"), ("ev_d", "desk"))
    tid = int(todo.insert(cn, "ev_proj", "ev_d", "open", "ev card")[0]["id"])
    todo.delete(cn, tid, "ev_d")
    evs = floor.build_events(cn, [], None)
    hit = next(e for e in evs if e["type"] == "todo" and int(e["id"]) == tid)
    assert hit["state"] == "deleted"

def test_cheap_detail_state_on_book(cn) -> None:
    """#93: watcher hint default detail carries state from mill_activity_select."""
    import json

    from agent_coord.server import push

    seed_names(cn, ("cd_proj", "roster"), ("cd_d", "desk"), ("cd_r", "desk"))
    mid = int(mail.insert(cn, "cd_proj", "cd_d", "cd_r", "hint me")[0]["id"])
    tid = int(todo.insert(cn, "cd_proj", "cd_d", "open", "hint card")[0]["id"])
    assert json.loads(push._cheap_detail(cn, "mail", mid, []))["state"] == "sent"
    assert json.loads(push._cheap_detail(cn, "todo", tid, []))["state"] is None
    todo.delete(cn, tid, "cd_d")
    assert json.loads(push._cheap_detail(cn, "todo", tid, []))["state"] == "deleted"

def _plan_rows(cn, plan: str) -> list[tuple]:
    cur = cn.cursor()
    try:
        cur.execute(
            "SELECT t.type, t.id, t.lft, t.rgt FROM tree t JOIN name n ON n.id = t.name_id"
            " WHERE n.type = 'tree' AND n.name = %s ORDER BY t.lft",
            (plan,),
        )
        return [tuple(r) for r in cur.fetchall()]
    finally:
        cur.close()

def test_todo_delete_detaches_from_every_plan(cn) -> None:
    """mill_todo_delete takes the card off every plan (mill_tree_remove: children move up)."""
    seed_names(cn, ("nd_proj", "roster"), ("nd_desk", "desk"))
    root = int(todo.insert(cn, "nd_proj", "nd_desk", "open", "root")[0]["id"])
    tid = int(todo.insert(cn, "nd_proj", "nd_desk", "open", "in-tree")[0]["id"])
    kid = int(todo.insert(cn, "nd_proj", "nd_desk", "open", "child")[0]["id"])
    rec_tree.create(cn, "nd_plan", "todo", root)
    rec_tree.add(cn, "todo", root, "todo", tid, tree="nd_plan")
    rec_tree.add(cn, "todo", tid, "todo", kid, tree="nd_plan")
    rec_tree.create(cn, "nd_plan2", "todo", tid)
    # The trigger still refuses a direct DELETE while the card sits on a plan.
    cur = cn.cursor()
    try:
        with pytest.raises(Exception) as ei:
            cur.execute("DELETE FROM todo WHERE id=%s", (tid,))
        assert "still in tree" in str(ei.value)
        cn.rollback()
    finally:
        cur.close()
    todo.delete(cn, tid, "nd_desk")
    assert scalar(cn, "SELECT id FROM todo WHERE id=%s", (tid,)) is None
    assert scalar(cn, "SELECT deleted FROM activity WHERE type='todo' AND id=%s", (tid,)) is not None
    assert scalar(cn, "SELECT COUNT(*) FROM tree WHERE type='todo' AND id=%s", (tid,)) == 0
    # The child moved up under the root; the line stays packed.
    assert _plan_rows(cn, "nd_plan") == [("todo", root, 1, 4), ("todo", kid, 2, 3)]
    assert _plan_rows(cn, "nd_plan2") == []

def test_mail_delete_detaches_from_every_plan(cn) -> None:
    seed_names(cn, ("nd_m", "roster"), ("nd_md", "desk"), ("nd_mr", "desk"))
    mid = int(mail.insert(cn, "nd_m", "nd_md", "nd_mr", "in-tree-mail")[0]["id"])
    kid = int(mail.insert(cn, "nd_m", "nd_md", "nd_mr", "reply")[0]["id"])
    rec_tree.create(cn, "nd_mail_plan", "mail", mid)
    rec_tree.add(cn, "mail", mid, "mail", kid, tree="nd_mail_plan")
    mail.delete(cn, mid, "nd_md")
    assert scalar(cn, "SELECT id FROM mail WHERE id=%s", (mid,)) is None
    assert scalar(cn, "SELECT deleted FROM activity WHERE type='mail' AND id=%s", (mid,)) is not None
    assert scalar(cn, "SELECT COUNT(*) FROM tree WHERE type='mail' AND id=%s", (mid,)) == 0
    assert _plan_rows(cn, "nd_mail_plan") == [("mail", kid, 1, 2)]

def test_no_delete_in_tree_triggers_exist(cn) -> None:
    rows = []
    cur = cn.cursor()
    cur.execute(
        "SELECT TRIGGER_NAME FROM information_schema.TRIGGERS "
        "WHERE TRIGGER_SCHEMA = DATABASE() AND TRIGGER_NAME LIKE %s "
        "ORDER BY TRIGGER_NAME",
        ("%_no_delete_in_tree",),  # hold moved to hold_no_delete (#97)
    )
    rows = [r[0] for r in cur.fetchall()]
    cur.close()
    assert rows == [
        "doing_no_delete_in_tree",
        "mail_no_delete_in_tree",
        "score_no_delete_in_tree",
        "todo_no_delete_in_tree",
    ]

def test_mail_delete_clears_push_queue(cn) -> None:
    """mill_mail_delete drops push_queue mail/receipt rows for payload.id before DELETE mail."""
    seed_names(cn, ("pq_proj", "roster"), ("pq_desk", "desk"), ("pq_reader", "desk"))
    mid = int(mail.insert(cn, "pq_proj", "pq_desk", "pq_reader", "queued")[0]["id"])
    desk_id = int(scalar(cn, "SELECT id FROM name WHERE type='desk' AND name=%s", ("pq_reader",)))
    cur = cn.cursor()
    cur.execute(
        "INSERT INTO push_queue (desk_id, kind, payload, outcome) VALUES "
        "(%s, 'mail', JSON_OBJECT('id', %s, 'kind', 'mail'), 'missed'), "
        "(%s, 'receipt', JSON_OBJECT('id', %s, 'kind', 'receipt'), 'missed'), "
        "(%s, 'mail', JSON_OBJECT('id', %s, 'kind', 'mail'), 'missed')",
        (desk_id, mid, desk_id, mid, desk_id, mid + 99999),
    )
    cur.close()
    assert (
        scalar(
            cn,
            "SELECT COUNT(*) FROM push_queue WHERE CAST(JSON_UNQUOTE(JSON_EXTRACT(payload,'$.id')) AS UNSIGNED)=%s",
            (mid,),
        )
        == 2
    )
    mail.delete(cn, mid, "pq_desk")
    assert scalar(cn, "SELECT id FROM mail WHERE id=%s", (mid,)) is None
    assert (
        scalar(
            cn,
            "SELECT COUNT(*) FROM push_queue WHERE CAST(JSON_UNQUOTE(JSON_EXTRACT(payload,'$.id')) AS UNSIGNED)=%s",
            (mid,),
        )
        == 0
    )
    # decoy remains
    assert (
        scalar(
            cn,
            "SELECT COUNT(*) FROM push_queue WHERE CAST(JSON_UNQUOTE(JSON_EXTRACT(payload,'$.id')) AS UNSIGNED)=%s",
            (mid + 99999,),
        )
        == 1
    )
    assert scalar(cn, "SELECT deleted FROM activity WHERE type='mail' AND id=%s", (mid,)) is not None

