"""Card 1021: desks only read scores; server writes them."""
from __future__ import annotations

import pytest

from agent_coord.helpers.errors import CoordError
from agent_coord.server.api.mill import rpc


class _Book:
    _cn = None


@pytest.fixture
def locked(monkeypatch):
    """Any desk write path must refuse before touching the book."""
    from agent_coord.server.records import score as rec_score

    def boom(*a, **k):
        raise AssertionError("desk score write must not reach records")

    monkeypatch.setattr(rec_score, "point_add", boom)
    monkeypatch.setattr(rec_score, "define", boom)
    monkeypatch.setattr(rec_score, "retire", boom)
    monkeypatch.setattr(rpc, "_poke", boom)
    return rpc


def test_desk_value_write_is_refused_and_names_the_read_verb(locked) -> None:
    with pytest.raises(CoordError, match=r"desks only read scores; use mill score unit tokens\.loop"):
        locked._h_score(_Book(), {"name": "tokens.loop", "value": "1"}, "unit", "d1")


def test_desk_define_and_retire_are_refused(locked) -> None:
    with pytest.raises(CoordError, match=r"desks only read scores; use mill score unit ms\.read"):
        locked._h_score(
            _Book(), {"name": "ms.read", "target": "50", "better": "down", "unit": "ms"}, "unit", "d1"
        )
    with pytest.raises(CoordError, match=r"desks only read scores; use mill score unit probe"):
        locked._h_score(_Book(), {"name": "probe", "retire": True}, "unit", "d1")


def test_desk_read_still_works(monkeypatch) -> None:
    from agent_coord.server import score_series as ss
    from agent_coord.server.records import score as rec_score

    def points(cn, project, kpi="", limit=10):
        return [
            {
                "id": 1,
                "kpi": "tokens.loop",
                "better": "down",
                "unit": "tokens",
                "target": "500",
                "owner": "d1",
                "latest": "880",
                "point_id": 1,
                "v": 880.0,
                "desk": "d1",
                "at": "2026-11-01 12:00:00",
                "note": "",
            }
        ]

    monkeypatch.setattr(rec_score, "points", points)
    out = rpc._h_score(_Book(), {"name": "tokens.loop", "limit": 2}, "unit", "d1")
    assert out["score"] == "tokens.loop"
    assert out["latest"] == 880
