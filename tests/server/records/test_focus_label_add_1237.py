"""Card 1237: label-add refuses a name another type already holds.

The error names that type (card 1254). An unknown name still follows the mint rules.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

pytestmark = pytest.mark.sql

from agent_coord.helpers.errors import CoordError
from agent_coord.server.api.mill import rpc
from agent_coord.server.records import name as rec_name
from agent_coord.server.records import todo as rec_todo
from tests.server.records.conftest import seed_names


class _Book:
    def __init__(self, cn):
        self._cn = cn


def _names(tag: str) -> tuple[str, str]:
    return f"r1237{tag}", f"d1237{tag}"


def _label_add(cn, home: str, by: str, tid: int, label: str, ord=None):
    body = {"verb": "label-add", "type": "todo", "id": tid, "label": label}
    if ord is not None:
        body["ord"] = ord
    return rpc._h_label(_Book(cn), body, home, by)


@pytest.mark.parametrize("trust", ["high", "limited"])
def test_desk_name_is_refused(cn, monkeypatch, trust) -> None:
    monkeypatch.setenv("AGENT_COORD_TRUST", trust)
    home, desk = _names(uuid4().hex[:6])
    seed_names(cn, (home, "roster"), (desk, "desk"))
    tid = int(rec_todo.insert(cn, home, desk, "open", "first")[0]["id"])
    with pytest.raises(CoordError, match="name in use: %s is a desk; pick another name" % desk):
        _label_add(cn, home, desk, tid, desk, 1)
    assert rec_name.get(cn, desk, "label") is None
    assert rec_name.get(cn, desk + "-1", "label") is None
    assert rec_name.get(cn, desk, "desk") is not None


def test_unknown_non_desk_name_still_mints_when_catalog_open(cn, monkeypatch) -> None:
    monkeypatch.setenv("AGENT_COORD_TRUST", "high")
    home, desk = _names(uuid4().hex[:6])
    fresh = "l1237" + uuid4().hex[:6]
    seed_names(cn, (home, "roster"), (desk, "desk"))
    tid = int(rec_todo.insert(cn, home, desk, "open", "mint")[0]["id"])
    _label_add(cn, home, desk, tid, fresh, 3)
    assert rec_name.get(cn, fresh, "label") is not None


def test_unknown_non_desk_name_still_refused_when_catalog_closed(cn, monkeypatch) -> None:
    monkeypatch.setenv("AGENT_COORD_TRUST", "limited")
    home, desk = _names(uuid4().hex[:6])
    fresh = "l1237" + uuid4().hex[:6]
    seed_names(cn, (home, "roster"), (desk, "desk"))
    tid = int(rec_todo.insert(cn, home, desk, "open", "closed")[0]["id"])
    with pytest.raises(CoordError, match="mill create label " + fresh):
        _label_add(cn, home, desk, tid, fresh)
    assert rec_name.get(cn, fresh, "label") is None
