# -*- coding: utf-8 -*-
"""Security: the reserved Admin roster (id 2) keeps its name (#722).

mill_name_rename refused nothing for id 2, while the Admin guards looked Admin
up by name. A rename of id 2 (then naming another roster Admin) moved who the
guards treated as Admin. Now SQL and the handler refuse renaming id 2, and
is_role_admin / is_human_admin read roster id 2, never the name. Office (id 1)
may be renamed by an Admin: see test_sec_office_rename_722.py.
"""
from __future__ import annotations

import mysql.connector
import pytest

from agent_coord.helpers.errors import CoordError
from agent_coord.server.admin import catalog as admin_cat
from agent_coord.server.admin.guard import ADMIN_ROSTER_ID, is_human_admin, is_role_admin
from agent_coord.server.records import name as rec_name
from tests.server.records.conftest import seed_names
from tests.server.records.conftest import admin_desk

pytestmark = pytest.mark.sql

ADMIN_SPELLINGS = ("Admin", "admin", " ADMIN ", "\u00c1dmin")
HASH_ADMIN = "a7" * 32
HASH_PLAIN = "b7" * 32


def _name_of(cn, nid: int) -> str:
    cur = cn.cursor()
    try:
        cur.execute("SELECT name FROM name WHERE id = %s", (nid,))
        row = cur.fetchone()
        return row[0] if row else ""
    finally:
        cur.close()


def _sql(cn, stmt: str, args=()) -> None:
    cur = cn.cursor()
    try:
        cur.execute(stmt, args)
        cn.commit()
    finally:
        cur.close()


@pytest.fixture(scope="module")
def book(cn):
    seed_names(cn, ("r722-admin", "desk"), ("r722-plain", "desk"), ("r722-room", "roster"))
    # Seed straight in SQL, so the fixture does not lean on the code under test.
    _sql(cn, "INSERT IGNORE INTO member (name_id, desk_id)"
             " SELECT %s, id FROM name WHERE type = 'desk' AND name = 'r722-admin'",
         (ADMIN_ROSTER_ID,))
    _sql(cn, "INSERT IGNORE INTO human (bearer_hash) VALUES (%s), (%s)", (HASH_ADMIN, HASH_PLAIN))
    _sql(cn, "INSERT IGNORE INTO human_member (human_id, name_id)"
             " SELECT id, %s FROM human WHERE bearer_hash = %s", (ADMIN_ROSTER_ID, HASH_ADMIN))
    assert is_role_admin(cn, "r722-admin") is True
    return True


@pytest.mark.parametrize("spelling", ADMIN_SPELLINGS)
def test_sql_rename_admin_roster_refused(cn, book, spelling):
    with pytest.raises(mysql.connector.Error) as ei:
        rec_name.rename(cn, spelling, "r722-new", "roster", by=admin_desk(cn))
    assert "cannot rename Admin" in str(ei.value)
    assert _name_of(cn, ADMIN_ROSTER_ID) == "Admin"


@pytest.mark.parametrize("spelling", ADMIN_SPELLINGS)
def test_handler_rename_admin_roster_refused(cn, book, spelling):
    body = {"old": spelling, "new": "r722-new", "confirm": "r722-new", "yes": True, "name_type": "roster"}
    with pytest.raises(CoordError) as ei:
        admin_cat.rename(cn, "r722-admin", body)
    assert "reserved Admin roster" in str(ei.value)
    assert _name_of(cn, ADMIN_ROSTER_ID) == "Admin"


def test_rename_onto_reserved_name_refused(cn, book):
    with pytest.raises(mysql.connector.Error) as ei:
        rec_name.rename(cn, "r722-room", "admin", "roster", by=admin_desk(cn))
    assert "name in use" in str(ei.value)
    assert _name_of(cn, ADMIN_ROSTER_ID) == "Admin"


def test_other_roster_rename_still_works(cn, book):
    rows = rec_name.rename(cn, "r722-room", "r722-room2", "roster", by=admin_desk(cn))
    assert rows and rows[0].get("op") == "renamed"
    rec_name.rename(cn, "r722-room2", "r722-room", "roster", by=admin_desk(cn))


def test_guards_follow_roster_id_2_not_the_name(cn, book):
    """Even if id 2 is renamed by hand and another roster takes the name Admin,
    the guards still mean id 2."""
    try:
        _sql(cn, "UPDATE name SET name = 'r722-was-admin' WHERE id = %s", (ADMIN_ROSTER_ID,))
        _sql(cn, "UPDATE name SET name = 'Admin' WHERE type = 'roster' AND name = 'r722-room'")
        _sql(cn, "INSERT IGNORE INTO member (name_id, desk_id)"
                 " SELECT r.id, d.id FROM name r JOIN name d ON d.type = 'desk' AND d.name = 'r722-plain'"
                 " WHERE r.type = 'roster' AND r.name = 'Admin'")
        _sql(cn, "INSERT IGNORE INTO human_member (human_id, name_id)"
                 " SELECT h.id, r.id FROM human h JOIN name r ON r.type = 'roster' AND r.name = 'Admin'"
                 " WHERE h.bearer_hash = %s", (HASH_PLAIN,))
        assert is_role_admin(cn, "r722-admin") is True
        assert is_role_admin(cn, "r722-plain") is False
        assert is_human_admin(cn, HASH_ADMIN) is True
        assert is_human_admin(cn, HASH_PLAIN) is False
    finally:
        _sql(cn, "UPDATE name SET name = 'r722-room' WHERE type = 'roster' AND name = 'Admin' AND id <> %s",
             (ADMIN_ROSTER_ID,))
        _sql(cn, "UPDATE name SET name = 'Admin' WHERE id = %s", (ADMIN_ROSTER_ID,))
