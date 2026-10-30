"""#537 on a real book: a label that shares its desk's name retires alone. Regression row F60 (name-type)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from agent_coord.helpers.errors import CoordError
from agent_coord.server.admin import catalog
from agent_coord.server.records.db import rows_done
from tests.server.records.conftest import seed_names
from tests.server.records.conftest import admin_desk

pytestmark = pytest.mark.sql


def _live(cn, name):
    return sorted(r["type"] for r in rows_done(cn, "SELECT type FROM name WHERE name=%s AND deleted IS NULL", (name,)))


@pytest.fixture(autouse=True)
def _admin():
    with patch("agent_coord.server.admin.catalog.require_admin", lambda cn, desk: None):
        yield


def test_shared_name_without_a_type_is_refused_not_an_unread_result(cn):
    seed_names(cn, ("fx537-d1", "desk"), ("fx537-d1", "label"))
    with pytest.raises(CoordError) as e:
        catalog.retire(cn, admin_desk(cn, "admin-desk"), {"slug": "fx537-d1", "confirm": "fx537-d1", "yes": True})
    assert "desk" in str(e.value) and "label" in str(e.value)
    assert _live(cn, "fx537-d1") == ["desk", "label"]


def test_retire_label_keeps_the_desk(cn):
    seed_names(cn, ("fx537-d2", "desk"), ("fx537-d2", "label"))
    catalog.retire(cn, admin_desk(cn, "admin-desk"), {"slug": "fx537-d2", "confirm": "fx537-d2", "yes": True, "name_type": "label"})
    assert _live(cn, "fx537-d2") == ["desk"]
