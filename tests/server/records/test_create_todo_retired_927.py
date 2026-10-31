"""create todo on a retired ROSTER/NEED is refused and inserts nothing (card 927).

Before: find skips retired cards, so create filed a second card on the same need.
After: find_retired in _h_open refuses and names mill reclaim todo ROSTER NEED.

Regression row F-create-todo-retired.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.sql

from agent_coord.helpers.errors import CoordError
from agent_coord.server.api.mill import rpc
from agent_coord.server.records import todo as rec_todo
from tests.server.records.conftest import seed_names


class _Book:
    def __init__(self, cn):
        self._cn = cn


def test_create_on_retired_need_is_refused_and_inserts_nothing(cn) -> None:
    seed_names(cn, ("unit", "roster"), ("a", "desk"))
    book = _Book(cn)
    need = "c927-stale"
    first = rpc._h_open(book, {"need": need, "detail": "kept"}, "unit", "a")
    tid = int(first["id"])
    rpc._h_retire(book, {"name_type": "todo", "need": need}, "unit", "a")
    assert rec_todo.find(cn, "unit", need) is None
    assert rec_todo.find_retired(cn, "unit", need) is not None
    with pytest.raises(CoordError) as err:
        rpc._h_open(book, {"need": need, "detail": "second card"}, "unit", "a")
    text = str(err.value)
    assert f"create todo: unit/{need} is retired (id {tid})" in text
    assert f"mill reclaim todo unit {need}" in text
    assert rec_todo.find(cn, "unit", need) is None
    hit = rec_todo.find_retired(cn, "unit", need)
    assert hit is not None and int(hit["id"]) == tid
    fields = rec_todo.unpack(hit.get("body") or "", hit.get("id"))
    assert fields["detail"] == "kept"
