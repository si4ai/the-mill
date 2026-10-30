# -*- coding: utf-8 -*-
"""Lean list truncate for mailbox + todos; detail full-body routes."""
from __future__ import annotations

from agent_coord.server.records.mail import lean_body, public_mail, MAIL_BODY_LIST_MAX
from agent_coord.server.records.floor import lean_text, LIST_TEXT_MAX, v1_mail, v1_todo


def test_lean_body_truncates() -> None:
    short, t1 = lean_body("hi")
    assert short == "hi" and t1 is False
    long = "x" * (MAIL_BODY_LIST_MAX + 10)
    got, t2 = lean_body(long)
    assert t2 is True
    assert len(got) == MAIL_BODY_LIST_MAX


def test_public_mail_lean_flag() -> None:
    body = "B" * 300
    lean = public_mail({"id": 1, "desk": "DESK_a", "body": body}, [], lean=True)
    assert lean["body_trunc"] is True
    assert len(lean["body"]) == 256
    full = public_mail({"id": 1, "desk": "DESK_a", "body": body}, [], lean=False)
    assert "body_trunc" not in full
    assert full["body"] == body


def test_lean_text_todos() -> None:
    got, trunc = lean_text("ok")
    assert got == "ok" and trunc is False
    long = "d" * (LIST_TEXT_MAX + 5)
    got2, trunc2 = lean_text(long)
    assert trunc2 and len(got2) == LIST_TEXT_MAX


def test_build_todos_lean(monkeypatch) -> None:
    from agent_coord.server.records.floor import build_todos

    long_detail = "Z" * 400
    monkeypatch.setattr(
        "agent_coord.server.records.todo.select_rosters",
        lambda cn, names, status="": [
            (
                "demo",
                {
                    "id": 9,
                    "status": "open",
                    "body": '{"slug":"x","doing":"short","detail":"%s"}' % long_detail,
                    "roster": "demo",
                    "assigned": "a",
                    "creator": "b",
                },
            )
        ],
    )
    needs, issues = build_todos(object(), ["demo"], {"demo"}, lean=True)
    assert issues == []
    assert len(needs) == 1
    assert needs[0]["detail_trunc"] is True
    assert len(needs[0]["detail"]) == 256
    assert "doing_trunc" not in needs[0]
    # need_id is the card id (todo.id), not the slug in the body
    assert needs[0]["need_id"] == "9"


def test_v1_detail_builders(monkeypatch) -> None:
    monkeypatch.setattr(
        "agent_coord.server.records.mail.letter_row",
        lambda cn, mid: {
            "id": mid,
            "created": "2026-01-01",
            "desk": "DESK_a",
            "sender_roster": None,
            "body": "FULL BODY " * 40,
        },
    )
    monkeypatch.setattr("agent_coord.server.records.mail.to_list", lambda cn, mid: [])
    monkeypatch.setattr("agent_coord.server.records.mail.tree_crumbs", lambda cn, mid: {})
    mail = v1_mail(object(), 7)
    assert mail["mail"]["id"] == 7
    assert "body_trunc" not in mail["mail"]
    assert len(mail["mail"]["body"]) > 256

    monkeypatch.setattr(
        "agent_coord.server.records.todo.get",
        lambda cn, tid: [
            {
                "id": tid,
                "status": "open",
                "body": '{"slug":"need","detail":"%s"}' % ("Y" * 300),
                "roster": "PROJ_demo",
                "assigned": "DESK_a",
                "creator": "DESK_b",
            }
        ],
    )
    todo = v1_todo(object(), 8)
    assert todo["todo"]["id"] == 8
    assert "detail_trunc" not in todo["todo"]
    assert len(todo["todo"]["detail"]) == 300
    assert todo["todo"]["need_id"] == "8"


def test_v1_mail_todo_routes(monkeypatch) -> None:
    from pathlib import Path
    from fastapi.testclient import TestClient
    from agent_coord.lib.observe import parse_roots
    from agent_coord.server.asgi import make_asgi_app

    monkeypatch.setattr("agent_coord.server.admin.door.mode", lambda: "path")
    monkeypatch.setattr("agent_coord.server.allow.allowed", lambda *a, **k: True)

    class _C:
        _cn = object()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr("agent_coord.server.middleware._office", lambda: _C())
    monkeypatch.setattr(
        "agent_coord.server.records.floor.v1_mail",
        lambda cn, mid: {
            "at": "t",
            "node": "n",
            "version": "0.5.6",
            "parts": ["mail"],
            "mail": {"id": mid, "body": "full"},
        },
    )
    monkeypatch.setattr(
        "agent_coord.server.records.floor.v1_todo",
        lambda cn, tid: {
            "at": "t",
            "node": "n",
            "version": "0.5.6",
            "parts": ["todos"],
            "todo": {"id": tid, "detail": "full"},
        },
    )
    root = Path(__file__).resolve().parents[2]
    client = TestClient(make_asgi_app(parse_roots(cwd=root), api_only=True))
    r = client.get("/api/v1/mail/42")
    assert r.status_code == 200
    assert r.json()["mail"]["id"] == 42
    assert "mill" in r.json()
    r2 = client.get("/api/v1/todo/99")
    assert r2.status_code == 200
    assert r2.json()["todo"]["id"] == 99
