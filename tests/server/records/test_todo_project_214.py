"""create todo refuses a project that is not already a project (#214)."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.sql

from agent_coord.helpers.errors import CoordError
from agent_coord.server.api.mill import rpc
from agent_coord.server.records import name as rec_name
from agent_coord.server.records import todo as rec_todo
from agent_coord.server.records import tree as rec_tree
from tests.server.records.conftest import seed_names


class _Book:
    def __init__(self, cn):
        self._cn = cn


def test_create_todo_requires_an_existing_project(cn) -> None:
    seed_names(cn, ("unit", "roster"), ("a", "desk"), ("b", "desk"))
    book = _Book(cn)

    made = rpc._h_open(book, {"need": "stays"}, "unit", "a")
    assert int(made["id"]) > 0
    assert rec_todo.find(cn, "unit", "stays") is not None

    with pytest.raises(CoordError, match="no roster nosuch"):
        rpc._h_open(book, {"need": "lost"}, "nosuch", "a")
    assert rec_name.get(cn, "nosuch", "roster") is None
    assert rec_todo.find(cn, "nosuch", "lost") is None

    root = rpc._h_open(book, {"need": "plan-root"}, "unit", "a")
    rec_tree.create(cn, "plan-214", "todo", int(root["id"]))
    with pytest.raises(CoordError, match="plan-214 is a tree, not a roster"):
        rpc._h_open(book, {"need": "on-plan"}, "plan-214", "a")
    assert rec_name.get(cn, "plan-214", "roster") is None

    rpc._h_send(
        book,
        {"src": "a", "dst": "b", "body": "room root", "name": "room-214"},
        "unit",
        "a",
    )
    with pytest.raises(CoordError, match="room-214 is a room, not a roster"):
        rpc._h_open(book, {"need": "on-room"}, "room-214", "a")
    assert rec_name.get(cn, "room-214", "roster") is None

    seed_names(cn, ("reviewers", "roster"))
    role_card = rpc._h_open(book, {"need": "n1"}, "reviewers", "a")
    assert int(role_card["id"]) > 0
    hit = rec_todo.find(cn, "reviewers", "n1")
    assert hit is not None
    assert str(hit.get("roster_type") or "") == "roster"

    again = rpc._h_open(book, {"need": "stays-too"}, "unit", "a")
    assert int(again["id"]) > 0
