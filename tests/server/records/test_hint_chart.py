# -*- coding: utf-8 -*-
"""HINT chart regression: real watcher rows, default detail, and one custom recipe per activity.

hints.md default-by-activity plus the example watcher.hint strings.
DOING is pushed and dispatch ignores it. A name is not a watcher target.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.sql

from agent_coord.client.dispatch import dispatch_hint
from agent_coord.server.records.db import conn_kwargs as _conn_kwargs
from agent_coord.server.records import hold, join as here, member, name, score, todo, watcher as watchers
from agent_coord.helpers.ident import desk
from agent_coord.server import push
from agent_coord.server.push import fanout

PROGRAM = Path(__file__).resolve().parents[2] / "programs" / "hint_check.py"
_spec = importlib.util.spec_from_file_location("hint_check", PROGRAM)
assert _spec and _spec.loader
_hint_check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_hint_check)
check_frame = _hint_check.check_frame

from tests.server.records.conftest import make_admin

# Activity, chart hint, example recipe from hints.md.
CHART = [
    ("todo", "TODO", "need,status"),
    ("hold", "HOLD", "resource,desk"),
    ("score", "SCORE", "kpi,value,target"),
]

def _sit(cn, who: str = "alice"):
    project = "unit"
    stored = who
    rec = here.upsert(cn, project, stored, "builder", token_hash="a" * 64)
    return project, stored, rec

def _frames(cn, typ: str, nid: int) -> dict[str, dict]:
    rows = watchers.select(cn, typ, int(nid)) or []
    assert rows, f"no watchers type={typ} id={nid}"
    notified: list[tuple[str, dict]] = []

    def capture(room, payload, row=None):  # row: #832 settle key
        notified.append((str(room), dict(payload)))

    rooms = {desk(str(r.get("desk") or "")): {object()} for r in rows}
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(push.HUB, "rooms", rooms)
        mp.setattr(push.HUB, "notify", capture)
        fanout(cn, typ, int(nid), typ.upper())
    return {room: payload for room, payload in notified}

def _desk_id(cn, stored: str) -> int:
    nid = name.get(cn, stored, "desk")
    assert nid, stored
    return int(nid)

@pytest.mark.parametrize("typ,hint,recipe", CHART)
def test_default_then_custom_recipe(cn, typ, hint, recipe) -> None:
    project, alice, _ = _sit(cn)
    bob = "bob"
    here.upsert(cn, project, bob, "builder", token_hash="b" * 64)
    if typ == "todo":
        nid = int(todo.insert(cn, project, alice, "open", '{"slug":"chart"}')[0]["id"])
    elif typ == "hold":
        nid = int(hold.upsert(cn, project, alice, "chart-res")[0]["id"])
    else:
        nid = int(score.upsert(cn, project, alice, "chart-kpi", "1", "1", "ok")[0]["id"])

    frames = _frames(cn, typ, nid)
    assert frames, typ
    for payload in frames.values():
        assert payload["hint"] == hint
        check_frame(payload)
    assert desk(bob) not in frames
    watchers.put(cn, typ, nid, _desk_id(cn, bob))

    watchers.set_hint(cn, typ, nid, _desk_id(cn, alice), recipe)
    frames = _frames(cn, typ, nid)
    alice_frame = frames[desk(alice)]
    assert alice_frame["hint"] == hint
    assert alice_frame["detail"] == recipe
    check_frame(alice_frame, recipe)
    others = [p for room, p in frames.items() if room != desk(alice)]
    assert others, f"{typ} needs a second watcher still on the default"
    for payload in others:
        check_frame(payload)

    watchers.set_hint(cn, typ, nid, _desk_id(cn, alice), "")
    frames = _frames(cn, typ, nid)
    check_frame(frames[desk(alice)])

def test_name_member_does_not_push_a_name_hint(cn) -> None:
    _sit(cn)
    bob = "bob"
    here.upsert(cn, "unit", bob, "builder", token_hash="b" * 64)
    name.host_put(cn, "chart", "roster")
    member.put(cn, "chart", "alice")
    member.put(cn, "chart", bob)
    nid = int(name.get(cn, "chart", "roster"))
    with pytest.raises(Exception):
        watchers.select(cn, "name", nid)
    with pytest.raises(Exception):
        watchers.set_hint(cn, "name", nid, _desk_id(cn, "alice"), "slug")
    cur = cn.cursor()
    try:
        cur.execute("SELECT DISTINCT type FROM watcher")
        types = {str(r[0]) for r in cur.fetchall()}
    finally:
        cur.close()
    assert "name" not in types

def test_label_create_does_not_push_a_name_hint(cn) -> None:
    project, alice, _ = _sit(cn)
    from agent_coord.server.api.mill import rpc

    class Book:
        def __init__(self, conn):
            self._cn = conn

    notified: list[tuple[str, dict]] = []

    def capture(desk, payload, row=None):  # row: #832 settle key
        notified.append((str(desk), dict(payload)))

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("agent_coord.server.admin.catalog.require_admin", lambda *a, **k: None)
        mp.setattr(push.HUB, "rooms", {desk(alice): {object()}})
        mp.setattr(push.HUB, "notify", capture)
        rpc._h_label_name(
            Book(cn),
            {"verb": "label", "slug": "chart-label", "confirm": "chart-label", "yes": True},
            project,
            "alice",
        )
    assert notified == []
    nid = int(name.get(cn, "chart-label", "label"))
    assert nid
    with pytest.raises(Exception):
        watchers.set_hint(cn, "name", nid, _desk_id(cn, alice), "slug")

def test_label_retire_does_not_push_a_name_hint(cn) -> None:
    project, alice, _ = _sit(cn)
    from agent_coord.server.api.mill import rpc

    class Book:
        def __init__(self, conn):
            self._cn = conn

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("agent_coord.server.admin.catalog.require_admin", lambda *a, **k: None)
        mp.setattr(push.HUB, "rooms", {})
        mp.setattr(push.HUB, "notify", lambda *a, **k: None)
        rpc._h_label_name(
            Book(cn),
            {"verb": "label", "slug": "chart2", "confirm": "chart2", "yes": True},
            project,
            "alice",
        )
    nid = int(name.get(cn, "chart2", "label"))
    notified: list[tuple[str, dict]] = []

    def capture(desk, payload, row=None):  # row: #832 settle key
        notified.append((str(desk), dict(payload)))

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("agent_coord.server.admin.catalog.require_admin", lambda *a, **k: None)
        mp.setattr(push.HUB, "rooms", {desk(alice): {object()}})
        mp.setattr(push.HUB, "notify", capture)
        make_admin(cn, alice)  # 0.8.0: sp_name_retire checks the acting desk is Admin
        rpc._h_retire(
            Book(cn),
            {"verb": "retire", "slug": "chart2", "confirm": "chart2", "yes": True},
            project,
            "alice",
        )
    assert notified == []
    assert name.get(cn, "chart2", "label") is None
    assert nid

def test_doing_watch_frames_default_then_custom_and_dispatch_ignores(cn) -> None:
    """Card 1207: a doing is a tw run; a watcher on it gets DOING frames (default, then its own hint)."""
    _, alice, _ = _sit(cn)
    from agent_coord.server.records.db import call

    jid = int(call(cn, "mill_doing_task", [alice, f"task:{alice}:chart", None, 1])[0]["id"])
    watchers.put(cn, "doing", jid, _desk_id(cn, alice))
    frames = _frames(cn, "doing", jid)
    assert frames[desk(alice)]["hint"] == "DOING"
    check_frame(frames[desk(alice)])
    assert dispatch_hint(alice, frames[desk(alice)]) == "skip"

    watchers.set_hint(cn, "doing", jid, _desk_id(cn, alice), "session")
    frames = _frames(cn, "doing", jid)
    assert frames[desk(alice)]["detail"] == "session"
    assert frames[desk(alice)]["hint"] == "DOING"
    check_frame(frames[desk(alice)], "session")
    assert dispatch_hint(alice, frames[desk(alice)]) == "skip"

def test_note_connect_pushes_no_doing(cn) -> None:
    """Card 1207: a connect writes no doing row, so it pushes no DOING to anyone."""
    _, alice, _ = _sit(cn)
    bob = "bob"
    here.upsert(cn, "unit", bob, "builder", token_hash="b" * 64)
    notified: list[tuple[str, dict]] = []

    def capture(room, payload, row=None):  # row: #832 settle key
        notified.append((str(room), dict(payload)))

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(push.HUB, "rooms", {desk(alice): {object()}, desk(bob): {object()}})
        mp.setattr(push.HUB, "notify", capture)
        here.note_connect(cn, alice)
    assert [p for _, p in notified if p.get("hint") == "DOING"] == []

def test_dispatch_ignores_ping_and_doing() -> None:
    assert dispatch_hint("alice", {"type": "heartbeat", "id": 0, "hint": "PING"}) == "skip"
    assert dispatch_hint("alice", {"type": "doing", "id": 1, "hint": "DOING", "detail": "{}"}) == "skip"

def test_dispatch_doing_route_still_runs(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)
    from agent_coord.client.route_chain import save_routes

    stamp = tmp_path / "doing.json"
    save_routes(
        "alice",
        {"doing:DOING": subprocess.list2cmdline([sys.executable, str(PROGRAM), "--stamp", str(stamp)])},
    )
    kind = dispatch_hint(
        "alice",
        {"type": "doing", "id": 3, "hint": "DOING", "detail": '{"what":"doing","id":3,"when":"t","watchers":1,"tree":[]}'},
    )
    assert kind == "work"
