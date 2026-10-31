"""Card 879 / F210: mill delete hard-removes an unreferenced roster, label or tree."""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.sql

from agent_coord.helpers.errors import CoordError
from agent_coord.server.records import apply, connect
from agent_coord.server.records import member as rec_member
from agent_coord.server.records import name as rec_name
from agent_coord.server.records.db import conn_kwargs as _conn_kwargs
from tests.server.records.conftest import admin_desk
from tests.sql_isolate import throwaway_db

TEST_DB = throwaway_db("mill_delete_879")


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


def _desk(cn, name: str) -> int:
    return rec_name.get_or_insert(cn, name, "desk")


def test_sole_member_deletes_empty_roster(cn) -> None:
    """SPIN-adjacent card 879: sole member (creator stand-in) hard-deletes an empty roster."""
    d = _desk(cn, "d879a")
    rid = rec_name.get_or_insert(cn, "r879-empty", "roster")
    rec_member.put(cn, "r879-empty", "d879a")
    out = rec_name.hard_delete(cn, "r879-empty", "roster", by="d879a")
    assert out["op"] == "deleted" and out["id"] == rid
    assert rec_name.get(cn, "r879-empty", "roster") is None


def test_referenced_roster_points_at_retire(cn) -> None:
    admin = admin_desk(cn)
    _desk(cn, "d879b")
    _desk(cn, "d879c")
    rid = rec_name.get_or_insert(cn, "r879-card", "roster")
    rec_member.put(cn, "r879-card", "d879b")
    rec_member.put(cn, "r879-card", "d879c")
    with pytest.raises(CoordError, match="retire"):
        rec_name.hard_delete(cn, "r879-card", "roster", by=admin)
    assert rec_name.get(cn, "r879-card", "roster") == rid


def test_office_and_admin_never_hard_delete(cn) -> None:
    admin = admin_desk(cn)
    with pytest.raises(CoordError, match="Office and Admin"):
        rec_name.hard_delete(cn, "Office", "roster", by=admin)


def test_unreferenced_label_deletes(cn) -> None:
    admin = admin_desk(cn)
    lid = rec_name.get_or_insert(cn, "l879", "label")
    out = rec_name.hard_delete(cn, "l879", "label", by=admin)
    assert out["op"] == "deleted" and out["id"] == lid
    assert rec_name.get(cn, "l879", "label") is None


def test_unreferenced_tree_deletes(cn) -> None:
    admin = admin_desk(cn)
    tid = rec_name.get_or_insert(cn, "t879", "tree")
    out = rec_name.hard_delete(cn, "t879", "tree", by=admin)
    assert out["op"] == "deleted" and out["id"] == tid
    assert rec_name.get(cn, "t879", "tree") is None


def test_desk_type_refused(cn) -> None:
    admin = admin_desk(cn)
    _desk(cn, "d879c")
    with pytest.raises(CoordError, match="retire"):
        rec_name.hard_delete(cn, "d879c", "desk", by=admin)
