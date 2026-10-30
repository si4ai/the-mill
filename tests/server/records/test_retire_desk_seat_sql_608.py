"""#608 on a real book: retiring a desk ends its seat. Regression row F65 (retired-seat).

Seen live: a desk retired itself, yet its seat token still passed connect and
the desk sat as ready. Reset then refused (name retired) and reclaim refused
(seat live), so an Admin had no command that revoked the seat.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from agent_coord.client.tokens import token_hash
from agent_coord.server.admin import catalog
from agent_coord.server.records import join as rec_join
from agent_coord.server.records import name as rec_name
from agent_coord.server.records.db import rows_done, scalar_done
from tests.server.records.conftest import seed_names

pytestmark = pytest.mark.sql


@pytest.fixture(autouse=True)
def _admin():
    with patch("agent_coord.server.admin.catalog.require_admin", lambda cn, desk: None):
        yield


def _seat(cn, desk: str, seat: str) -> str:
    seed_names(cn, ("fx608", "roster"), (desk, "desk"))
    rec_join.upsert(cn, "fx608", desk, "", token_hash(seat), None)
    cn.commit()
    digest = token_hash(seat)
    assert rec_join.desk_for_token_hash(cn, digest) == desk
    assert rec_join.token_matches(cn, desk, digest)
    return digest


def _stored_hash(cn, desk: str):
    return scalar_done(
        cn,
        "SELECT j.token_hash FROM seat j JOIN name d ON d.id = j.desk_id"
        " WHERE d.type = 'desk' AND d.name = %s",
        (desk,),
    )


def test_self_retire_clears_the_seat(cn):
    digest = _seat(cn, "fx608-d1", "seat-608-d1")
    rec_name.retire(cn, "fx608-d1", "desk")
    cn.commit()
    assert _stored_hash(cn, "fx608-d1") is None
    assert rec_join.desk_for_token_hash(cn, digest) == ""
    assert not rec_join.token_matches(cn, "fx608-d1", digest)


def test_admin_retire_clears_the_seat(cn):
    digest = _seat(cn, "fx608-d2", "seat-608-d2")
    catalog.retire(cn, "admin-desk", {"slug": "fx608-d2", "confirm": "fx608-d2", "yes": True, "name_type": "desk"})
    cn.commit()
    assert _stored_hash(cn, "fx608-d2") is None
    assert not rec_join.token_matches(cn, "fx608-d2", digest)


def test_retiring_a_label_named_like_a_desk_keeps_the_seat(cn):
    digest = _seat(cn, "fx608-d3", "seat-608-d3")
    seed_names(cn, ("fx608-d3", "label"))
    catalog.retire(cn, "admin-desk", {"slug": "fx608-d3", "confirm": "fx608-d3", "yes": True, "name_type": "label"})
    cn.commit()
    assert rec_join.token_matches(cn, "fx608-d3", digest)


def _retired_with_leftover_seat(cn, desk: str, seat: str) -> str:
    """A desk retired before this fix: name.deleted set, token_hash still stored."""
    digest = _seat(cn, desk, seat)
    cur = cn.cursor()
    cur.execute("UPDATE name SET deleted = MILL_NOW() WHERE type = 'desk' AND name = %s", (desk,))
    cur.close()
    cn.commit()
    assert _stored_hash(cn, desk) == digest
    return digest


def test_a_leftover_seat_on_a_retired_desk_does_not_authenticate(cn):
    digest = _retired_with_leftover_seat(cn, "fx608-d4", "seat-608-d4")
    assert rec_join.desk_for_token_hash(cn, digest) == ""
    assert not rec_join.token_matches(cn, "fx608-d4", digest)


def test_reset_clears_a_retired_desk_seat_then_reclaim_works(cn):
    _retired_with_leftover_seat(cn, "fx608-d5", "seat-608-d5")
    rows = rec_join.reset(cn, "fx608", "fx608-d5")
    cn.commit()
    assert rows and rows[0].get("op") == "reset"
    assert _stored_hash(cn, "fx608-d5") is None
    catalog.reclaim(cn, "admin-desk", {"slug": "fx608-d5", "confirm": "fx608-d5", "yes": True, "name_type": "desk"})
    cn.commit()
    live = rows_done(cn, "SELECT id FROM name WHERE type='desk' AND name=%s AND deleted IS NULL", ("fx608-d5",))
    assert len(live) == 1


def test_reclaim_without_a_type_finds_the_retired_name(cn):
    seed_names(cn, ("fx608-d6", "desk"))
    rec_name.retire(cn, "fx608-d6", "desk")
    cn.commit()
    catalog.reclaim(cn, "admin-desk", {"slug": "fx608-d6", "confirm": "fx608-d6", "yes": True})
    cn.commit()
    live = rows_done(cn, "SELECT id FROM name WHERE type='desk' AND name=%s AND deleted IS NULL", ("fx608-d6",))
    assert len(live) == 1
