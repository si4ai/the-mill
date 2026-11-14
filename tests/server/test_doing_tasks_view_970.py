"""Card 970 / card 1207: connected exposes only the desk part plus n and doings."""
from types import SimpleNamespace

from agent_coord.server.api.mill import rpc
from agent_coord.server.records import doing


def view(monkeypatch, live):
    monkeypatch.setattr(doing, "now", lambda *a: [
        {"part": "desk", "desk": "Builder", "heartbeat": None},
        {"part": "desk", "desk": "Validator", "heartbeat": None},
    ])
    monkeypatch.setattr(doing, "live_doings", lambda cn, desks: {d: live[d] for d in desks if d in live})
    return rpc._h_session(SimpleNamespace(_cn=None), {"all": True}, "", None)


def test_each_desk_gets_n_and_doings_and_nothing_from_the_dropped_columns(monkeypatch):
    row = {"id": 7, "created": "2026-11-13T14:00:00Z", "text": "", "state": "active",
           "state_at": "2026-11-13T14:01:00Z", "card": None}
    got = view(monkeypatch, {"Builder": {"n": 1, "doings": [row]}})
    assert got[0]["n"] == 1 and got[0]["doings"] == [row]
    assert got[1]["n"] == 0 and got[1]["doings"] == []
    for v in got:
        assert not {"doing", "on", "act", "age", "line", "tasks", "waiting_on", "waiting_on_it", "last"} & set(v)


def test_now_reads_only_the_desk_part(monkeypatch):
    desks = [{"part": "desk", "desk": role} for role in ("Builder", "Validator")]
    monkeypatch.setattr(doing, "call", lambda *a: list(desks))
    assert doing.now(None, all_desks=True) == desks
