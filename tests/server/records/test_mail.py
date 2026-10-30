"""W3 mail delivery. Dest desks are mail_to rows. Mail does not plant watchers."""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.sql

from agent_coord.server.records.db import conn_kwargs as _conn_kwargs
from agent_coord.server.records import apply, connect
from agent_coord.server.records import mail as rec_mail
from agent_coord.server.records import member as rec_member
from agent_coord.server.records import name as rec_name
from tests.server.records.conftest import seed_names

from tests.sql_isolate import throwaway_db
from tests.server.records.conftest import admin_desk

TEST_DB = throwaway_db("mill_records_test")


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


def _mail_to(cn, mid: int) -> set[int]:
    cur = cn.cursor()
    cur.execute("SELECT desk_id FROM mail_to WHERE type='mail' AND id=%s", (mid,))
    ids = {int(r[0]) for r in cur.fetchall()}
    cur.close()
    return ids


def test_mail_select_src_is_sender_not_dest(cn) -> None:
    """mill_mail_select: desk_id is sender; dst_id is dest. t.desk_id must not overwrite m.desk_id."""
    seed_names(cn, ("unit", "roster"), ("a", "desk"), ("b", "desk"))
    rows = rec_mail.insert(cn, "unit", "a", "b", "from a to b")
    mid = int(rows[0]["id"])
    a = rec_name.get(cn, "a", "desk")
    b = rec_name.get(cn, "b", "desk")
    got = rec_mail.select(cn, "b")
    rec = next(r for r in got if int(r["id"]) == mid)
    assert int(rec["desk_id"]) == a
    assert int(rec["dst_id"]) == b
    assert int(rec["desk_id"]) != int(rec["dst_id"])


def test_mail_select_card_roster_only(cn) -> None:
    """Inbox roster is mail.roster_id; no fallback to activity.roster_id."""
    seed_names(cn, ("unit", "roster"), ("a", "desk"), ("b", "desk"))
    mid = int(rec_mail.insert(cn, "unit", "a", "b", "tagged")[0]["id"])
    unit = rec_name.get(cn, "unit", "roster")
    office = rec_name.get(cn, "Office", "roster")
    rec = next(r for r in rec_mail.select(cn, "b") if int(r["id"]) == mid)
    assert int(rec["roster_id"]) == unit
    assert rec["roster"] == "unit"
    # Retag the letter, then put activity back on unit (send tags both since
    # card 841; the drift is made by hand) so inbox must not fall back.
    cur = cn.cursor()
    cur.execute("UPDATE mail SET roster_id=%s WHERE type='mail' AND id=%s", (office, mid))
    cur.execute("UPDATE activity SET roster_id=%s, updated=updated WHERE type='mail' AND id=%s", (unit, mid))
    cn.commit()
    cur.execute("SELECT roster_id FROM activity WHERE type='mail' AND id=%s", (mid,))
    act_aff = cur.fetchone()[0]
    cur.close()
    assert act_aff is not None and int(act_aff) == unit  # activity still carries unit
    # Inbox is desk-scoped; roster fields must still come from the letter column.
    rec = next(r for r in rec_mail.select(cn, "b") if int(r["id"]) == mid)
    assert int(rec["roster_id"]) == office
    assert rec["roster"] == "Office"
    assert rec["sender_roster"] == "Office"


def test_mail_get_card_roster_only(cn) -> None:
    """mill_mail_get roster is mail.roster_id; no fallback to activity.roster_id."""
    seed_names(cn, ("unit", "roster"), ("a", "desk"), ("b", "desk"))
    mid = int(rec_mail.insert(cn, "unit", "a", "b", "tagged-get")[0]["id"])
    unit = rec_name.get(cn, "unit", "roster")
    office = rec_name.get(cn, "Office", "roster")
    rows = rec_mail.get(cn, mid)
    assert rows and int(rows[0]["roster_id"]) == unit
    assert rows[0]["roster"] == "unit"
    # Retag the letter, then put activity back on unit (send tags both since
    # card 841; the drift is made by hand) so get must not fall back.
    cur = cn.cursor()
    cur.execute("UPDATE mail SET roster_id=%s WHERE type='mail' AND id=%s", (office, mid))
    cur.execute("UPDATE activity SET roster_id=%s, updated=updated WHERE type='mail' AND id=%s", (unit, mid))
    cn.commit()
    cur.execute("SELECT roster_id FROM activity WHERE type='mail' AND id=%s", (mid,))
    act_aff = cur.fetchone()[0]
    cur.close()
    assert act_aff is not None and int(act_aff) == unit  # activity still carries unit
    rows = rec_mail.get(cn, mid)
    assert rows and int(rows[0]["roster_id"]) == office
    assert rows[0]["roster"] == "Office"
    assert rows[0]["sender_roster"] == "Office"


def test_w3_role_expands_to_member_desks(cn) -> None:
    """mill send dest=ROLE_: snapshot member desks onto mail_to, not the ROLE_ name."""
    seed_names(cn, ("unit", "roster"), ("a", "desk"), ("b", "desk"), ("c", "desk"))
    rec_name.host_put(cn, "builder", "roster")
    rec_member.put(cn, "builder", "b", kind="roster")
    rec_member.put(cn, "builder", "c", kind="roster")
    rows = rec_mail.insert(cn, "unit", "a", "builder", "queue", receipt=1, dst_kind="roster")
    mid = int(rows[0]["id"])
    a = rec_name.get(cn, "a", "desk")
    b = rec_name.get(cn, "b", "desk")
    c = rec_name.get(cn, "c", "desk")
    rid = rec_name.get(cn, "builder", "roster")
    dests = _mail_to(cn, mid)
    assert {b, c} <= dests
    assert a not in dests
    assert rid not in dests
    cur = cn.cursor()
    cur.execute("SELECT receipt FROM mail_to WHERE id=%s AND desk_id=%s", (mid, b))
    receipt = cur.fetchone()[0]
    cur.close()
    assert int(receipt) == 1
