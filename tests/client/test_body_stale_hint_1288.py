# -*- coding: utf-8 -*-
"""Card 1288: a body:stale refusal says who edited the text, when (UTC), that nothing was written, and the next step.

The office signals ``body:stale by DESK at YYYY-MM-DD HH:MM:SS`` (sp_body.sql); the server turns it into one line.
The duplicate-key path looks the editor up; when that lookup fails it keeps the old line and names no one.
No MySQL here: the SQL side is tests/server/records/test_body_stale_hint_1288.py.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_coord.client import body_read
from agent_coord.helpers.errors import CoordError
from agent_coord.server.api.mill import rpc

TODO_LINE = (
    "body:stale: card 1270 changed after your read: validator edited it at 2026-11-22 19:58:10 UTC. "
    "Nothing was written. Next: read it again (mill todo the-mill 1270), put your edit on top of that text, "
    "then run replace-body again. Their old text: mill replace-body todo 1270 --history"
)
MAIL_LINE = (
    "body:stale: letter 6780 changed after your read: grok-tui edited it at 2026-11-22 19:58:10 UTC. "
    "Nothing was written. Next: read it again (mill mail-thread 6780 --full), put your edit on top of that text, "
    "then run replace-body again. Their old text: mill replace-body mail 6780 --history"
)


def test_todo_line_is_the_wording_as_written():
    got = body_read.map_refusal("body:stale by validator at 2026-11-22 19:58:10", "todo", 1270, "the-mill",
                                me="builder")
    assert got == TODO_LINE


def test_mail_line_is_the_wording_as_written():
    got = body_read.map_refusal("body:stale by grok-tui at 2026-11-22 19:58:10", "mail", 6780, me="builder")
    assert got == MAIL_LINE


def test_same_desk_reads_this_desk_another_session():
    got = body_read.map_refusal("body:stale by builder at 2026-11-22 19:58:10", "todo", 1270, "the-mill",
                                me="builder")
    assert got == TODO_LINE.replace("validator edited", "this desk (another session) edited")
    assert "builder" not in got


def test_bare_stale_keeps_the_old_line_and_names_no_one():
    assert body_read.map_refusal("body:stale", "todo", 9, "the-mill", me="builder") == (
        "body:stale: read it again: mill todo the-mill 9"
    )


class _Refusal(Exception):
    def __init__(self, msg: str = "", errno: int = 0, sqlstate: str = ""):
        super().__init__(msg)
        self.msg = msg
        self.errno = errno
        self.sqlstate = sqlstate


def _run(monkeypatch, kind: str, item_id: int, exc: Exception, owner: str = "builder"):
    """Drive _h_replace_body with the office write refusing; record anything that would follow a write."""
    after: list[str] = []

    def refuse(*_a, **_k):
        raise exc

    monkeypatch.setattr("agent_coord.server.records.body.replace", refuse)
    monkeypatch.setattr(rpc, "_todo_roster_name", lambda cn, i: "the-mill")
    monkeypatch.setattr(rpc, "_poke", lambda *a, **k: after.append("poke"))
    monkeypatch.setattr("agent_coord.server.mail_push.notify_replaced_readers",
                        lambda *a, **k: after.append("notify"))
    body = {"type": kind, "id": item_id, "body": "my edit", "expected": "2026-11-22 19:00:00.000000"}
    with pytest.raises(CoordError) as err:
        rpc._h_replace_body(SimpleNamespace(_cn=object()), body, "the-mill", owner)
    return str(err.value), after


def test_handler_turns_the_office_signal_into_the_line_and_writes_nothing(monkeypatch):
    msg, after = _run(monkeypatch, "todo", 1270,
                      _Refusal("body:stale by validator at 2026-11-22 19:58:10", sqlstate="45000"))
    assert TODO_LINE in msg
    assert after == []
    msg, after = _run(monkeypatch, "mail", 6780,
                      _Refusal("body:stale by grok-tui at 2026-11-22 19:58:10", sqlstate="45000"))
    assert MAIL_LINE in msg
    assert after == []


def test_duplicate_key_looks_up_the_editor(monkeypatch):
    seen = []

    def editor(cn, kind, item_id):
        seen.append((kind, item_id))
        return ("validator", "2026-11-22 19:58:10")

    monkeypatch.setattr(rpc, "_body_editor", editor)
    msg, after = _run(monkeypatch, "todo", 1270, _Refusal("Duplicate entry 'x' for key 'u'", errno=1062))
    assert TODO_LINE in msg and seen == [("todo", 1270)] and after == []


def test_duplicate_key_lookup_failure_keeps_todays_line(monkeypatch):
    monkeypatch.setattr(rpc, "_body_editor", lambda cn, kind, item_id: None)
    msg, after = _run(monkeypatch, "mail", 6780, _Refusal("Duplicate entry 'x' for key 'u'", errno=1062))
    assert "body:stale: read it again: mill mail-thread 6780 --full" in msg
    assert "edited it at" not in msg and after == []


def test_editor_lookup_swallows_a_failed_query():
    class _Broken:
        def cursor(self, *a, **k):
            raise RuntimeError("gone")

    assert rpc._body_editor(_Broken(), "todo", 1270) is None
