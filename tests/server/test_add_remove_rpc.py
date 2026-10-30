"""mill add|remove RPC (#265), unit level. SQL behavior: records/test_add_remove_265.py."""
from __future__ import annotations

import pytest

from agent_coord.helpers.errors import CoordError
from agent_coord.server.api.mill import rpc


class _Book:
    def __init__(self):
        self._cn = object()


@pytest.fixture
def live(monkeypatch):
    calls: dict[str, list] = {"hint": [], "del": [], "put": [], "drop": []}
    monkeypatch.setattr("agent_coord.server.records.label._activity_live", lambda *a, **k: True)
    names = {("builder", "desk"): 42, ("peer", "desk"): 43, ("crew", "roster"): 50}
    monkeypatch.setattr("agent_coord.server.records.name.get",
                        lambda cn, n, kind="": names.get((n, kind)))
    monkeypatch.setattr("agent_coord.server.records.watcher.set_hint",
                        lambda cn, t, i, d, h: calls["hint"].append((t, i, d, h)) or [{"ok": 1}])
    monkeypatch.setattr("agent_coord.server.records.watcher.delete",
                        lambda cn, t, i, d: calls["del"].append((t, i, d)) or [])
    monkeypatch.setattr("agent_coord.server.records.mail.to_node_put",
                        lambda cn, i, w: calls["put"].append((i, w)) or {"added": 1, "letters": 1, "desks": 1})
    monkeypatch.setattr("agent_coord.server.records.mail.to_node_delete",
                        lambda cn, i, w: calls["drop"].append((i, w)) or {"removed": 1})
    monkeypatch.setattr("agent_coord.server.records.mail.to_list", lambda *a, **k: [])
    monkeypatch.setattr("agent_coord.server.records.mail.letter_row", lambda *a, **k: None)
    monkeypatch.setattr("agent_coord.server.records.db.scalar", lambda *a, **k: 1)
    # Read access (#sec S-3) is covered in records/test_sec_mail_participant.py.
    monkeypatch.setattr("agent_coord.server.api.mill.rpc._mail_reader", lambda *a, **k: True)
    return calls


def _go(body, owner="builder"):
    return rpc._h_add_remove(_Book(), body, "the-mill", owner)


def test_add_watch_defaults_to_self_with_hint(live):
    out = _go({"verb": "add", "type": "todo", "id": 9, "hint": "need:detail"})
    assert (out["who"], out["kind"], out["hint"]) == ("builder", "desk", "need:detail")
    assert live["hint"] == [("todo", 9, 42, "need:detail")]


@pytest.mark.parametrize("typ,stored", [("todo", "todo"), ("doing", "doing"), ("hold", "hold"), ("score", "score")])
def test_every_non_mail_kind_is_a_watcher(live, typ, stored):
    _go({"verb": "add", "type": typ, "id": 3})
    _go({"verb": "remove", "type": typ, "id": 3})
    assert live["hint"][-1][:3] == (stored, 3, 42) and live["del"] == [(stored, 3, 42)]
    assert live["put"] == [] and live["drop"] == []


def test_mail_is_recipients_never_watchers(live):
    _go({"verb": "add", "type": "mail", "id": 7, "who": "peer"})
    _go({"verb": "remove", "type": "mail", "id": 7, "who": "crew"})
    assert live["put"] == [(7, 43)] and live["drop"] == [(7, 50)]
    assert live["hint"] == [] and live["del"] == []


@pytest.mark.parametrize("body,msg", [
    ({"verb": "add", "type": "mail", "id": 7, "hint": "x"}, "--hint"),
    ({"verb": "remove", "type": "todo", "id": 7, "hint": "x"}, "--hint"),
    ({"verb": "add", "type": "tree", "id": 1}, "TARGET is type:id"),
    ({"verb": "add", "type": "join", "id": 1}, "TARGET is type:id"),  # #818: join is no type now
    ({"verb": "remove", "type": "join", "id": 1}, "TARGET is type:id"),
    ({"verb": "add", "type": "todo", "id": 0}, "TARGET is type:id"),
    ({"verb": "add", "type": "todo", "id": "abc"}, "TARGET is type:id"),
    ({"verb": "add", "type": "todo", "id": 3, "who": "ghost"}, "no such desk or roster ghost"),
    ({"verb": "add", "type": "todo", "id": 3, "who": "x" * 65}, "WHO is a desk or roster"),
    ({"verb": "watcher", "type": "todo", "id": 3}, "command is add or remove"),
])
def test_refusals(live, body, msg):
    with pytest.raises(CoordError, match=msg):
        _go(body)
    assert not any(live.values())


def test_missing_activity_refused(live, monkeypatch):
    monkeypatch.setattr("agent_coord.server.records.label._activity_live", lambda *a, **k: False)
    with pytest.raises(CoordError, match="remove: no hold 5"):
        _go({"verb": "remove", "type": "hold", "id": 5})


def test_remove_when_not_watching_refused(live, monkeypatch):
    monkeypatch.setattr("agent_coord.server.records.db.scalar", lambda *a, **k: None)
    with pytest.raises(CoordError, match="builder is not watching todo:4"):
        _go({"verb": "remove", "type": "todo", "id": 4})
    assert live["del"] == []


def test_other_desk_and_roster_follow_member_add_trust(live, monkeypatch):
    monkeypatch.setenv("AGENT_COORD_TRUST", "limited")
    monkeypatch.setattr("agent_coord.server.admin.guard.is_role_admin", lambda cn, desk: False)
    for who in ("peer", "crew"):
        with pytest.raises(CoordError, match="Admin"):
            _go({"verb": "add", "type": "todo", "id": 3, "who": who})
    _go({"verb": "add", "type": "todo", "id": 3})  # self is always allowed
    monkeypatch.setenv("AGENT_COORD_TRUST", "high")
    _go({"verb": "add", "type": "todo", "id": 3, "who": "peer"})


def test_add_remove_are_rpc_commands_and_watcher_is_gone():
    assert rpc.HANDLERS["add"] is rpc._h_add_remove and rpc.HANDLERS["remove"] is rpc._h_add_remove
    assert "watcher" not in rpc.HANDLERS and not hasattr(rpc, "_h_watcher")


class _SqlRefusal(Exception):
    def __init__(self, msg, sqlstate="45000", errno=1644):
        super().__init__(f"{errno} ({sqlstate}): {msg}")
        self.msg, self.sqlstate, self.errno = msg, sqlstate, errno


@pytest.mark.parametrize("command,patch", [
    ("add", "agent_coord.server.records.mail.to_node_put"),
    ("remove", "agent_coord.server.records.mail.to_node_delete"),
])
def test_sql_signal_becomes_one_plain_line_270(live, monkeypatch, command, patch):
    def boom(*a, **k):
        raise _SqlRefusal("remove: not a recipient on this letter or under it")
    monkeypatch.setattr(patch, boom)
    with pytest.raises(CoordError) as ei:
        _go({"verb": command, "type": "mail", "id": 7, "who": "peer"})
    assert str(ei.value) == "remove: not a recipient on this letter or under it"


@pytest.mark.parametrize("sqlstate,errno", [("22001", 1406), ("HY000", 2013)])
def test_other_sql_errors_are_not_dressed_as_refusals_270(live, monkeypatch, sqlstate, errno):
    def boom(*a, **k):
        raise _SqlRefusal("raw", sqlstate=sqlstate, errno=errno)
    monkeypatch.setattr("agent_coord.server.records.mail.to_node_delete", boom)
    with pytest.raises(_SqlRefusal):
        _go({"verb": "remove", "type": "mail", "id": 7, "who": "peer"})


def test_empty_signal_text_is_not_swallowed_270(live, monkeypatch):
    def boom(*a, **k):
        raise _SqlRefusal("")
    monkeypatch.setattr("agent_coord.server.records.mail.to_node_delete", boom)
    with pytest.raises(_SqlRefusal):
        _go({"verb": "remove", "type": "mail", "id": 7, "who": "peer"})


@pytest.mark.parametrize("command,args", [
    ("add", {"type": "join", "id": 3}),
    ("remove", {"type": "join", "id": 3}),
    ("label-add", {"type": "join", "id": 3, "label": "x"}),
    ("move", {"type": "join", "id": 3, "type_b": "join"}),
])
def test_old_client_join_type_over_ws_names_the_upgrade(live, command, args):
    """#818: a 0.7.15 client still sends TYPE join; the refusal names the upgrade, nothing runs."""
    with pytest.raises(CoordError, match="pip install -U the-mill"):
        rpc.dispatch_ws(_Book(), "builder", command, dict(args))
    assert live["hint"] == [] and live["del"] == [] and live["put"] == [] and live["drop"] == []
