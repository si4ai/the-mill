"""A dropped sit frame leaves a waiting push row, or writes one drop line."""
from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.sql

from agent_coord.server.records import push as rec_push
from agent_coord.server.records.db import conn_kwargs as _conn_kwargs
from tests.server.records.conftest import seed_names

def _rows(cn, desk_id: int) -> list[dict]:
    cur = cn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT id, cause AS kind, payload, state AS outcome FROM wake "
            "WHERE desk_id = %s AND state <> 'taken' ORDER BY id",
            (desk_id,),
        )
        out = []
        for row in cur.fetchall():
            payload = row["payload"]
            if isinstance(payload, str):
                payload = json.loads(payload)
            row["payload"] = payload
            out.append(row)
        return out
    finally:
        cur.close()

def test_waiting_row_is_left_alone(cn) -> None:
    desk = seed_names(cn, ("hint-drop-wait", "desk"))[0]
    rec_push.put(
        cn,
        "hint-drop-wait",
        "hint",
        {"type": "todo", "id": 7, "hint": "TODO", "detail": "keep-me"},
        "missed",
    )
    frame = {
        "type": "todo",
        "id": 7,
        "hint": "TODO",
        "route": "todo:TODO",
        "idem": "hint:todo:7:hint-drop-wait",
    }
    assert rec_push.note_drop(cn, "hint-drop-wait", frame) == "leave"
    rows = _rows(cn, desk)
    assert len(rows) == 1
    assert rows[0]["outcome"] == "missed"
    assert rows[0]["payload"]["detail"] == "keep-me"
    assert "dropped" not in rows[0]["payload"]
    assert "idem" not in rows[0]["payload"]

def test_sent_row_is_put_back(cn) -> None:
    desk = seed_names(cn, ("hint-drop-sent", "desk"))[0]
    rec_push.put(
        cn,
        "hint-drop-sent",
        "hint",
        {"type": "todo", "id": 7, "hint": "TODO", "detail": "keep-me"},
        "sent",
    )
    frame = {
        "type": "todo",
        "id": 7,
        "hint": "TODO",
        "route": "todo:TODO",
        "idem": "hint:todo:7:hint-drop-sent",
    }
    assert rec_push.note_drop(cn, "hint-drop-sent", frame) == "back"
    assert rec_push.note_drop(cn, "hint-drop-sent", frame) == "leave"
    rows = _rows(cn, desk)
    assert len(rows) == 1
    assert rows[0]["kind"] == "hint"
    assert rows[0]["outcome"] == "missed"
    assert rows[0]["payload"]["detail"] == "keep-me"
    assert rows[0]["payload"]["type"] == "todo"
    assert int(rows[0]["payload"]["id"]) == 7
    assert rows[0]["payload"]["idem"] == "hint:todo:7:hint-drop-sent"
    assert "dropped" not in rows[0]["payload"]

def test_missing_row_writes_one_drop_line(cn) -> None:
    desk = seed_names(cn, ("hint-drop-gone", "desk"))[0]
    frame = {
        "type": "todo",
        "id": 9,
        "hint": "TODO",
        "route": "todo:TODO",
        "idem": "hint:todo:9:hint-drop-gone",
        "detail": "not-on-the-line",
    }
    assert rec_push.note_drop(cn, "hint-drop-gone", frame) == "requeue"
    assert rec_push.note_drop(cn, "hint-drop-gone", frame) == "leave"
    rows = _rows(cn, desk)
    assert len(rows) == 1
    assert rows[0]["kind"] == "hint"
    assert rows[0]["outcome"] == "missed"
    assert rows[0]["payload"]["route"] == "todo:TODO"
    assert int(rows[0]["payload"]["id"]) == 9
    assert int(rows[0]["payload"]["dropped"]) == 1
    assert rows[0]["payload"]["idem"] == "hint:todo:9:hint-drop-gone"
    assert "detail" not in rows[0]["payload"]
    assert "not-on-the-line" not in json.dumps(rows[0]["payload"])

def test_mail_row_still_waiting_is_left(cn) -> None:
    desk = seed_names(cn, ("hint-drop-mail", "desk"))[0]
    rec_push.put(cn, "hint-drop-mail", "mail", {"id": 4, "body": "letter"}, "missed")
    frame = {"kind": "mail", "id": 4, "hint": "MAIL", "route": "mail:MAIL"}
    assert rec_push.note_drop(cn, "hint-drop-mail", frame) == "leave"
    rows = _rows(cn, desk)
    assert [row["kind"] for row in rows] == ["mail"]
    assert rows[0]["payload"]["body"] == "letter"
    cur = cn.cursor()
    try:
        # Hand-back style clear: mark taken (no delete of history)
        cur.execute("UPDATE wake SET state = 'taken' WHERE desk_id = %s", (desk,))
        cn.commit()
    finally:
        cur.close()
    assert rec_push.note_drop(cn, "hint-drop-mail", frame) == "requeue"
    assert rec_push.note_drop(cn, "hint-drop-mail", frame) == "leave"
    again = _rows(cn, desk)
    assert len(again) == 1
    assert again[0]["kind"] == "hint"
    assert int(again[0]["payload"]["dropped"]) == 1
    assert again[0]["payload"]["route"] == "mail:MAIL"
    assert "body" not in again[0]["payload"]
