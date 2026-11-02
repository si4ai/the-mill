"""#707: an over-limit score note is refused with the limit in plain words, no book text.

Card 1021: desks no longer write scores; the note limit lives on records.point_add
(the server write path).
"""
from __future__ import annotations

import pytest

from agent_coord.helpers.errors import CoordError
from agent_coord.server import score_series as ss
from agent_coord.server.records import score as rec_score


def test_note_limit_matches_the_column():
    assert ss.NOTE_MAX == 200


def test_long_note_refused_with_the_limit(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("over-limit note must not reach the book")

    monkeypatch.setattr("agent_coord.server.records.db.call", boom)
    with pytest.raises(CoordError) as ei:
        rec_score.point_add(None, "unit", "d1", "x", 1.0, note="n" * 201)
    msg = str(ei.value)
    assert msg == "score: --note is 201 characters; the most is 200, one line; nothing stored"
    assert "1406" not in msg and "p_note" not in msg


def test_note_at_the_limit_is_recorded(monkeypatch):
    calls: list[str] = []

    def fake_call(cn, sp, args):
        calls.append(args[5])
        return [{"id": 7, "point_id": 1}]

    monkeypatch.setattr(rec_score, "call", fake_call)
    monkeypatch.setattr("agent_coord.server.records.name.bare", lambda n, t: n)
    out = rec_score.point_add(None, "unit", "d1", "x", 1.0, note="n" * 200)
    assert calls == ["n" * 200]
    assert out[0]["id"] == 7


def test_help_names_the_limit():
    from agent_coord.__main__ import _build_parser

    sub = next(a for a in _build_parser()._actions if a.dest == "cmd" or getattr(a, "choices", None))
    score = sub.choices["score"]
    note = next(a for a in score._actions if "--note" in a.option_strings)
    assert "200" in note.help
