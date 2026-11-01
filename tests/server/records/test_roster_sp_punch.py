"""Roster SP punch (source-docs mail 308 / todos 82-88): letter columns are SoR."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.sql

from agent_coord.server.records import mail, score, todo
from agent_coord.server.records.db import conn_kwargs as _conn_kwargs
from agent_coord.server.records.db import scalar
from tests.server.records.conftest import seed_names

def _call_dict(cn, sql: str, params=()):
    cur = cn.cursor(dictionary=True)
    cur.execute(sql, params)
    rows = list(cur.fetchall())
    while cur.nextset():
        pass
    cur.close()
    return rows

def test_mail_insert_writes_letter_roster(cn) -> None:
    seed_names(cn, ("affil_proj", "roster"), ("affil_desk", "desk"), ("affil_reader", "desk"))
    mid = int(mail.insert(cn, "affil_proj", "affil_desk", "affil_reader", "letter")[0]["id"])
    m_aff = scalar(cn, "SELECT roster_id FROM mail WHERE id=%s", (mid,))
    a_aff = scalar(cn, "SELECT roster_id FROM activity WHERE type='mail' AND id=%s", (mid,))
    proj = scalar(cn, "SELECT id FROM name WHERE type = 'roster' AND name='affil_proj'")
    assert m_aff == proj
    assert a_aff == proj

def test_mail_update_delete_read_letter_roster(cn) -> None:
    seed_names(cn, ("affil_upd", "roster"), ("affil_upd_d", "desk"), ("affil_upd_r", "desk"))
    mid = int(mail.insert(cn, "affil_upd", "affil_upd_d", "affil_upd_r", "one")[0]["id"])
    m_aff = scalar(cn, "SELECT roster_id FROM mail WHERE id=%s", (mid,))
    office = scalar(cn, "SELECT id FROM name WHERE type = 'roster' AND name='Office'")
    cur = cn.cursor()
    cur.execute(
        "UPDATE activity SET roster_id=%s WHERE type='mail' AND id=%s",
        (office, mid),
    )
    cn.commit()
    cur.close()
    mail.update(cn, mid, "affil_upd_d", body="two")
    assert (
        scalar(cn, "SELECT roster_id FROM activity WHERE type='mail' AND id=%s", (mid,))
        == m_aff
    )
    mail.delete(cn, mid, "affil_upd_d")
    assert scalar(cn, "SELECT id FROM mail WHERE id=%s", (mid,)) is None
    # Soft-delete does not mill_activity_put; roster_id stays as pre-delete activity value.
    assert (
        scalar(cn, "SELECT roster_id FROM activity WHERE type='mail' AND id=%s", (mid,))
        == m_aff
    )
    assert scalar(cn, "SELECT deleted FROM activity WHERE type='mail' AND id=%s", (mid,)) is not None

def test_mail_list_filters_letter_only(cn) -> None:
    seed_names(
        cn,
        ("affil_list", "roster"),
        ("affil_list_d", "desk"),
        ("affil_list_r", "desk"),
    )
    mid = int(mail.insert(cn, "affil_list", "affil_list_d", "affil_list_r", "listed")[0]["id"])
    ids = {int(r["id"]) for r in mail.list_project(cn, "affil_list")}
    assert mid in ids
    proj = scalar(cn, "SELECT id FROM name WHERE type = 'roster' AND name='affil_list'")
    desk = scalar(cn, "SELECT desk_id FROM mail WHERE id=%s", (mid,))
    cur = cn.cursor()
    # Orphan letter: card roster is Office while activity says affil_list -
    # list_project must read mail.roster_id only (NOT NULL; no NULL card).
    office = scalar(cn, "SELECT id FROM name WHERE type = 'roster' AND name='Office'")
    cur.execute("SET FOREIGN_KEY_CHECKS=0")
    cur.execute(
        "INSERT INTO mail (desk_id, roster_id, body) VALUES (%s, %s, 'orphan-letter')",
        (desk, office),
    )
    orphan = cur.lastrowid
    cur.execute(
        "INSERT INTO activity (type, id, updated, desk_id, roster_id, act, bytes) "
        "VALUES ('mail', %s, NOW(6), %s, %s, 'create', 1)",
        (orphan, desk, proj),
    )
    cur.execute(
        "INSERT INTO mail_to (type, id, desk_id, receipt) VALUES ('mail', %s, %s, 0)",
        (orphan, desk),
    )
    cur.execute("SET FOREIGN_KEY_CHECKS=1")
    cn.commit()
    cur.close()
    ids2 = {int(r["id"]) for r in mail.list_project(cn, "affil_list")}
    assert mid in ids2
    assert orphan not in ids2

def test_todo_score_delete_read_card(cn) -> None:
    seed_names(cn, ("affil_del", "roster"), ("affil_del_d", "desk"))
    tid = int(todo.insert(cn, "affil_del", "affil_del_d", "open", "card")[0]["id"])
    sid = int(score.upsert(cn, "affil_del", "affil_del_d", "k", "1", "", "")[0]["id"])
    office = scalar(cn, "SELECT id FROM name WHERE type = 'roster' AND name='Office'")
    t_aff = scalar(cn, "SELECT roster_id FROM todo WHERE id=%s", (tid,))
    s_aff = scalar(cn, "SELECT roster_id FROM score WHERE id=%s", (sid,))
    cur = cn.cursor()
    cur.execute(
        "UPDATE activity SET roster_id=%s WHERE type='todo' AND id=%s",
        (office, tid),
    )
    cur.execute(
        "UPDATE activity SET roster_id=%s WHERE type='score' AND id=%s",
        (office, sid),
    )
    cn.commit()
    cur.close()
    todo.delete(cn, tid, "affil_del_d")
    score.delete(cn, sid, "affil_del_d")
    # Soft-delete stamps deleted only; drifted activity.roster_id is not rewritten.
    assert (
        scalar(cn, "SELECT roster_id FROM activity WHERE type='todo' AND id=%s", (tid,))
        == office
    )
    assert (
        scalar(cn, "SELECT roster_id FROM activity WHERE type='score' AND id=%s", (sid,))
        == office
    )
    assert scalar(cn, "SELECT deleted FROM activity WHERE type='todo' AND id=%s", (tid,)) is not None
    assert scalar(cn, "SELECT deleted FROM activity WHERE type='score' AND id=%s", (sid,)) is not None
    assert t_aff is not None and s_aff is not None

def test_floor_fp_mail_letter_only(cn) -> None:
    seed_names(cn, ("affil_fp", "roster"), ("affil_fp_d", "desk"), ("affil_fp_r", "desk"))
    mid = int(mail.insert(cn, "affil_fp", "affil_fp_d", "affil_fp_r", "fp")[0]["id"])
    row = _call_dict(cn, "CALL mill_floor_fp('project', %s, 'mail')", ("affil_fp",))[0]
    assert row.get("part") == "mail"
    fp1 = row["fp"]
    proj = scalar(cn, "SELECT id FROM name WHERE type = 'roster' AND name='affil_fp'")
    desk = scalar(cn, "SELECT desk_id FROM mail WHERE id=%s", (mid,))
    cur = cn.cursor()
    # Letter roster Office (not affil_fp); activity says affil_fp - fp must ignore it.
    office = scalar(cn, "SELECT id FROM name WHERE type = 'roster' AND name='Office'")
    cur.execute("SET FOREIGN_KEY_CHECKS=0")
    cur.execute(
        "INSERT INTO mail (desk_id, roster_id, body) VALUES (%s, %s, 'desk-or')",
        (desk, office),
    )
    oid = cur.lastrowid
    cur.execute(
        "INSERT INTO activity (type, id, updated, desk_id, roster_id, act, bytes) "
        "VALUES ('mail', %s, NOW(6), %s, %s, 'create', 1)",
        (oid, desk, proj),
    )
    cur.execute(
        "INSERT INTO mail_to (type, id, desk_id, receipt) VALUES ('mail', %s, %s, 0)",
        (oid, proj),
    )
    cur.execute("SET FOREIGN_KEY_CHECKS=1")
    cn.commit()
    cur.close()
    row2 = _call_dict(cn, "CALL mill_floor_fp('project', %s, 'mail')", ("affil_fp",))[0]
    assert row2["fp"] == fp1

def test_role_filter_fallback(cn) -> None:
    seed_names(cn, ("Engineer", "roster"), ("affil_role_d", "desk"))
    role_id = scalar(cn, "SELECT id FROM name WHERE type = 'roster' AND name='Engineer'")
    desk = scalar(cn, "SELECT id FROM name WHERE type='desk' AND name='affil_role_d'")
    cur = cn.cursor()
    cur.execute("SET FOREIGN_KEY_CHECKS=0")
    cur.execute(
        "INSERT INTO todo (updated, updated_id, roster_id, creator_id, status, body) "
        "VALUES (NOW(6), %s, %s, %s, 'open', 'role-card')",
        (desk, role_id, desk),
    )
    tid = cur.lastrowid
    cur.execute(
        "INSERT INTO activity (type, id, updated, desk_id, roster_id, act, bytes) "
        "VALUES ('todo', %s, NOW(6), %s, %s, 'create', 1)",
        (tid, desk, role_id),
    )
    cur.execute("SET FOREIGN_KEY_CHECKS=1")
    cn.commit()
    cur.close()
    rows = _call_dict(cn, "CALL mill_todo_select(%s, %s)", ("Engineer", ""))
    assert tid in {int(r["id"]) for r in rows}
