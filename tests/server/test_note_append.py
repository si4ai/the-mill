"""Card 1125: the server note path does not append detail. Card text is mill replace-body."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agent_coord.helpers.errors import CoordError
from agent_coord.server.api.mill import rpc


def test_note_appends_detail(monkeypatch):
    stored = {"body": ""}

    def fake_find(cn, project, need):
        return {"id": 9, "body": stored["body"] or "slug=loop2-note\ndoing=\ndetail=seed-text"}

    def fake_unpack(body, tid):
        detail = "seed-text"
        if "detail=" in (body or ""):
            detail = body.split("detail=", 1)[-1].split("\n")[0]
        # after first update body is packed
        if "seed-text" in (body or "") and "second" in (body or ""):
            detail = body  # won't happen
        payload_detail = detail
        if stored.get("payload_detail"):
            payload_detail = stored["payload_detail"]
        return {
            "need_id": "loop2-note",
            "doing": "",
            "detail": payload_detail,
            "payload": {"slug": "loop2-note", "doing": "", "detail": payload_detail},
        }

    def fake_pack(payload):
        stored["payload_detail"] = payload.get("detail")
        stored["body"] = f"slug={payload.get('slug')}\ndetail={payload.get('detail')}"
        return stored["body"]

    def fake_update(cn, tid, desk, body=""):
        stored["body"] = body
        return [{"id": tid}]

    monkeypatch.setattr("agent_coord.server.records.todo.find", fake_find)
    monkeypatch.setattr("agent_coord.server.records.todo.unpack", fake_unpack)
    monkeypatch.setattr("agent_coord.server.records.todo.stored_body", fake_pack)
    monkeypatch.setattr("agent_coord.server.records.todo.update", fake_update)
    monkeypatch.setattr(rpc, "_poke", lambda *a, **k: None)

    book = MagicMock()
    with pytest.raises(CoordError, match="mill replace-body"):
        rpc._h_note(book, {"need": "loop2-note", "note": "first"}, "PROJ_the-mill", "DESK_builder")
    assert stored.get("payload_detail") in (None, "seed-text")


def test_note_replace_is_refused(monkeypatch):
    stored = {"payload_detail": "seed-text", "body": "detail=seed-text"}

    def fake_find(cn, project, need):
        return {"id": 9, "body": stored["body"]}

    def fake_unpack(body, tid):
        d = stored.get("payload_detail") or "seed-text"
        return {
            "need_id": "loop2-note",
            "doing": "",
            "detail": d,
            "payload": {"slug": "loop2-note", "doing": "", "detail": d},
        }

    def fake_pack(payload):
        stored["payload_detail"] = payload.get("detail")
        stored["body"] = f"detail={payload.get('detail')}"
        return stored["body"]

    monkeypatch.setattr("agent_coord.server.records.todo.find", fake_find)
    monkeypatch.setattr("agent_coord.server.records.todo.unpack", fake_unpack)
    monkeypatch.setattr("agent_coord.server.records.todo.stored_body", fake_pack)
    monkeypatch.setattr("agent_coord.server.records.todo.update", lambda *a, **k: [{"id": 9}])
    monkeypatch.setattr(rpc, "_poke", lambda *a, **k: None)

    book = MagicMock()
    # #539: notes append; a replace request is refused and the detail stays.
    with pytest.raises(CoordError, match="mill replace-body"):
        rpc._h_note(
            book,
            {"need": "loop2-note", "note": "only-this", "replace": True},
            "PROJ_the-mill",
            "DESK_builder",
        )
    assert stored["payload_detail"] == "seed-text"
