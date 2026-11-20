"""Card 1236: replace-body on a letter tells desks that already read it.

No live office. One recipient has opened the letter and one has not. The
reader gets one mail notice, on the same emit path as a new letter, and
opened is cleared so inbox shows the letter again. The unread recipient
and the sender get none. A later replace notifies the reader again once
they have opened the letter.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from agent_coord.helpers.errors import CoordError
from agent_coord.server.api.mill import rpc
from agent_coord.server.mail_push import notify_replaced_readers
from agent_coord.server.records.mail import public_mail


def _world():
    rows = [
        {
            "desk_id": 2,
            "desk": "reader",
            "opened": "2026-11-01 00:00:00.000000",
            "receipt": 1,
        },
        {"desk_id": 3, "desk": "waiting", "opened": None, "receipt": 0},
    ]
    letter = {
        "id": 12,
        "created": "2026-11-01 00:00:00.000000",
        "desk": "sender",
        "sender_roster": "office",
        "body": "new text",
        "body_updated": "2026-11-19 01:02:03.000000",
        "body_updater": "sender",
    }
    sqls: list[tuple] = []
    sent: list[tuple] = []

    def to_list(cn, mail_id):
        assert mail_id == 12
        return [dict(r) for r in rows]

    def letter_row(cn, mail_id):
        assert mail_id == 12
        return dict(letter)

    class Cur:
        def execute(self, sql, args=()):
            sqls.append((sql, tuple(args)))
            if not str(sql).lstrip().upper().startswith("UPDATE"):
                return
            ids = {int(x) for x in tuple(args)[1:]}
            for row in rows:
                if int(row["desk_id"]) in ids:
                    row["opened"] = None

        def close(self):
            return None

    cn = MagicMock()
    cn.cursor.return_value = Cur()
    return SimpleNamespace(
        cn=cn, rows=rows, letter=letter, sqls=sqls, sent=sent, to_list=to_list, letter_row=letter_row
    )


def _install(monkeypatch, world) -> None:
    monkeypatch.setattr("agent_coord.server.records.mail.to_list", world.to_list)
    monkeypatch.setattr("agent_coord.server.records.mail.letter_row", world.letter_row)
    monkeypatch.setattr("agent_coord.server.records.mail.tree_crumbs", lambda cn, mail_id: {})

    def emit(cn, desk, kind, payload, **kw):
        world.sent.append((desk, kind, payload, kw))
        return "missed"

    monkeypatch.setattr("agent_coord.server.push.emit", emit)


def _set_clause(sql: str) -> str:
    return str(sql).split(" WHERE ", 1)[0].lower()


def test_replace_notifies_the_reader_only_and_clears_opened(monkeypatch):
    world = _world()
    _install(monkeypatch, world)
    told = notify_replaced_readers(world.cn, 12, "sender")
    assert told == ["reader"]
    assert [row[0] for row in world.sent] == ["reader"]
    desk, kind, payload, kw = world.sent[0]
    assert desk == "reader" and kind == "mail"
    assert payload["kind"] == "mail" and payload["id"] == 12
    assert payload["body"] == "new text"
    assert payload["opened"] is None
    assert kw["reason"] == "addressed"
    assert len(world.sqls) == 1
    sql, args = world.sqls[0]
    clause = _set_clause(sql)
    assert "opened = null" in clause
    assert "receipt" not in clause
    assert "delete" not in sql.lower()
    assert "activity_history" not in sql.lower()
    assert args == (12, 2)
    reader = next(r for r in world.rows if r["desk"] == "reader")
    waiting = next(r for r in world.rows if r["desk"] == "waiting")
    assert reader["opened"] is None and reader["receipt"] == 1
    assert waiting["opened"] is None and waiting["receipt"] == 0
    shown = public_mail(world.letter, [{"desk": "reader", "receipt": 1, "opened": None}])
    assert shown["body"] == "new text"
    assert shown["edited"] == "edited by sender at 2026-11-19 01:02:03.000000"
    assert world.cn.commit.called


def test_second_replace_notifies_again_after_the_reader_opens(monkeypatch):
    world = _world()
    _install(monkeypatch, world)
    assert notify_replaced_readers(world.cn, 12, "sender") == ["reader"]
    # Still unread: another replace does not add a notice.
    assert notify_replaced_readers(world.cn, 12, "sender") == []
    assert [row[0] for row in world.sent] == ["reader"]
    world.rows[0]["opened"] = "2026-11-19 02:00:00.000000"
    world.letter["body"] = "newer text"
    assert notify_replaced_readers(world.cn, 12, "sender") == ["reader"]
    assert [row[0] for row in world.sent] == ["reader", "reader"]
    assert world.sent[1][2]["body"] == "newer text"
    assert world.sent[1][2]["opened"] is None
    assert len(world.sqls) == 2


def test_acting_desk_who_already_read_is_not_told(monkeypatch):
    world = _world()
    world.rows.append(
        {
            "desk_id": 1,
            "desk": "sender",
            "opened": "2026-11-01 00:00:00.000000",
            "receipt": 1,
        }
    )
    _install(monkeypatch, world)
    assert notify_replaced_readers(world.cn, 12, "sender") == ["reader"]
    assert [row[0] for row in world.sent] == ["reader"]
    sender = next(r for r in world.rows if r["desk"] == "sender")
    assert sender["opened"] == "2026-11-01 00:00:00.000000"
    assert sender["receipt"] == 1
    sql, args = world.sqls[0]
    assert 1 not in args


def test_mail_replace_handler_calls_the_notice(monkeypatch):
    seen: dict = {}

    def replace(cn, kind, item_id, desk, text, expected):
        return {"op": "replaced", "id": item_id, "type": kind}

    monkeypatch.setattr("agent_coord.server.records.body.replace", replace)
    monkeypatch.setattr(
        "agent_coord.server.mail_push.notify_replaced_readers",
        lambda cn, mail_id, actor: seen.setdefault("notice", (mail_id, actor)) or ["reader"],
    )
    monkeypatch.setattr(rpc, "_poke", lambda *a, **k: seen.setdefault("poke", (a[1], k.get("owner"))))
    out = rpc._h_replace_body(
        SimpleNamespace(_cn=object()),
        {"type": "mail", "id": 12, "body": "new text", "expected": "2026-11-01 00:00:00"},
        "office",
        "sender",
    )
    assert out["op"] == "replaced"
    assert seen["notice"] == (12, "sender")
    assert seen["poke"] == ("mail", "sender")


def test_card_replace_history_and_refusal_do_not_notify(monkeypatch):
    def fail_notice(*args, **kwargs):
        raise AssertionError("mail notice")

    monkeypatch.setattr("agent_coord.server.mail_push.notify_replaced_readers", fail_notice)
    monkeypatch.setattr(rpc, "_poke", lambda *a, **k: None)
    monkeypatch.setattr(
        "agent_coord.server.records.body.replace",
        lambda cn, kind, item_id, desk, text, expected: {"op": "replaced", "id": item_id},
    )
    book = SimpleNamespace(_cn=object())
    card = rpc._h_replace_body(
        book,
        {"type": "todo", "id": 8, "body": "card text", "expected": "2026-11-01 00:00:00"},
        "office",
        "sender",
    )
    assert card["op"] == "replaced"
    monkeypatch.setattr(
        "agent_coord.server.records.body.history",
        lambda cn, kind, item_id, order: [{"old_body": "v1"}],
    )
    hist = rpc._h_replace_body(book, {"type": "mail", "id": 12, "history": True}, "office", "sender")
    assert hist == [{"old_body": "v1"}]

    def refused(*args, **kwargs):
        raise CoordError("body:unchanged: replace did nothing: the new text is the same as the current text")

    monkeypatch.setattr("agent_coord.server.records.body.replace", refused)
    with pytest.raises(CoordError, match="body:unchanged"):
        rpc._h_replace_body(
            book,
            {"type": "mail", "id": 12, "body": "same", "expected": "2026-11-01 00:00:00"},
            "office",
            "sender",
        )
