"""ux12 polish (card #283): watch/unwatch name themselves, todo --find ranks and
snips, regression row F25 is documented. The send roster note is in
tests/server/records/test_card_lookup_274.py (real book)."""
from __future__ import annotations

import json
from pathlib import Path

from agent_coord.__main__ import _build_parser
from agent_coord.client.http import _said_command, _todo_find
from agent_coord.client.language import translate

ROOT = Path(__file__).resolve().parents[2]


def _card(i, need, detail="", roster="cold-test"):
    # #818: cards have no title (no doing field).
    return {"project_id": roster, "need_id": need, "id": i, "status": "open",
            "detail": detail, "progress": ["x" * 400], "volunteer": "", "asker": "u1",
            "tree": None, "labels": []}


def test_regression_row_f25_documented():
    doc = (ROOT / "docs" / "protocol" / "commands.md").read_text(encoding="utf-8")
    assert "Regression row F25 (ux12-polish)" in doc


def test_watch_and_unwatch_remember_the_typed_command(monkeypatch):
    import agent_coord.client.tokens as tokens

    monkeypatch.setattr(tokens, "resolve_desk_owner", lambda x="": "me")
    p = _build_parser()
    a = translate(p.parse_args(["watch", "todo", "5"]))
    assert a.cmd == "add" and a.said_command == "watch"
    b = translate(p.parse_args(["unwatch", "todo", "5"]))
    assert b.cmd == "remove" and b.said_command == "unwatch"


def test_watch_reply_names_watch():
    row = {"ok": True, "result": {"ok": True, "verb": "add", "type": "todo", "id": 5}}
    assert _said_command(row, "watch")["result"]["verb"] == "watch"
    row = {"ok": True, "result": {"ok": True, "verb": "remove", "type": "todo", "id": 5}}
    assert _said_command(row, "unwatch")["result"]["verb"] == "unwatch"


def test_unwatch_refusal_names_unwatch():
    row = {"ok": False, "error": "remove: me is not watching todo:5"}
    assert _said_command(row, "unwatch")["error"] == "unwatch: me is not watching todo:5"


def test_plain_add_reply_is_untouched():
    row = {"ok": True, "result": {"ok": True, "verb": "add", "type": "todo", "id": 5}}
    assert _said_command(row, "") is row


def test_find_ranks_need_before_body_hits():
    big = "unrelated " * 600 + "login " + "tail " * 200
    rows = [_card(1, "big-card", big), _card(2, "other", "x"),
            _card(3, "fix-thing", "fix login 500"), _card(4, "login-page", "")]
    out = _todo_find({"ok": True, "result": rows}, "login")
    assert [c["id"] for c in out["result"]] == [4, 1, 3]
    assert [c["match"] for c in out["result"]] == ["need", "detail", "detail"]
    assert out["note"].startswith("3 card(s)")


def test_find_body_hit_prints_a_short_snippet():
    big = "unrelated " * 600 + "login " + "tail " * 200
    out = _todo_find({"ok": True, "result": [_card(1, "big-card", big)]}, "LOGIN")
    c = out["result"][0]
    assert "detail" not in c and "progress" not in c
    assert "login" in c["snippet"] and len(c["snippet"]) <= 126


def test_one_need_hit_prints_under_1kb():
    rows = [_card(9, "ux12-fix-login", "steps " * 900)]
    out = _todo_find({"ok": True, "result": rows}, "login")
    assert len(out["result"]) == 1
    assert len(json.dumps(out).encode()) < 1024
