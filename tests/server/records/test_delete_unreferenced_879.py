"""Card 879 / F210: mill delete trashes; restore undoes; purge hard-deletes trashed rows only."""
from __future__ import annotations

import os

import mysql.connector
import pytest

pytestmark = pytest.mark.sql

from agent_coord.helpers.errors import CoordError
from agent_coord.server.records import apply, connect
from agent_coord.server.records import member as rec_member
from agent_coord.server.records import name as rec_name
from agent_coord.server.records.db import conn_kwargs as _conn_kwargs, scalar_done
from tests.server.records.conftest import admin_desk
from tests.sql_isolate import throwaway_db

TEST_DB = throwaway_db("mill_delete_879")


def _cn():
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
    # Drop pooled connections that may still point at another database.
    import agent_coord.server.records.db as db

    db._POOL = None
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


def _seat(cn, name: str) -> str:
    """Seated desk (sp_name_* and purge auth expect a live seat)."""
    from agent_coord.client.tokens import token_hash
    from agent_coord.server.records import join as rec_join

    rec_join.upsert(cn, "Office", name, "", token_hash("seat-" + name), None)
    return name


def _trashed(cn, kind: str, name: str):
    return scalar_done(
        cn,
        "SELECT trashed IS NOT NULL FROM name WHERE type=%s AND name=%s",
        (kind, name),
    )


def test_delete_trashes_roster_and_hides_from_get(cn) -> None:
    d = _seat(cn, "d879a")
    rid = rec_name.get_or_insert(cn, "r879-empty", "roster")
    rec_member.put(cn, "r879-empty", "d879a")
    out = rec_name.trash(cn, "r879-empty", "roster", by=d)
    assert out["op"] == "deleted" and out["id"] == rid
    assert _trashed(cn, "roster", "r879-empty") in (1, True)
    assert rec_name.get(cn, "r879-empty", "roster") is None


def test_restore_clears_trash(cn) -> None:
    admin = admin_desk(cn)
    lid = rec_name.get_or_insert(cn, "l879-rest", "label")
    rec_name.trash(cn, "l879-rest", "label", by=admin)
    assert rec_name.get(cn, "l879-rest", "label") is None
    out = rec_name.restore_trashed(cn, "l879-rest", "label", by=admin)
    assert out["op"] == "restored" and out["id"] == lid
    assert rec_name.get(cn, "l879-rest", "label") == lid
    assert _trashed(cn, "label", "l879-rest") in (0, False, None)


def test_purge_refuses_live_not_trashed(cn) -> None:
    admin = admin_desk(cn)
    rec_name.get_or_insert(cn, "l879-live", "label")
    with pytest.raises(CoordError, match="trashed|delete first"):
        rec_name.purge_trashed(cn, "l879-live", "label", by=admin)
    assert rec_name.get(cn, "l879-live", "label") is not None


def test_purge_hard_deletes_trashed_unreferenced(cn) -> None:
    admin = admin_desk(cn)
    tid = rec_name.get_or_insert(cn, "t879-purge", "tree")
    rec_name.trash(cn, "t879-purge", "tree", by=admin)
    out = rec_name.purge_trashed(cn, "t879-purge", "tree", by=admin)
    assert out["op"] == "purged" and out["id"] == tid
    row = scalar_done(cn, "SELECT COUNT(*) FROM name WHERE type='tree' AND name='t879-purge'")
    assert int(row or 0) == 0


def test_purge_refuses_referenced_trashed_roster(cn) -> None:
    admin = admin_desk(cn)
    _seat(cn, "d879b")
    _seat(cn, "d879c")
    rid = rec_name.get_or_insert(cn, "r879-card", "roster")
    rec_member.put(cn, "r879-card", "d879b")
    rec_member.put(cn, "r879-card", "d879c")
    rec_name.trash(cn, "r879-card", "roster", by=admin)
    with pytest.raises(CoordError, match="retire|referenced|members"):
        rec_name.purge_trashed(cn, "r879-card", "roster", by=admin)
    assert scalar_done(cn, "SELECT id FROM name WHERE type='roster' AND name='r879-card'") == rid


def test_office_and_admin_never_purge(cn) -> None:
    admin = admin_desk(cn)
    with pytest.raises(CoordError, match="Office and Admin"):
        rec_name.trash(cn, "Office", "roster", by=admin)
    with pytest.raises(CoordError, match="Office and Admin|desk|retire"):
        rec_name.purge_trashed(cn, "Office", "roster", by=admin)


def test_desk_type_refused_for_delete_restore_purge(cn) -> None:
    admin = admin_desk(cn)
    _seat(cn, "d879desk")
    with pytest.raises(CoordError, match="retire"):
        rec_name.trash(cn, "d879desk", "desk", by=admin)
    with pytest.raises(CoordError, match="retire"):
        rec_name.restore_trashed(cn, "d879desk", "desk", by=admin)
    with pytest.raises(CoordError, match="retire"):
        rec_name.purge_trashed(cn, "d879desk", "desk", by=admin)


def test_raw_delete_refused_without_session_flag(cn) -> None:
    """name_no_delete still blocks a bare DELETE even for a roster row."""
    admin = admin_desk(cn)
    rid = rec_name.get_or_insert(cn, "r879-raw", "roster")
    cur = cn.cursor()
    with pytest.raises(mysql.connector.Error, match="retire only|DELETE refused"):
        cur.execute("DELETE FROM name WHERE id=%s", (int(rid),))
    cur.close()
    try:
        cn.rollback()
    except Exception:
        pass
    assert rec_name.get(cn, "r879-raw", "roster") == rid


def test_session_flag_still_refuses_desk_hard_delete(cn) -> None:
    admin = admin_desk(cn)
    did = rec_name.get(cn, "d879desk", "desk") or rec_name.get_or_insert(cn, "d879desk2", "desk")
    _seat(cn, "d879desk2")
    did = rec_name.get(cn, "d879desk2", "desk")
    cur = cn.cursor()
    cur.execute("SET @mill_allow_name_hard_delete = 1")
    with pytest.raises(mysql.connector.Error, match="retire only|DELETE refused"):
        cur.execute("DELETE FROM name WHERE id=%s AND type='desk'", (int(did),))
    cur.execute("SET @mill_allow_name_hard_delete = NULL")
    cur.close()
    try:
        cn.rollback()
    except Exception:
        pass


def test_human_member_blocks_purge(cn) -> None:
    """Purge must count human_member as a reference (Validator major on #256)."""
    admin = admin_desk(cn)
    rid = rec_name.get_or_insert(cn, "r879-hm", "roster")
    # Insert a human + human_member if the book has those tables.
    cur = cn.cursor()
    try:
        cur.execute(
            "INSERT INTO human (bearer_hash) VALUES (%s)",
            ("h" * 64,),
        )
        hid = cur.lastrowid
        cur.execute(
            "INSERT INTO human_member (human_id, name_id, name_kind) VALUES (%s,%s,'roster')",
            (hid, int(rid)),
        )
        cn.commit()
    except mysql.connector.Error as e:
        cur.close()
        pytest.skip(f"human_member shape: {e}")
    cur.close()
    rec_name.trash(cn, "r879-hm", "roster", by=admin)
    with pytest.raises(CoordError, match="human|referenced|retire"):
        rec_name.purge_trashed(cn, "r879-hm", "roster", by=admin)


def test_delete_restore_purge_write_timeline_acts(cn) -> None:
    admin = admin_desk(cn)
    rec_name.get_or_insert(cn, "l879-act", "label")
    rec_name.trash(cn, "l879-act", "label", by=admin)
    rec_name.restore_trashed(cn, "l879-act", "label", by=admin)
    rec_name.trash(cn, "l879-act", "label", by=admin)
    rec_name.purge_trashed(cn, "l879-act", "label", by=admin)
    acts = []
    cur = cn.cursor()
    cur.execute(
        "SELECT act FROM doing WHERE act IN ('delete','restore','purge') ORDER BY id"
    )
    acts = [r[0] for r in cur.fetchall()]
    cur.close()
    assert acts.count("delete") >= 2
    assert "restore" in acts
    assert "purge" in acts
