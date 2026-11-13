"""Card 1204: mill member --all reuses list_rosters; default member is unchanged."""
from __future__ import annotations

from types import SimpleNamespace

from agent_coord.server.api.mill import rpc


class _Book:
    def __init__(self):
        self._cn = object()


def test_member_all_returns_list_rosters(monkeypatch) -> None:
    rows = [{"name": "Office", "desks": 2, "members": ["a", "b"]}]
    seen = {"select": 0, "list": 0}

    def _list(cn):
        seen["list"] += 1
        assert cn is book._cn
        return rows

    def _select(cn, group="", desk="", kind=""):
        seen["select"] += 1
        raise AssertionError("default select must not run for --all")

    monkeypatch.setattr("agent_coord.server.records.member.list_rosters", _list)
    monkeypatch.setattr("agent_coord.server.records.member.select", _select)
    book = _Book()
    out = rpc._h_member(book, {"verb": "member", "all": True}, "Office", "builder")
    assert out == rows and seen == {"select": 0, "list": 1}


def test_member_without_all_still_selects_the_caller(monkeypatch) -> None:
    mine = [SimpleNamespace(slot="Office")]
    seen = {}

    def _select(cn, group="", desk="", kind=""):
        seen["args"] = (group, desk, kind)
        return mine

    monkeypatch.setattr("agent_coord.server.records.member.select", _select)
    monkeypatch.setattr(
        "agent_coord.server.records.member.list_rosters",
        lambda cn: (_ for _ in ()).throw(AssertionError("list_rosters must not run")),
    )
    out = rpc._h_member(_Book(), {"verb": "member"}, "Office", "builder")
    assert out is mine and seen["args"] == ("", "builder", "")
