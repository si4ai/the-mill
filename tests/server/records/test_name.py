"""N1-N4 names: create / rename / retire / reclaim. Throwaway mill_records_test.

Use cases: docs/protocol/usecases.md Names chart.

SPIN N1 SPIN N2 SPIN N4 SPIN JOIN_RETIRED: retire, reclaim, join-after-retire refuse.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.sql

from agent_coord.server.records.db import conn_kwargs as _conn_kwargs
from agent_coord.server.records import name as rec_name

from tests.server.records.conftest import admin_desk

def test_n4_office_seed_rename_ok_never_retire_reclaim(cn) -> None:
    """N4: Office is id 1. Host may rename. Never retire / reclaim."""
    assert rec_name.get(cn, "Office", "roster") == 1
    rec_name.rename(cn, "Office", "East-Office", "roster", by=admin_desk(cn))
    assert rec_name.get(cn, "East-Office", "roster") == 1
    rec_name.rename(cn, "East-Office", "Office", "roster", by=admin_desk(cn))
    with pytest.raises(Exception, match="Office"):
        rec_name.retire(cn, "Office", "roster", by=admin_desk(cn))
    with pytest.raises(Exception, match="seed|Office"):
        rec_name.reclaim(cn, "Office", "roster", by=admin_desk(cn))

def test_n1_desk_create_rename_retire_no_reuse_reclaim(cn) -> None:
    """N1: mill_name DESK_ first use; rename string; retire holds unique; mill_name warns; reclaim same id."""
    a = rec_name.get_or_insert(cn, "alice", "desk")
    rec_name.rename(cn, "alice", "alice2", "desk", by=admin_desk(cn))
    assert rec_name.get(cn, "alice", "desk") is None
    assert rec_name.get(cn, "alice2", "desk") == a
    rec_name.retire(cn, "alice2", "desk", by=admin_desk(cn))
    with pytest.raises(Exception, match="retired"):
        rec_name.get_or_insert(cn, "alice2", "desk")
    rec_name.reclaim(cn, "alice2", "desk", by=admin_desk(cn))
    assert rec_name.get_or_insert(cn, "alice2", "desk") == a

def test_n2_group_first_use_and_rename_conflict(cn) -> None:
    """N2: mill member-add first use = mill_name PROJ_. Rename conflict if slug live."""
    g = rec_name.get_or_insert(cn, "east", "roster")
    rec_name.get_or_insert(cn, "west", "roster")
    with pytest.raises(Exception, match="in use"):
        rec_name.rename(cn, "east", "west", "roster", by=admin_desk(cn))
    rec_name.rename(cn, "east", "east-coast", "roster", by=admin_desk(cn))
    assert rec_name.get(cn, "east-coast", "roster") == g

def test_n3_role_first_use_retire_reclaim(cn) -> None:
    """N3: mill here --role first use = mill_name ROLE_. Retire then reclaim."""
    r = rec_name.get_or_insert(cn, "builder", "roster")
    rec_name.retire(cn, "builder", "roster", by=admin_desk(cn))
    with pytest.raises(Exception, match="retired"):
        rec_name.get_or_insert(cn, "builder", "roster")
    rec_name.reclaim(cn, "builder", "roster", by=admin_desk(cn))
    assert rec_name.get(cn, "builder", "roster") == r

def test_reclaim_live_name_refused(cn) -> None:
    """Reclaim is dangerous: live names cannot reclaim."""
    rec_name.get_or_insert(cn, "bob", "desk")
    with pytest.raises(Exception, match="live"):
        rec_name.reclaim(cn, "bob", "desk", by=admin_desk(cn))
