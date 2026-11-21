"""watch and unwatch a hold by its resource name on a real book (#327)."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.sql

from agent_coord.server.api.mill import rpc
from agent_coord.server.records.db import scalar
from tests.server.records.conftest import seed_names


class _Book:
    def __init__(self, cn):
        self._cn = cn


def test_watch_hold_by_name_then_unwatch(cn) -> None:
    seed_names(cn, ("unit", "roster"), ("c327-w3", "desk"), ("c327-w1", "desk"))
    book = _Book(cn)
    took = rpc._h_hold(book, {"kh": "0" * 64, "resource": "c327-deploy"}, "unit", "c327-w3")
    hid = int(took["id"])
    assert rpc._card_ref_id(cn, {"type": "hold", "ref": "c327-deploy"}, "add") == hid

    w0 = scalar(cn, "SELECT COUNT(*) FROM watcher")
    body = {"verb": "add", "type": "hold", "ref": "c327-deploy"}
    rpc._h_add_remove(book, body, "unit", "c327-w1")
    assert scalar(cn, "SELECT COUNT(*) FROM watcher") == w0 + 1
    rpc._h_add_remove(book, dict(body, verb="remove"), "unit", "c327-w1")
    assert scalar(cn, "SELECT COUNT(*) FROM watcher") == w0
