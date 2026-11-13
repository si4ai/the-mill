"""Bare `mill hold` lists every lock; a peek at a name never taken hints (#326)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from agent_coord.client import outbound
from agent_coord.server.api.mill import rpc


def _args(**kw):
    base = dict(cmd="hold", project="", resource="", peek=False, doing="")
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture
def _me(monkeypatch):
    monkeypatch.setattr("agent_coord.client.tokens.resolve_desk_owner", lambda _x="": "alice")


def test_bare_hold_is_the_list(_me):
    body = outbound.body_from_args(_args())
    assert body["peek"] is True
    assert "resource" not in body


def test_hold_has_no_doing_flag(_me):
    # Card 1207: hold only does hold; the parser refuses --doing and the body never carries it.
    from agent_coord.__main__ import _build_parser

    with pytest.raises(SystemExit):
        _build_parser().parse_args(["hold", "a.md", "--doing", "x"])
    assert "doing" not in outbound.body_from_args(_args(resource="a.md", doing="x"))


def test_hold_with_resource_still_acquires(_me):
    body = outbound.body_from_args(_args(resource="docs/a.md"))
    assert body["resource"] == "docs/a.md"
    assert "peek" not in body


def test_parser_accepts_bare_hold():
    from agent_coord.__main__ import _build_parser

    a = _build_parser().parse_args(["hold"])
    assert a.cmd == "hold" and a.resource == "" and a.peek is False


def _server(monkeypatch, rows, roster_names=()):
    monkeypatch.setattr(rpc, "_require_live_project", lambda *a, **k: None)
    monkeypatch.setattr("agent_coord.server.records.hold.find", lambda cn, **kw: list(rows))

    def fake_get(cn, name, kind):
        return 7 if name in roster_names or name == "Office" else None

    monkeypatch.setattr("agent_coord.server.records.name.get", fake_get)


def test_server_lists_when_no_resource_even_without_peek(monkeypatch):
    _server(monkeypatch, [{"resource": "deploy", "desk": "w3", "id": 85, "updated": "t"}])
    out = rpc._h_hold(MagicMock(), {}, "", "alice")
    assert [h["resource"] for h in out["holds"]] == ["deploy"]


def test_peek_at_roster_name_hints_the_list(monkeypatch):
    _server(monkeypatch, [], roster_names=("cold-test",))
    out = rpc._h_hold(MagicMock(), {"peek": True, "resource": "cold-test"}, "", "alice")
    assert out["held"] is False and out["id"] is None
    assert "no hold named cold-test" in out["hint"]
    assert "is a roster" in out["hint"]
    assert "mill hold --peek" in out["hint"]


def test_peek_at_never_taken_name_hints(monkeypatch):
    _server(monkeypatch, [])
    out = rpc._h_hold(MagicMock(), {"peek": True, "resource": "nope"}, "", "alice")
    assert "no hold named nope" in out["hint"]
    assert "roster" not in out["hint"]


def test_peek_at_real_hold_has_no_hint(monkeypatch):
    _server(monkeypatch, [{"resource": "deploy", "desk": "w3", "id": 85, "updated": "t"}])
    out = rpc._h_hold(MagicMock(), {"peek": True, "resource": "deploy"}, "", "alice")
    assert out["owner"] == "w3" and "hint" not in out
