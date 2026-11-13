"""Card 1192: waiting_on_it.letters gains oldest_at and n_over_day.

oldest_at is the office-clock time of the oldest letter still waiting, the
same 19-character cut claimed_at uses, and empty when none are waiting.
n_over_day counts letters that have waited more than one day on that clock.
n and newest stay as they are. A copy never waits, so it never counts.
"""
from __future__ import annotations

import pytest

from agent_coord.server.records.db import rows_done
from tests.server.records.conftest import seed_names
from tests.server.records.test_doing_flag_818 import World, _dispatch

pytestmark = pytest.mark.sql

ME = "d1192-me"
PEER = "d1192-peer"
R = "r1192"


def _stamp(cn, mid: int, interval: str) -> str:
    cur = cn.cursor()
    try:
        cur.execute(
            f"UPDATE mail SET created = MILL_NOW() - INTERVAL {interval} WHERE id = %s",
            (int(mid),),
        )
        cn.commit()
    finally:
        cur.close()
    got = rows_done(cn, "SELECT created FROM mail WHERE id = %s", (int(mid),))
    return str(got[0]["created"])[:19]


@pytest.fixture(scope="module")
def w(cn, tmp_path_factory):
    from agent_coord.client.tokens import token_hash
    from agent_coord.server.records import join as here

    seed_names(cn, (R, "roster"), ("the-mill", "roster"), (ME, "desk"), (PEER, "desk"))
    for desk in (ME, PEER):
        here.upsert(cn, R, desk, "builder", token_hash=token_hash("tok-" + desk), doing="present")
    mp = pytest.MonkeyPatch()
    world = World(cn, tmp_path_factory.mktemp("d1192"))
    mp.setenv("AGENT_COORD_MILL_HOME", str(tmp_path_factory.mktemp("d1192home")))
    mp.setenv("AGENT_COORD_MILL_URL", "http://127.0.0.1:9")
    mp.setattr("agent_coord.client.http.mill_http_call", lambda body: _dispatch(world, body))
    mp.setattr("agent_coord.server.api.mill.rpc._require_live_ws", lambda owner: None)
    for mod in ("agent_coord.client.http", "agent_coord.client.outbound"):
        mp.setattr(mod + ".resolve_desk_owner", lambda cli="": world.desk, raising=False)
    yield world
    mp.undo()


def test_oldest_at_and_n_over_day_pin_the_office_clock(w):
    old = w.letter(to=ME, desk=PEER)
    recent = w.letter(to=ME, desk=PEER)
    fresh = w.letter(to=ME, desk=PEER)
    oldest = _stamp(w.cn, old, "2 DAY")
    _stamp(w.cn, recent, "23 HOUR")

    letters = w.me(ME)["waiting_on_it"]["letters"]
    assert letters["n"] == 3
    assert letters["n_over_day"] == 1
    assert letters["oldest_at"] == oldest
    assert len(letters["oldest_at"]) == 19
    assert letters["newest"][0] == {
        "id": f"mail-{fresh}",
        "from": PEER,
        "age": letters["newest"][0]["age"],
        "asked": True,
    }
    assert [x["id"] for x in letters["newest"]] == [f"mail-{fresh}", f"mail-{recent}", f"mail-{old}"]

    none = w.me(PEER)["waiting_on_it"]["letters"]
    assert none["n"] == 0 and none["n_over_day"] == 0 and none["oldest_at"] == "" and none["newest"] == []
