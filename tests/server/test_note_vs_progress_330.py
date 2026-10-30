"""A card reply has no always-empty field; help says a note lands in detail (#330)."""
from __future__ import annotations

from pathlib import Path

from agent_coord.server.api.mill import rpc

ROOT = Path(__file__).resolve().parents[2]


def _fields(progress=""):
    return {"need_id": "c330", "detail": "seed\nfirst note", "progress": progress}


def test_card_without_progress_leaves_it_out():
    card = rpc._todo_card({"id": 330, "assigned": "w1", "creator": "a"}, "cold-test", "claimed", _fields())
    assert "progress" not in card
    assert "doing" not in card
    assert card["detail"] == "seed\nfirst note"


def test_card_with_progress_shows_it_and_has_no_title():
    # #818: cards have no title; a stored doing never prints as one.
    fields = dict(_fields(progress="9/12"), doing="ship it")
    card = rpc._todo_card({"id": 330}, "cold-test", "claimed", fields)
    assert "doing" not in card
    assert card["progress"] == "9/12"


def test_note_reply_leaves_out_empty_progress(monkeypatch):
    import json
    from unittest.mock import MagicMock

    body = {"b": json.dumps({"slug": "c330", "doing": "", "detail": "seed"})}
    monkeypatch.setattr(
        "agent_coord.server.records.todo.find", lambda cn, p, n: {"id": 330, "body": body["b"]}
    )

    monkeypatch.setattr(
        "agent_coord.server.records.todo.update", lambda cn, tid, desk, **kw: [{"id": tid}]
    )
    monkeypatch.setattr(rpc, "_poke", lambda *a, **k: None)
    r = rpc._h_note(MagicMock(), {"need": "c330", "note": "first note"}, "cold-test", "w1")
    assert r["detail"] == "seed\nfirst note"
    assert "progress" not in r
    r2 = rpc._h_note(MagicMock(), {"need": "c330", "text": "75%"}, "cold-test", "w1")
    assert r2["progress"] == "75%"


def test_help_says_where_a_note_goes():
    row = next(
        ln for ln in (ROOT / "docs/protocol/cli-desk.md").read_text(encoding="utf-8").splitlines()
        if ln.startswith("| `note` |")
    )
    assert "detail" in row
    assert "peer reads" in row
