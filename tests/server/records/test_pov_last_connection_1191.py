"""Card 1191 on a real book: the Wall's station clock on GET /api/pov?part=desks. Row F-wall-station-clock.

GET /api/pov?part=desks
    every station of a live desk, whatever its age (no 1-day filter); retired
    desks (name.deleted) and System (id 0) stay out. Each row carries
    last_connected: the later of seat.time_connect and seat.time_disconnect as
    ISO 8601 UTC, null when the desk never connected; never seat.updated.
    recent_activity carries at, the activity row's updated, ISO 8601 UTC.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent_coord.server.records.db import rows_done, scalar_done
from tests.server.records.conftest import seed_names
from tests.server.records.test_doing_only_tw_1207 import World, _dispatch

pytestmark = pytest.mark.sql

R = "r1191"
LIVE = "d1191-live"
OLD = "d1191-old"
NEVER = "d1191-never"
GONE = "d1191-gone"
PEER = "d1191-peer"
ISO = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")


class _Office:
    def __init__(self, cn):
        self._cn = cn
        self._tokens: dict = {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _utc(epoch) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(int(float(epoch)), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _seat(cn, desk: str, connect: str | None, disconnect: str | None) -> None:
    """Stamp a seat's connect clocks and pin seat.updated far away from both."""
    cn.cursor().execute(
        "UPDATE seat j JOIN name n ON n.id = j.desk_id SET"
        " j.time_connect = " + (connect or "NULL") + ","
        " j.time_disconnect = " + (disconnect or "NULL") + ","
        " j.updated = '2001-01-01 00:00:00'"
        " WHERE n.type = 'desk' AND n.name = %s",
        (desk,),
    )
    cn.commit()


@pytest.fixture(scope="module")
def w(cn, tmp_path_factory):
    from agent_coord.client.tokens import token_hash
    from agent_coord.server.records import join as here

    seed_names(cn, (R, "roster"), ("the-mill", "roster"), *[(d, "desk") for d in (LIVE, OLD, NEVER, GONE, PEER)])
    for d in (LIVE, OLD, NEVER, GONE, PEER):
        here.upsert(cn, R, d, "builder", token_hash=token_hash("tok-" + d))
    mp = pytest.MonkeyPatch()
    world = World(cn, tmp_path_factory.mktemp("d1191"))
    mp.setenv("AGENT_COORD_MILL_HOME", str(tmp_path_factory.mktemp("d1191home")))
    mp.setenv("AGENT_COORD_MILL_URL", "http://127.0.0.1:9")
    mp.setattr("agent_coord.client.http.mill_http_call", lambda body: _dispatch(world, body))
    mp.setattr("agent_coord.server.api.mill.rpc._require_live_ws", lambda owner: None)
    for mod in ("agent_coord.client.http", "agent_coord.client.outbound"):
        mp.setattr(mod + ".resolve_desk_owner", lambda cli="": world.desk, raising=False)
    yield world
    mp.undo()


@pytest.fixture()
def wall(w, monkeypatch):
    import agent_coord.server.middleware as mw
    from agent_coord.lib.observe import parse_roots
    from agent_coord.server.asgi import make_asgi_app

    monkeypatch.setattr("agent_coord.server.admin.door.mode", lambda: "path")
    monkeypatch.setattr("agent_coord.server.allow.allowed", lambda *a, **k: True)
    monkeypatch.setattr(mw, "_office", lambda **k: _Office(w.cn))
    mw._floor_cache.clear()
    root = Path(__file__).resolve().parents[3]
    return TestClient(make_asgi_app(parse_roots(cwd=root), api_only=True))


def _json(wall, url: str):
    r = wall.get(url, headers={"Accept": "application/json"})
    assert r.status_code == 200, r.text
    got = r.json()
    if isinstance(got, dict):
        got.pop("mill", None)
        if set(got) == {"result"}:
            got = got["result"]
    return got


def _desks(wall) -> dict[str, dict]:
    got = _json(wall, "/api/pov?part=desks")
    return {row["name"]: row for row in got["rows"]}


def test_every_station_comes_back_with_its_last_connection(w, wall):
    cn = w.cn
    _seat(cn, LIVE, "mill_now() - INTERVAL 5 MINUTE", "mill_now() - INTERVAL 2 HOUR")
    _seat(cn, OLD, "mill_now() - INTERVAL 10 DAY", "mill_now() - INTERVAL 9 DAY")
    _seat(cn, NEVER, None, None)
    rows = _desks(wall)
    # the 1-day filter is gone: a desk last seen 9 days ago and one never seen are both listed
    assert {LIVE, OLD, NEVER} <= set(rows), sorted(rows)
    clock = {
        d: rows_done(cn, "SELECT UNIX_TIMESTAMP(j.time_connect) AS c, UNIX_TIMESTAMP(j.time_disconnect) AS x,"
                         " UNIX_TIMESTAMP(j.updated) AS u FROM seat j JOIN name n ON n.id = j.desk_id"
                         " WHERE n.type = 'desk' AND n.name = %s", (d,))[0]
        for d in (LIVE, OLD)
    }
    # live: its session's connect; disconnected: the later stamp; never: null
    assert rows[LIVE]["connected"] is True and rows[LIVE]["last_connected"] == _utc(clock[LIVE]["c"])
    assert rows[OLD]["connected"] is False and rows[OLD]["last_connected"] == _utc(clock[OLD]["x"])
    assert rows[NEVER]["last_connected"] is None
    # never seat.updated (pinned to 2001 above)
    for d in (LIVE, OLD):
        assert rows[d]["last_connected"] != _utc(clock[d]["u"])
        assert ISO.fullmatch(rows[d]["last_connected"])
    assert set(rows[LIVE]) == {"name", "connected", "lan_ip", "last_connected", "recent_activity", "n", "doings"}


def test_a_disconnect_older_than_its_connect_reads_the_connect(w, wall):
    _seat(w.cn, OLD, "mill_now() - INTERVAL 3 DAY", "mill_now() - INTERVAL 4 DAY")
    rows = _desks(wall)
    want = scalar_done(w.cn, "SELECT UNIX_TIMESTAMP(j.time_connect) FROM seat j JOIN name n ON n.id = j.desk_id"
                             " WHERE n.type = 'desk' AND n.name = %s", (OLD,))
    assert rows[OLD]["last_connected"] == _utc(want)


def test_retired_desks_and_system_stay_out(w, wall):
    cn = w.cn
    _seat(cn, GONE, "mill_now() - INTERVAL 1 MINUTE", None)
    assert GONE in _desks(wall)
    cn.cursor().execute("UPDATE name SET deleted = mill_now() WHERE type = 'desk' AND name = %s", (GONE,))
    cn.commit()
    import agent_coord.server.middleware as mw

    mw._floor_cache.clear()
    rows = _desks(wall)
    assert GONE not in rows
    # System has a seat (id 0, never connects) and is never a station
    assert scalar_done(cn, "SELECT COUNT(*) FROM seat WHERE desk_id = 0") == 1
    assert "System" not in rows


def test_recent_activity_carries_when(w, wall):
    mid = w.letter(to=PEER, desk=LIVE)
    rows = _desks(wall)
    ra = rows[LIVE]["recent_activity"]
    assert ra and ra["type"] == "mail" and int(ra["id"]) == mid, ra
    want = scalar_done(w.cn, "SELECT UNIX_TIMESTAMP(updated) FROM activity WHERE type = 'mail' AND id = %s", (mid,))
    assert ra["at"] == _utc(want) and ISO.fullmatch(ra["at"])

