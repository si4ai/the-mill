"""A card on two plans names them. --tree picks one (#225)."""
from __future__ import annotations

import pytest

from agent_coord.helpers.errors import CoordError
from agent_coord.server.api.mill import rpc
from agent_coord.server.records import name as rec_name
from agent_coord.server.records import todo
from agent_coord.server.records import tree as rec_tree


pytestmark = pytest.mark.sql


class _Book:
    def __init__(self, cn) -> None:
        self._cn = cn


def _move(cn, cid: int, pid: int, tree: str = ""):
    body = {
        "type": "todo",
        "id": cid,
        "parent_type": "todo",
        "parent_id": pid,
    }
    if tree:
        body["tree"] = tree
    return rpc._h_move(_Book(cn), body, "unit", "a")


def test_two_plans_name_the_plans_and_tree_picks_one(cn) -> None:
    rec_tree.delete(cn, "f17-plan-a")
    rec_tree.delete(cn, "f17-plan-b")
    rec_name.get_or_insert(cn, "unit", "roster")
    rec_name.get_or_insert(cn, "a", "desk")
    parent = todo.insert(cn, "unit", "a", "open", '{"slug":"f17-parent"}')
    child = todo.insert(cn, "unit", "a", "open", '{"slug":"f17-child"}')
    pid, cid = int(parent[0]["id"]), int(child[0]["id"])
    try:
        rec_tree.create(cn, "f17-plan-a", "todo", pid)
        rec_tree.add(cn, "todo", pid, "todo", cid, tree="f17-plan-a")
        rec_tree.create(cn, "f17-plan-b", "todo", cid)
        with pytest.raises(CoordError) as ei:
            _move(cn, cid, pid)
        msg = str(ei.value)
        assert "f17-plan-a" in msg
        assert "f17-plan-b" in msg
        assert "--tree picks one" in msg
        assert "1644" not in msg
        with pytest.raises(CoordError) as missed:
            _move(cn, cid, pid, "f17-plan-b")
        missed_msg = str(missed.value)
        assert "1644" not in missed_msg
        assert "parent" in missed_msg
        assert "f17-plan-b" in missed_msg
        moved = _move(cn, cid, pid, "f17-plan-a")
        assert moved
    finally:
        rec_tree.delete(cn, "f17-plan-a")
        rec_tree.delete(cn, "f17-plan-b")
        todo.delete(cn, pid, "a")
        todo.delete(cn, cid, "a")
