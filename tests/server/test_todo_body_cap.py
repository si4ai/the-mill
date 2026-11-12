# -*- coding: utf-8 -*-
"""Note diary must fit mill_todo_update p_body VARCHAR(4096)."""
import json
from unittest.mock import MagicMock

import pytest

from agent_coord.helpers.errors import CoordError
from agent_coord.server.records import todo as rec_todo
from agent_coord.server.api.mill import rpc


@pytest.fixture(autouse=True)
def _project_already_exists(monkeypatch):
    monkeypatch.setattr("agent_coord.server.records.name.get", lambda *a, **k: 1)


def test_open_refuses_detail_over_4096() -> None:
    """#292: create takes the mail body cap (was 500)."""
    book = MagicMock()
    with pytest.raises(CoordError, match="max 4096"):
        rpc._h_open(book, {"need": "cap-4096", "detail": "d" * 4097}, "the-mill", "me")
    assert book._cn.method_calls == []


def test_open_keeps_detail_over_old_500(monkeypatch) -> None:
    """#292: 501..4000 ASCII characters store whole (old cap was 500)."""
    monkeypatch.setattr(rpc, "_poke", lambda *a, **k: None)
    monkeypatch.setattr("agent_coord.server.records.name.ensure_roster", lambda *a, **k: None)
    monkeypatch.setattr("agent_coord.server.records.todo.find", lambda *a, **k: None)
    stored = {}

    def fake_insert(cn, project, desk, status, body):
        stored["body"] = body
        return [{"id": 7}]

    monkeypatch.setattr("agent_coord.server.records.todo.insert", fake_insert)
    for n in (501, 4000):
        rec = rpc._h_open(MagicMock(), {"need": "cap-big", "detail": "d" * n}, "the-mill", "me")
        assert rec["detail"] == "d" * n
        assert json.loads(stored["body"])["detail"] == "d" * n


def test_open_refuses_stored_overflow_never_trims() -> None:
    """#292: detail under 4096 whose stored JSON is over 4096 is refused, not cut."""
    book = MagicMock()
    with pytest.raises(CoordError, match="nothing stored"):
        rpc._h_open(book, {"need": "cap-esc", "detail": "\u00e9" * 1000}, "the-mill", "me")
    with pytest.raises(CoordError, match="nothing stored"):
        rpc._h_open(book, {"need": "cap-full", "detail": "d" * 4096}, "the-mill", "me")
    assert book._cn.method_calls == []


def test_open_keeps_detail_at_499(monkeypatch) -> None:
    monkeypatch.setattr(rpc, "_poke", lambda *a, **k: None)
    monkeypatch.setattr("agent_coord.server.records.name.ensure_roster", lambda *a, **k: None)
    monkeypatch.setattr("agent_coord.server.records.todo.find", lambda *a, **k: None)
    stored = {}

    def fake_insert(cn, project, desk, status, body):
        stored["body"] = body
        return [{"id": 7}]

    monkeypatch.setattr("agent_coord.server.records.todo.insert", fake_insert)
    book = MagicMock()
    rec = rpc._h_open(book, {"need": "cap-499", "detail": "d" * 499}, "the-mill", "me")
    assert rec["detail"] == "d" * 499
    assert json.loads(stored["body"])["detail"] == "d" * 499


def test_open_keeps_empty_detail(monkeypatch) -> None:
    monkeypatch.setattr(rpc, "_poke", lambda *a, **k: None)
    monkeypatch.setattr("agent_coord.server.records.name.ensure_roster", lambda *a, **k: None)
    monkeypatch.setattr("agent_coord.server.records.todo.find", lambda *a, **k: None)
    stored = {}

    def fake_insert(cn, project, desk, status, body):
        stored["body"] = body
        return [{"id": 8}]

    monkeypatch.setattr("agent_coord.server.records.todo.insert", fake_insert)
    book = MagicMock()
    rec = rpc._h_open(book, {"need": "cap-empty", "detail": ""}, "the-mill", "me")
    assert rec["detail"] == ""
    assert json.loads(stored["body"])["detail"] == ""


def test_open_counts_multibyte_detail_as_characters(monkeypatch) -> None:
    """#188: the cap is characters, matching VARCHAR, not UTF-8 bytes."""
    monkeypatch.setattr(rpc, "_poke", lambda *a, **k: None)
    monkeypatch.setattr("agent_coord.server.records.name.ensure_roster", lambda *a, **k: None)
    monkeypatch.setattr("agent_coord.server.records.todo.find", lambda *a, **k: None)
    stored = {}

    def fake_insert(cn, project, desk, status, body):
        stored["body"] = body
        return [{"id": 11}]

    monkeypatch.setattr("agent_coord.server.records.todo.insert", fake_insert)
    book = MagicMock()
    kept = "é" * 500
    assert len(kept) == 500
    assert len(kept.encode("utf-8")) == 1000
    rec = rpc._h_open(book, {"need": "cap-mb", "detail": kept}, "the-mill", "me")
    assert rec["detail"] == kept
    assert json.loads(stored["body"])["detail"] == kept
    short = "é" * 250
    assert len(short.encode("utf-8")) == 500
    rec = rpc._h_open(book, {"need": "cap-mb-bytes", "detail": short}, "the-mill", "me")
    assert rec["detail"] == short
    with pytest.raises(CoordError, match="max 4096"):
        rpc._h_open(book, {"need": "cap-mb-over", "detail": "é" * 4097}, "the-mill", "me")


def test_open_keeps_detail_at_500(monkeypatch) -> None:
    monkeypatch.setattr(rpc, "_poke", lambda *a, **k: None)
    monkeypatch.setattr("agent_coord.server.records.name.ensure_roster", lambda *a, **k: None)
    monkeypatch.setattr("agent_coord.server.records.todo.find", lambda *a, **k: None)
    stored = {}

    def fake_insert(cn, project, desk, status, body):
        stored["body"] = body
        return [{"id": 7}]

    monkeypatch.setattr("agent_coord.server.records.todo.insert", fake_insert)
    book = MagicMock()
    rec = rpc._h_open(book, {"need": "cap-500", "detail": "d" * 500}, "the-mill", "me")
    assert rec["detail"] == "d" * 500
    assert json.loads(stored["body"])["detail"] == "d" * 500


def test_pack_small_roundtrip() -> None:
    payload = {"slug": "n", "doing": "hi", "detail": "seed"}
    assert json.loads(rec_todo.pack(payload)) == payload


def test_pack_long_detail_keeps_newest_tail() -> None:
    payload = {
        "slug": "note-cap",
        "doing": "d" * 200,
        "detail": ("A" * 4000) + "NEW-TAIL",
        "progress": "1/2",
    }
    raw = rec_todo.pack(payload)
    assert len(raw) <= rec_todo.BODY_MAX
    got = json.loads(raw)
    assert got["slug"] == "note-cap"
    assert got["doing"] == "d" * 200
    assert got["detail"].endswith("NEW-TAIL")
    assert not got["detail"].startswith("A" * 4000)


def test_update_rejects_oversize_body() -> None:
    with pytest.raises(CoordError, match="4096"):
        rec_todo.update(None, 1, "DESK_a", body="x" * 4097)


def _fit_detail(slug: str, doing: str, extra: int) -> str:
    """Longest 'a' detail whose stored JSON is BODY_MAX, plus extra chars."""
    payload = {"slug": slug, "doing": doing, "detail": ""}
    lo, hi, best = 0, rec_todo.BODY_MAX, 0
    while lo <= hi:
        mid = (lo + hi) // 2
        payload["detail"] = "a" * mid
        if len(json.dumps(payload)) <= rec_todo.BODY_MAX:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return "a" * (best + extra)


def test_stored_body_boundary() -> None:
    payload = {"slug": "n", "doing": "", "detail": _fit_detail("n", "", 0)}
    raw = rec_todo.stored_body(payload)
    assert len(raw) == rec_todo.BODY_MAX
    assert json.loads(raw)["detail"] == payload["detail"]
    payload["detail"] = _fit_detail("n", "", 1)
    with pytest.raises(CoordError, match="nothing trimmed"):
        rec_todo.stored_body(payload)
