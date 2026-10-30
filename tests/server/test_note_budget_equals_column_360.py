"""The note budget is the card's stored column, from one constant, on every path (#360).

Regression row F56 (note-detail-budget). The decision on the card: the budget
is exactly the size of the todo body column; no per-note cap, no widening.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent_coord.helpers.errors import CoordError
from agent_coord.server.api.mill import rpc
from agent_coord.server.records import todo as rec_todo
from agent_coord.server.records.todo import BODY_MAX

SQL = Path(rec_todo.__file__).resolve().parents[1] / "sql"


@pytest.fixture(autouse=True)
def _project_already_exists(monkeypatch):
    monkeypatch.setattr("agent_coord.server.records.name.get", lambda *a, **k: 1)


def _card(monkeypatch, detail: str, **hit) -> dict:
    stored = {"body": json.dumps({"slug": "budget", "doing": "", "detail": detail}), "n": 0}

    def fake_find(cn, project, need):
        return dict({"id": 9, "body": stored["body"], "creator": "builder"}, **hit)

    def fake_update(cn, tid, desk, body=None, **k):
        stored["n"] += 1
        if body is not None:
            stored["body"] = body
        return [{"id": tid}]

    monkeypatch.setattr("agent_coord.server.records.todo.find", fake_find)
    monkeypatch.setattr("agent_coord.server.records.todo.update", fake_update)

    def fake_card_sp(c, proc, args, roster, need):  # #867: claim writes the body in cmd_claim
        if args[4] is not None:
            stored["body"] = args[4]
        return {"card": args[1], "status": "claimed"}

    monkeypatch.setattr(rpc, "_card_sp", fake_card_sp)
    monkeypatch.setattr(rpc, "_poke", lambda *a, **k: None)
    return stored


def test_body_max_is_the_todo_body_column():
    tables = (SQL / "tables.sql").read_text(encoding="utf-8")
    block = tables[tables.index("CREATE TABLE IF NOT EXISTS todo (") :]
    block = block[: block.index(") ENGINE")]
    col = re.search(r"^\s*body\s+VARCHAR\((\d+)\)\s+CHARACTER SET utf8mb4", block, re.M)
    assert col and int(col.group(1)) == BODY_MAX
    procs = (SQL / "sp_todo.sql").read_text(encoding="utf-8")
    sizes = {int(n) for n in re.findall(r"IN p_body\s+VARCHAR\((\d+)\)", procs)}
    assert sizes == {BODY_MAX}


def test_a_note_that_fills_the_column_exactly_is_kept(monkeypatch):
    stored = _card(monkeypatch, "")
    left = BODY_MAX - len(stored["body"])
    rec = rpc._h_note(MagicMock(), {"need": "budget", "note": "z" * left}, "the-mill", "builder")
    assert len(stored["body"]) == BODY_MAX
    assert rec["detail_left"] == 0
    with pytest.raises(CoordError, match="has 0 left of its %d" % BODY_MAX):
        rpc._h_note(MagicMock(), {"need": "budget", "note": "y"}, "the-mill", "builder")


def test_supersedes_over_the_column_names_the_room_left(monkeypatch):
    base = "keep\n" + "d" * 3900
    stored = _card(monkeypatch, base)
    before = stored["body"]
    left = BODY_MAX - len(before)
    with pytest.raises(CoordError) as e:
        rpc._h_note(
            MagicMock(),
            {"need": "budget", "supersedes": "keep", "note": "n" * (left + 400)},
            "the-mill",
            "builder",
        )
    msg = str(e.value)
    assert "refused, nothing written" in msg and f"has {left} left of its {BODY_MAX}" in msg
    assert stored["body"] == before and stored["n"] == 0


def test_claim_msg_over_the_column_names_the_room_left(monkeypatch):
    stored = _card(monkeypatch, "d" * 4000)
    before = stored["body"]
    left = BODY_MAX - len(before)
    with pytest.raises(CoordError) as e:
        rpc._h_claim(MagicMock(), {"need": "budget", "msg": "m" * (left + 10)}, "the-mill", "builder")
    msg = str(e.value)
    assert msg.startswith("claim: refused, nothing written")
    assert f"has {left} left of its {BODY_MAX}" in msg
    assert stored["body"] == before and stored["n"] == 0


def test_claim_msg_that_fills_the_column_exactly_is_kept(monkeypatch):
    stored = _card(monkeypatch, "")
    left = BODY_MAX - len(stored["body"])
    rpc._h_claim(MagicMock(), {"need": "budget", "msg": "m" * left}, "the-mill", "builder")
    assert len(stored["body"]) == BODY_MAX
