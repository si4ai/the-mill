# -*- coding: utf-8 -*-
"""An Admin may rename the Office roster (id 1); everything that means Office follows id 1 (#722).

Code that found Office by the name 'Office' broke after such a rename. Now SQL
and the server reach Office by id 1, and the protocol name Office stays an
alias of id 1 (MILL_NAME_GET / MILL_NAME_PUT, the RPC project field), so no
other roster may take that name while Office is renamed.
"""
from __future__ import annotations

import mysql.connector
import pytest

from agent_coord.server.admin import catalog as admin_cat
from agent_coord.server.admin.guard import (
    ADMIN_ROSTER_ID,
    OFFICE_ROSTER_ID,
    is_office_roster,
    office_name,
)
from agent_coord.server.admin.seats import resolve_seat_roster
from agent_coord.server.api.mill import rpc
from agent_coord.server.records import member as rec_member
from agent_coord.server.records import name as rec_name
from agent_coord.server.records import score as rec_score
from agent_coord.server.records.db import call
from tests.server.records.conftest import seed_names
from tests.server.records.conftest import admin_desk

pytestmark = pytest.mark.sql

NEW = "r722o-hq"


def _one(cn, sql: str, args=()):
    cur = cn.cursor()
    try:
        cur.execute(sql, args)
        row = cur.fetchone()
        return row[0] if row else None
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
def renamed(cn):
    seed_names(cn, ("r722o-admin", "desk"), ("r722o-plain", "desk"), ("r722o-room", "roster"))
    admin_desk(cn, "r722o-admin")  # 0.8.0: a seated Admin (sp_name_rename checks the acting desk)
    body = {"old": "Office", "new": NEW, "confirm": NEW, "yes": True, "name_type": "roster"}
    rows = admin_cat.rename(cn, "r722o-admin", body)
    assert rows and rows[0].get("op") == "renamed"
    assert _one(cn, "SELECT name FROM name WHERE id = 1") == NEW
    yield NEW
    rec_name.rename(cn, NEW, "Office", "roster", by=admin_desk(cn))
    assert _one(cn, "SELECT name FROM name WHERE id = 1") == "Office"


def test_office_name_follows_id_1(cn, renamed):
    assert office_name(cn) == NEW
    for spelling in ("Office", "office", NEW):
        assert is_office_roster(cn, spelling) is True
    assert is_office_roster(cn, "r722o-room") is False


@pytest.mark.parametrize("spelling", ("Office", "office", " OFFICE "))
def test_sql_alias_office_is_id_1(cn, renamed, spelling):
    assert _one(cn, "SELECT MILL_NAME_GET('roster', %s)", (spelling,)) == OFFICE_ROSTER_ID
    assert rec_name.get_or_insert(cn, spelling, "roster") == OFFICE_ROSTER_ID
    assert _one(cn, "SELECT COUNT(*) FROM name WHERE type = 'roster' AND name = 'Office'") == 0


def test_no_other_roster_takes_the_name_office(cn, renamed):
    with pytest.raises(mysql.connector.Error) as ei:
        rec_name.rename(cn, "r722o-room", "Office", "roster", by=admin_desk(cn))
    assert "name in use" in str(ei.value)


def test_put_office_and_seat_roster(cn, renamed):
    rec_member.put_office(cn, "r722o-plain")
    assert _one(cn, "SELECT COUNT(*) FROM member m JOIN name d ON d.id = m.desk_id"
                    " WHERE m.name_id = 1 AND d.name = 'r722o-plain'") == 1
    assert rpc._seat_roster(cn, "r722o-plain") == NEW
    assert rpc._connect_roster(cn, "r722o-plain", "Office") == NEW
    assert rpc._project_alias(cn, "Office") == NEW
    assert rpc._project_alias(cn, "the-mill") == "the-mill"
    assert rpc._live_projects(cn)[0] == NEW


@pytest.mark.parametrize("spelling", ("Office", NEW))
def test_seat_roster_refuses_office_by_either_name(cn, renamed, spelling):
    from agent_coord.helpers.errors import CoordError

    with pytest.raises(CoordError) as ei:
        resolve_seat_roster(cn, "r722o-plain", spelling)
    assert "Office is not a seat roster" in str(ei.value)


def test_score_procs_find_office_by_id(cn, renamed):
    rec_score.admin_upsert(cn, "r722o.kpi", "1", "0", "note")
    assert _one(cn, "SELECT COUNT(*) FROM score WHERE roster_id = 1 AND desk_id IS NULL"
                    " AND kpi = 'r722o.kpi'") == 1
    call(cn, "mill_wall_event", ["r722o-route", 5, None])
    assert _one(cn, "SELECT COUNT(*) FROM score WHERE roster_id = 1 AND desk_id IS NULL"
                    " AND kpi = 'wall'") == 1
    call(cn, "mill_score_event", ["r722o-plain", "todo", 5, 1, 1, None])
    assert _one(cn, "SELECT COUNT(*) FROM score s JOIN name d ON d.id = s.desk_id"
                    " WHERE s.roster_id = 1 AND d.name = 'r722o-plain' AND s.kpi = 'system'") == 1


def test_rename_back_to_office(cn, renamed):
    rec_name.rename(cn, NEW, "Office", "roster", by=admin_desk(cn))
    assert office_name(cn) == "Office"
    rec_name.rename(cn, "Office", NEW, "roster", by=admin_desk(cn))
    assert office_name(cn) == NEW
