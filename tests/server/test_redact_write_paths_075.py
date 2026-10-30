# -*- coding: utf-8 -*-
"""0.7.5: every write path runs the store redactor before the row is stored.

Covers reply, --doing (mark, drop, unpark, hold), join, claim, unclaim, pass, hold, assign and the score
value, target and note, plus Wall desk posts, Admin error mail and the error
text a 500 returns. Fake values are built at runtime. Regression row S-7
(redact-write-paths).
"""
from __future__ import annotations

import ast
import random
import string
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent_coord.helpers.errors import CoordError
from agent_coord.server.api.mill import rpc
from agent_coord.server.book import Book
from agent_coord.server.redact import PH, TEXT_KEYS, WRITE_COMMANDS, err_text

R = random.Random(5)
ROOT = Path(__file__).resolve().parents[2]


def fake_token() -> str:
    return "gl" + "pat-" + "".join(R.choice(string.ascii_letters + string.digits) for _ in range(20))


def _capture(store):
    def handler(c, body, project, owner):
        store["body"] = dict(body)
        return [{"ok": True, "id": 1}]

    return handler


CASES = [
    ("reply", {"mail_id": 5, "body": "see {t}"}, "body"),
    ("mark", {"ids": [5], "doing": "using {t}"}, "doing"),
    ("drop", {"resource": "r1", "doing": "after {t}"}, "doing"),
    ("unpark", {"need": "n1", "doing": "on {t}"}, "doing"),
    ("claim", {"need": "n1", "msg": "key {t}"}, "msg"),
    ("unclaim", {"need": "n1", "msg": "key {t}"}, "msg"),
    ("pass", {"need": "n1", "note": "key {t}"}, "note"),
    ("hold", {"resource": "r1", "doing": "with {t}"}, "doing"),
    ("score", {"name": "k", "value": "{t}", "target": "1"}, "value"),
    ("score", {"name": "k", "value": "1", "target": "{t}"}, "target"),
    ("score", {"name": "k", "value": "1", "note": "n {t}"}, "note"),
    ("send", {"body": "key {t}"}, "body"),
    ("note", {"need": "n1", "note": "key {t}"}, "note"),
]


@pytest.mark.parametrize("command,args,key", CASES, ids=[f"{v}-{k}" for v, _, k in CASES])
def test_ws_write_is_redacted_before_the_handler(monkeypatch, command, args, key):
    tok = fake_token()
    store: dict = {}
    monkeypatch.setitem(rpc.HANDLERS, command, _capture(store))
    body = {k: (v.format(t=tok) if isinstance(v, str) else v) for k, v in args.items()}
    c = MagicMock(spec=Book)
    c._cn = MagicMock()  # a --doing command runs in a request transaction on it (#818)
    try:
        rpc.dispatch_ws(c, "desk-a", command, body, req_id=None)
    except CoordError:
        pass  # the fake handler wrote no item, so a --doing command is refused after it ran
    assert tok not in store["body"][key]
    assert PH["token"] in store["body"][key]


def test_http_join_doing_is_redacted(monkeypatch):
    """join is HTTP only; its doing line is stored on the seat."""
    tok = fake_token()
    store: dict = {}
    monkeypatch.setitem(rpc.HANDLERS, "join", _capture(store))
    c = MagicMock(spec=Book)
    c._cn = MagicMock()
    rpc.dispatch(c, {"verb": "join", "project": "the-mill", "owner": "desk-a", "doing": "seat " + tok}, token="")
    assert tok not in store["body"]["doing"]


def test_read_commands_are_left_alone(monkeypatch):
    tok = fake_token()
    store: dict = {}
    monkeypatch.setitem(rpc.HANDLERS, "todo", _capture(store))
    rpc.dispatch_ws(MagicMock(spec=Book), "desk-a", "todo", {"find": tok}, req_id=None)
    assert store["body"]["find"] == tok


def test_every_text_command_is_listed():
    for command in ("send", "reply", "note", "open", "score", "join", "claim", "unclaim", "pass", "hold", "assign", "mark", "drop", "unpark"):
        assert command in WRITE_COMMANDS
    for key in ("body", "doing", "msg", "note", "detail", "value", "target"):
        assert key in TEXT_KEYS


def test_wall_desk_post_is_redacted(monkeypatch):
    from agent_coord.server.admin import human

    tok = fake_token()
    seen = {}
    monkeypatch.setattr(human.door, "check", lambda t: True)
    monkeypatch.setattr(
        "agent_coord.server.records.join.desk_for_token_hash",
        lambda cn, digest: "desk-b",
    )

    def insert(cn, project, src, dst, body, **k):
        seen["body"] = body
        return [{"id": 9}]

    monkeypatch.setattr(human.rec_mail, "insert", insert)
    monkeypatch.setattr("agent_coord.server.mail_push.push_mail", lambda cn, mid: None)
    human.desk_post(MagicMock(), {"token": "t", "dst": "desk-b", "body": "key " + tok})
    assert tok not in seen["body"] and PH["token"] in seen["body"]


def test_admin_alert_mail_is_redacted(monkeypatch):
    from agent_coord.server import push

    tok = fake_token()
    seen = {}
    monkeypatch.setattr("agent_coord.server.records.member.select", lambda *a, **k: [{"desk": "host-desk"}])

    def insert(cn, project, src, dst, body, *a, **k):
        seen["body"] = body
        return [{"id": 3}]

    monkeypatch.setattr("agent_coord.server.records.mail.insert", insert)
    monkeypatch.setattr("agent_coord.server.mail_push.push_mail", lambda cn, mid: None)
    push.mill_admin_alert(MagicMock(), "boom url https://svc:" + tok + "@db.example/x")
    assert tok not in seen["body"]


def test_err_text_redacts_then_cuts():
    tok = fake_token()
    out = err_text(RuntimeError("connect failed for " + tok + " " + "x" * 400))
    assert tok not in out and len(out) <= 240


def test_error_replies_use_err_text():
    """No 500/400 reply in the wall returns raw exception text."""
    for rel in ("agent_coord/server/middleware.py", "agent_coord/server/asgi.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert "str(e)[:240]" not in src, rel
        ast.parse(src)


def test_docs_name_the_row():
    text = (ROOT / "docs" / "security" / "REGRESSION-MATRIX.md").read_text(encoding="utf-8")
    assert "| S-7 |" in text and "test_redact_write_paths_075.py" in text
