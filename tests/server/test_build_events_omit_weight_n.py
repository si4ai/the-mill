"""Floor events omit activity weight and n (dropped in 0.8.0)."""
from __future__ import annotations


def test_build_events_omits_weight_and_n(monkeypatch) -> None:
    from agent_coord.server.records import floor

    def _select(cn, desk_id, limit):
        del cn, desk_id, limit
        return [
            {
                "id": 9,
                "type": "todo",
                "updated": "2026-10-30 00:00:00.000000",
                "desk": "desk-a",
                "roster": "roster-a",
                "desk_id": 2,
                "weight": 3,
                "n": 4,
                "state": "deleted",
            }
        ]

    monkeypatch.setattr(floor.rec_activity, "select", _select)
    evs = floor.build_events(object(), [], None)
    assert len(evs) == 1
    ev = evs[0]
    assert ev["id"] == 9
    assert ev["type"] == "todo"
    assert ev["state"] == "deleted"
    assert "weight" not in ev
    assert "n" not in ev
