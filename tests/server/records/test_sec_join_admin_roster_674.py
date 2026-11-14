# -*- coding: utf-8 -*-
"""Security: join never puts a desk on the reserved Admin roster (#674).

The Admin roster is granted only by member-add on the office host. A join
(open command, plain HTTP) that names Admin as its project or role, in any
spelling the case- and accent-insensitive name table resolves to Admin, is
refused with a clear error and writes no member row. Refusal is in SQL
(mill_join_upsert, authoritative) and in the join handler (clean CoordError).
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agent_coord.helpers.errors import CoordError
from agent_coord.server.admin.guard import ADMIN_ROSTER_ID, is_admin_roster, is_role_admin
from agent_coord.server.api.mill import rpc
from agent_coord.server.records import join as rec_join
from agent_coord.server.records.db import scalar
from tests.server.records.conftest import seed_names

pytestmark = pytest.mark.sql

ADMIN_SPELLINGS = ("Admin", "admin", "ADMIN", " Admin ", "\u00c1dmin", "adm\u00edn")


def _member_ids(cn, desk: str) -> list[int]:
    cur = cn.cursor()
    try:
        cur.execute(
            "SELECT m.name_id FROM member m JOIN name d ON d.id = m.desk_id"
            " WHERE d.type = 'desk' AND d.name = %s ORDER BY m.name_id",
            (desk,),
        )
        return [int(r[0]) for r in cur.fetchall()]
    finally:
        cur.close()


def _admin_n(cn) -> int:
    return int(scalar(cn, "SELECT n FROM name WHERE id = %s", (ADMIN_ROSTER_ID,)) or 0)


def test_admin_roster_is_id_2(cn):
    assert scalar(cn, "SELECT name FROM name WHERE id = %s AND type = 'roster'", (ADMIN_ROSTER_ID,)) == "Admin"


@pytest.mark.parametrize("spelling", ADMIN_SPELLINGS)
def test_is_admin_roster_resolves_every_spelling(cn, spelling):
    assert is_admin_roster(cn, spelling) is True


def test_is_admin_roster_false_for_other_rosters(cn):
    seed_names(cn, ("sec674-proj", "roster"))
    for name in ("sec674-proj", "Office", "the-mill", "admins", "", None):
        assert is_admin_roster(cn, name) is False


@pytest.mark.parametrize("spelling", ADMIN_SPELLINGS)
def test_join_handler_refuses_admin_project(cn, spelling):
    desk = "sec674-h%d" % ADMIN_SPELLINGS.index(spelling)
    before = _admin_n(cn)
    with pytest.raises(CoordError) as ei:
        rpc._issue_here(SimpleNamespace(_cn=cn), {"project": spelling, "owner": desk})
    assert "Admin" in str(ei.value) and "member-add on the office host" in str(ei.value)
    assert is_role_admin(cn, desk) is False
    assert ADMIN_ROSTER_ID not in _member_ids(cn, desk)
    assert _admin_n(cn) == before


@pytest.mark.parametrize("spelling", ("Admin", "admin", "\u00c1dmin"))
def test_join_handler_refuses_admin_role_any_spelling(cn, spelling):
    desk = "sec674-r%d" % ("Admin", "admin", "\u00c1dmin").index(spelling)
    with pytest.raises(CoordError) as ei:
        rpc._issue_here(
            SimpleNamespace(_cn=cn), {"project": "sec674-proj", "owner": desk, "role": spelling}
        )
    assert "member-add on the office host" in str(ei.value)
    assert is_role_admin(cn, desk) is False


@pytest.mark.parametrize("spelling", ADMIN_SPELLINGS)
def test_sql_join_upsert_refuses_admin_project(cn, spelling):
    """SQL is authoritative: a caller that skips the handler is still refused."""
    import mysql.connector

    desk = "sec674-s%d" % ADMIN_SPELLINGS.index(spelling)
    before = _admin_n(cn)
    with pytest.raises(mysql.connector.Error) as ei:
        rec_join.upsert(cn, spelling, desk, "", "a" * 64)
    assert "Admin is not granted by join" in str(ei.value)
    assert is_role_admin(cn, desk) is False
    assert _member_ids(cn, desk) == []  # rolled back: no Office row, no Admin row
    assert _admin_n(cn) == before


@pytest.mark.parametrize("spelling", ("Admin", "admin", "\u00c1dmin"))
def test_sql_join_upsert_refuses_admin_role(cn, spelling):
    import mysql.connector

    desk = "sec674-sr%d" % ("Admin", "admin", "\u00c1dmin").index(spelling)
    with pytest.raises(mysql.connector.Error) as ei:
        rec_join.upsert(cn, "sec674-proj", desk, spelling, "b" * 64)
    assert "Admin is not granted by join" in str(ei.value)
    assert is_role_admin(cn, desk) is False


def test_plain_join_still_works(cn):
    seed_names(cn, ("sec674-proj", "roster"))
    out = rpc._issue_here(SimpleNamespace(_cn=cn), {"project": "sec674-proj", "owner": "sec674-ok"})
    assert out["group_id"] == "sec674-proj" and out["token"]
    pid = int(scalar(cn, "SELECT id FROM name WHERE type='roster' AND name='sec674-proj'"))
    assert _member_ids(cn, "sec674-ok") == sorted([1, pid])
    assert is_role_admin(cn, "sec674-ok") is False


def test_admin_desk_placeholder_rejoin_keeps_office(cn):
    """A desk whose one non-Office roster is Admin rejoins on Office, not refused."""
    first = rpc._issue_here(SimpleNamespace(_cn=cn), {"project": "Office", "owner": "sec674-adm"})
    cur = cn.cursor()
    try:
        cur.execute(
            "INSERT IGNORE INTO member (name_id, desk_id)"
            " SELECT %s, id FROM name WHERE type='desk' AND name='sec674-adm'",
            (ADMIN_ROSTER_ID,),
        )
        cn.commit()
    finally:
        cur.close()
    out = rpc._issue_here(
        SimpleNamespace(_cn=cn),
        {"project": "Office", "owner": "sec674-adm", "placeholder": True, "token": first["token"]},
    )
    assert out["group_id"] == "Office"
    assert is_role_admin(cn, "sec674-adm") is True  # existing Admin is kept


@pytest.mark.parametrize("spelling", ("Admin", "admin"))
def test_seat_mint_refuses_admin_roster(cn, spelling):
    from agent_coord.server.admin.seats import mint_seat, resolve_seat_roster

    with pytest.raises(CoordError):
        resolve_seat_roster(cn, "sec674-inviter", spelling)
    import mysql.connector

    with pytest.raises((CoordError, mysql.connector.Error)):
        mint_seat(cn, desk="sec674-seat", project=spelling)
    assert is_role_admin(cn, "sec674-seat") is False


def test_handler_refuses_before_upsert_unit():
    """No book needed: the handler refuses a casefold Admin before any write."""
    c = MagicMock()
    with patch("agent_coord.server.records.join.upsert") as up:
        for spelling in ("Admin", "admin", "ADMIN"):
            with pytest.raises(CoordError):
                rpc._issue_here(c, {"project": spelling, "owner": "x674"})
    up.assert_not_called()
