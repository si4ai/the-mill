"""Create-todo with a parent commits the card and the tree row together (#146).

The procedure is not executed against a live book. The retry is mocked.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import agent_coord.server.push as push
import agent_coord.server.records.name as rec_name
import agent_coord.server.records.todo as rec_todo
import agent_coord.server.records.tree as rec_tree
from agent_coord.helpers.errors import CoordError
from agent_coord.server.api.mill.rpc import _h_open


class Dup(Exception):
    def __init__(self, msg: str = "Duplicate entry '62-todo-24' for key 'tree.PRIMARY'") -> None:
        super().__init__(msg)
        self.errno = 1062


class Other(Exception):
    errno = 1048


def _procedure() -> str:
    blob = Path("agent_coord/server/sql/sp_todo.sql").read_text(encoding="utf-8")
    start = blob.index("CREATE PROCEDURE mill_todo_insert_attached")
    end = blob.index("END //", start)
    return blob[start:end]


def test_attached_procedure_is_one_transaction() -> None:
    body = _procedure()
    assert body.count("START TRANSACTION") == 1
    assert body.count("COMMIT") == 1
    assert "ROLLBACK" in body
    assert "mill_tree_add" not in body
    assert body.index("INSERT INTO todo") < body.index("INSERT INTO tree")
    assert body.index("FOR UPDATE") < body.index("COUNT(DISTINCT name_id)")


def test_insert_attached_retries_duplicate_then_returns(monkeypatch) -> None:
    calls = {"n": 0}

    def fake_call(cn, name, args):
        calls["n"] += 1
        assert name == "mill_todo_insert_attached"
        assert args[4] == "mail"
        assert args[5] == 51
        if calls["n"] < 3:
            raise Dup()
        return [{"id": 25}]

    monkeypatch.setattr(rec_todo, "call", fake_call)
    rows = rec_todo.insert_attached(object(), "the-mill", "grok-tui", "open", "{}", "mail", 51)
    assert rows == [{"id": 25}]
    assert calls["n"] == 3


def test_insert_attached_stops_after_three_duplicates(monkeypatch) -> None:
    calls = {"n": 0}

    def fake_call(cn, name, args):
        calls["n"] += 1
        raise Dup()

    monkeypatch.setattr(rec_todo, "call", fake_call)
    with pytest.raises(Dup):
        rec_todo.insert_attached(object(), "the-mill", "grok-tui", "open", "{}", "mail", 51)
    assert calls["n"] == 3


def test_insert_attached_does_not_retry_other_errors(monkeypatch) -> None:
    calls = {"n": 0}

    def fake_call(cn, name, args):
        calls["n"] += 1
        raise Other("bad column")

    monkeypatch.setattr(rec_todo, "call", fake_call)
    with pytest.raises(Other):
        rec_todo.insert_attached(object(), "the-mill", "grok-tui", "open", "{}", "mail", 51)
    assert calls["n"] == 1


class _Book:
    _cn = object()


def _silence(monkeypatch) -> None:
    monkeypatch.setattr(rec_name, "ensure_roster", lambda *a, **k: None)
    monkeypatch.setattr(rec_name, "get", lambda *a, **k: 1)
    monkeypatch.setattr(push, "fanout", lambda *a, **k: None)


def test_open_new_card_with_parent_does_not_add_after(monkeypatch) -> None:
    _silence(monkeypatch)
    monkeypatch.setattr(rec_todo, "find", lambda *a, **k: None)
    monkeypatch.setattr(rec_todo, "find_retired", lambda *a, **k: None)
    seen: dict[str, tuple] = {}

    def attached(*args):
        seen["attached"] = args
        return [{"id": 25}]

    monkeypatch.setattr(rec_todo, "insert_attached", attached)
    monkeypatch.setattr(
        rec_todo, "insert", lambda *a, **k: (_ for _ in ()).throw(AssertionError("insert"))
    )
    monkeypatch.setattr(
        rec_tree, "add", lambda *a, **k: (_ for _ in ()).throw(AssertionError("tree.add"))
    )
    rec = _h_open(
        _Book(),
        {"need": "f1327-create-todo-race", "parent_type": "mail", "parent_id": 51},
        "the-mill",
        "grok-tui",
    )
    assert rec["id"] == 25
    assert seen["attached"][5] == "mail"
    assert seen["attached"][6] == 51


def test_open_existing_card_is_refused_and_attaches_nothing(monkeypatch) -> None:
    """Card 775: create on an existing card refuses; attach is its own command."""
    _silence(monkeypatch)
    monkeypatch.setattr(rec_todo, "find", lambda *a, **k: {"id": 24, "status": "claimed"})
    monkeypatch.setattr(
        rec_todo, "update", lambda *a, **k: (_ for _ in ()).throw(AssertionError("update"))
    )
    monkeypatch.setattr(
        rec_todo,
        "insert_attached",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("attached")),
    )
    monkeypatch.setattr(
        rec_tree, "add", lambda *a, **k: (_ for _ in ()).throw(AssertionError("tree.add"))
    )
    with pytest.raises(CoordError, match=r"exists \(id 24, claimed\).*mill attach the-mill mail 51 todo 24"):
        _h_open(
            _Book(),
            {"need": "f1327-create-todo-race", "parent_type": "mail", "parent_id": 51},
            "the-mill",
            "grok-tui",
        )


def test_open_without_parent_stays_a_plain_insert(monkeypatch) -> None:
    _silence(monkeypatch)
    monkeypatch.setattr(rec_todo, "find", lambda *a, **k: None)
    monkeypatch.setattr(rec_todo, "find_retired", lambda *a, **k: None)
    monkeypatch.setattr(rec_todo, "insert", lambda *a, **k: [{"id": 8}])
    monkeypatch.setattr(
        rec_todo,
        "insert_attached",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("attached")),
    )
    rec = _h_open(_Book(), {"need": "plain-card"}, "the-mill", "grok-tui")
    assert rec["id"] == 8
