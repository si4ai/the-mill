"""create todo on a ROSTER/NEED that already exists is refused and changes nothing (card 775).

Before: a second `mill create todo R N --detail X` returned ok with the same id,
put the card back to open and replaced its detail (a done or claimed card lost
its status, its volunteer's work and its notes). Now it exits 1 naming the card
and the commands that do change it; status, detail and volunteer stay.

Regression row F130 (create-todo-exists).
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.sql

from agent_coord.helpers.errors import CoordError
from agent_coord.server.api.mill import rpc
from agent_coord.server.records import todo as rec_todo
from agent_coord.server.records import tree as rec_tree
from tests.server.records.conftest import seed_names


class _Book:
    def __init__(self, cn):
        self._cn = cn


def _card(cn, need):
    hit = rec_todo.find(cn, "unit", need)
    fields = rec_todo.unpack(hit.get("body") or "", hit.get("id"))
    return int(hit["id"]), str(hit.get("status")), fields["detail"]


@pytest.mark.parametrize("move", ["open", "parked", "claimed", "done"])
def test_second_create_is_refused_and_keeps_the_card(cn, move) -> None:
    seed_names(cn, ("unit", "roster"), ("a", "desk"), ("b", "desk"))
    book = _Book(cn)
    need = f"c775-{move}"
    first = rpc._h_open(book, {"need": need, "detail": "original text",
                               "status": "parked" if move == "parked" else ""}, "unit", "a")
    if move in ("claimed", "done"):
        rpc._h_claim(book, {"need": need}, "unit", "b")
    if move == "done":
        rpc._h_pass(book, {"need": need}, "unit", "b")
        rpc._h_pass(book, {"need": need, "step": "done"}, "unit", "a")
    before = _card(cn, need)
    with pytest.raises(CoordError) as err:
        rpc._h_open(book, {"need": need, "detail": "dup"}, "unit", "a")
    text = str(err.value)
    assert f"create todo: unit/{need} exists (id {first['id']}, {before[1]})" in text
    assert f"mill note unit {need} --note TEXT" in text
    assert _card(cn, need) == before
    assert before[2] == "original text"


def test_second_create_with_a_parent_is_refused_and_attaches_nothing(cn) -> None:
    seed_names(cn, ("unit", "roster"), ("a", "desk"))
    book = _Book(cn)
    parent = rpc._h_open(book, {"need": "c775-parent"}, "unit", "a")
    child = rpc._h_open(book, {"need": "c775-child", "detail": "kept"}, "unit", "a")
    with pytest.raises(CoordError, match=r"mill attach unit todo %d todo %d" % (parent["id"], child["id"])):
        rpc._h_open(book, {"need": "c775-child", "parent_type": "todo", "parent_id": parent["id"]},
                    "unit", "a")
    assert not rec_tree.has_parent(cn, "todo", child["id"])
    assert _card(cn, "c775-child")[2] == "kept"
