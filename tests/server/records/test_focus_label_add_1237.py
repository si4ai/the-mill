"""Card 1237: label-add with a desk name ranks that desk's focus list (card 1163).

A desk-named label is the desk's focus list and has no label-type name, so the
first-use mint must not run for it: b_name_mint refuses a name a desk holds
('name in use'). Unknown names that are not desks keep the mint rules.
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


def _names(tag: str) -> tuple[str, str, str]:
    return f"r1237{tag}", f"d1237{tag}", f"o1237{tag}"


def _label_add(cn, home: str, by: str, tid: int, label: str, ord=None):
    body = {"verb": "label-add", "type": "todo", "id": tid, "label": label}
    if ord is not None:
        body["ord"] = ord
    return rpc._h_label(_Book(cn), body, home, by)


def _trail(cn, home: str, by: str, label: str) -> list[tuple[int, int]]:
    got = rpc._h_trail(_Book(cn), {"label": label}, home, by)
    return [(int(r["id"]), int(r["ord"])) for r in got["rows"]]


@pytest.mark.parametrize("trust", ["high", "limited"])
def test_desk_name_adds_and_reranks_without_minting(cn, monkeypatch, trust) -> None:
    monkeypatch.setenv("AGENT_COORD_TRUST", trust)
    home, desk, other = _names(uuid4().hex[:6])
    seed_names(cn, (home, "roster"), (desk, "desk"), (other, "desk"))
    first = int(rec_todo.insert(cn, home, desk, "open", "first")[0]["id"])
    second = int(rec_todo.insert(cn, home, desk, "open", "second")[0]["id"])

    # A new card on the list, by the desk itself and by another desk.
    got = _label_add(cn, home, desk, first, desk, 1)
    assert [int(r["ord"]) for r in got] == [1]
    got = _label_add(cn, home, other, second, desk)
    assert [int(r["ord"]) for r in got] == [65535]
    assert _trail(cn, home, desk, desk) == [(first, 1), (second, 65535)]

    # A card already on the list: re-label changes its ord, shown in the JSON.
    got = _label_add(cn, home, desk, second, desk, 0)
    assert [int(r["ord"]) for r in got] == [0]
    assert _trail(cn, home, desk, desk) == [(second, 0), (first, 1)]
    got = _label_add(cn, home, other, first, desk, 65535)
    assert [int(r["ord"]) for r in got] == [65535]
    assert _trail(cn, home, desk, desk) == [(second, 0), (first, 65535)]

    # No label-type name was minted with the desk's bare string.
    assert rec_name.get(cn, desk, "label") is None
    assert rec_name.get(cn, desk, "desk") is not None


def test_unknown_non_desk_name_still_mints_when_catalog_open(cn, monkeypatch) -> None:
    monkeypatch.setenv("AGENT_COORD_TRUST", "high")
    home, desk, _ = _names(uuid4().hex[:6])
    fresh = "l1237" + uuid4().hex[:6]
    seed_names(cn, (home, "roster"), (desk, "desk"))
    tid = int(rec_todo.insert(cn, home, desk, "open", "mint")[0]["id"])
    _label_add(cn, home, desk, tid, fresh, 3)
    assert rec_name.get(cn, fresh, "label") is not None
    assert _trail(cn, home, desk, fresh) == [(tid, 3)]


def test_unknown_non_desk_name_still_refused_when_catalog_closed(cn, monkeypatch) -> None:
    monkeypatch.setenv("AGENT_COORD_TRUST", "limited")
    home, desk, _ = _names(uuid4().hex[:6])
    fresh = "l1237" + uuid4().hex[:6]
    seed_names(cn, (home, "roster"), (desk, "desk"))
    tid = int(rec_todo.insert(cn, home, desk, "open", "closed")[0]["id"])
    with pytest.raises(CoordError, match="mill create label " + fresh):
        _label_add(cn, home, desk, tid, fresh)
    assert rec_name.get(cn, fresh, "label") is None
