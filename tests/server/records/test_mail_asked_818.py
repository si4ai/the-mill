"""#818 D1 on a real book: mail_to says whether a desk was asked or copied. Row F119.

(a) send names every recipient: a desk To, each --to-desk and each member of
    a roster To are asked;
(b) reply-all asks the parent's sender and copies every other desk it reaches
    only as a room member (the parent's other recipients and the room cast);
    reply --to-desk asks every desk it names. The same split the wakes use
    (#627 room_only), now stored;
(c) `mill connected` counts only unhandled letters the desk was asked on as
    waiting on it; a copy never does;
(d) on an existing book `migrate.ensure()` adds the column: old rows are
    asked unless the stored wake for that letter and desk (wake,
    wake_reason room) says the desk got it as a room member; a second ensure
    changes nothing, and a run killed after the column was added converges.
"""
from __future__ import annotations

import pytest

from agent_coord.install import migrate
from agent_coord.server.records.db import rows_done, scalar_done
from tests.server.records.conftest import seed_names
from tests.server.records.test_doing_flag_818 import World, _dispatch

pytestmark = pytest.mark.sql

ME = "d818a-me"
PEER = "d818a-peer"
THIRD = "d818a-third"
R = "r818a"


@pytest.fixture(scope="module")
def w(cn, tmp_path_factory):
    from agent_coord.client.tokens import token_hash
    from agent_coord.server.records import join as here

    seed_names(cn, (R, "roster"), ("the-mill", "roster"), (ME, "desk"), (PEER, "desk"), (THIRD, "desk"))
    for d in (ME, PEER, THIRD):
        here.upsert(cn, R, d, "builder", token_hash=token_hash("tok-" + d), doing="present")
    mp = pytest.MonkeyPatch()
    world = World(cn, tmp_path_factory.mktemp("d818a"))
    mp.setenv("AGENT_COORD_MILL_HOME", str(tmp_path_factory.mktemp("d818ahome")))
    mp.setenv("AGENT_COORD_MILL_URL", "http://127.0.0.1:9")
    mp.setattr("agent_coord.client.http.mill_http_call", lambda body: _dispatch(world, body))
    mp.setattr("agent_coord.server.api.mill.rpc._require_live_ws", lambda owner: None)
    for mod in ("agent_coord.client.http", "agent_coord.client.outbound"):
        mp.setattr(mod + ".resolve_desk_owner", lambda cli="": world.desk, raising=False)
    yield world
    mp.undo()


def _asked(cn, mid: int) -> dict[str, int]:
    rows = rows_done(
        cn,
        "SELECT n.name, mt.asked FROM mail_to mt JOIN name n ON n.id = mt.desk_id"
        " WHERE mt.type = 'mail' AND mt.id = %s",
        (int(mid),),
    )
    return {str(r["name"]): int(r["asked"]) for r in rows}


def _send(w, tos, desk=PEER) -> int:
    argv = ["send"]
    for t in tos:
        argv += ["--to-desk", t]
    res = w.ok(argv + ["--body-file", str(w.body)], desk=desk)
    return int(res["id"])


def _reply(w, mid, desk, tos=()) -> int:
    argv = ["reply", str(mid)]
    for t in tos:
        argv += ["--to-desk", t]
    return int(w.ok(argv + ["--body-file", str(w.body)], desk=desk)["id"])


def _waiting_ids(w, desk=ME) -> tuple[list[str], int]:
    view = w.me(desk)
    return [x["id"] for x in view["waiting_on_it"]["letters"]["newest"]], view["waiting_on_it"]["letters"]["n"]


# (a) send -----------------------------------------------------------------------

def test_send_asks_every_named_desk(w):
    mid = _send(w, [ME, THIRD])
    assert _asked(w.cn, mid) == {ME: 1, THIRD: 1}


def test_send_to_a_roster_asks_its_members(w):
    res = w.ok(["send", "roster", R, "--body-file", str(w.body)], desk=PEER)
    got = _asked(w.cn, int(res["id"]))
    assert got and set(got.values()) == {1} and ME in got and THIRD in got


# (b) reply ----------------------------------------------------------------------

def test_reply_all_asks_the_parent_sender_and_copies_the_room(w):
    root = _send(w, [ME, THIRD])
    r1 = _reply(w, root, THIRD)
    # THIRD answers PEER (named); ME was on the parent only, so a copy.
    assert _asked(w.cn, r1) == {PEER: 1, ME: 0}
    r2 = _reply(w, r1, ME)
    # ME answers THIRD (named); PEER is reached only through the room.
    assert _asked(w.cn, r2) == {THIRD: 1, PEER: 0}


def test_reply_to_desk_asks_every_named_desk(w):
    root = _send(w, [ME, THIRD])
    r1 = _reply(w, root, THIRD, tos=[PEER, ME])
    assert _asked(w.cn, r1) == {PEER: 1, ME: 1}


def test_wake_reason_and_stored_flag_agree(w):
    root = _send(w, [ME, THIRD])
    r1 = _reply(w, root, THIRD)
    rows = rows_done(
        w.cn,
        "SELECT n.name, JSON_UNQUOTE(JSON_EXTRACT(p.payload, '$.wake_reason')) AS why"
        " FROM wake p JOIN name n ON n.id = p.desk_id"
        " WHERE p.cause = 'mail' AND JSON_EXTRACT(p.payload, '$.id') = %s",
        (r1,),
    )
    wake = {str(r["name"]): (0 if r["why"] == "room" else 1) for r in rows}
    assert wake == _asked(w.cn, r1)


# (c) connected ------------------------------------------------------------------

def test_connected_counts_only_letters_the_desk_was_asked_on(w):
    root = _send(w, [ME, THIRD])
    copy = _reply(w, root, THIRD)  # ME is copied
    ids, n = _waiting_ids(w)
    assert f"mail-{root}" in ids
    # The copy is newer than root; before #818 D1 it led the list.
    assert f"mail-{copy}" not in ids
    # Asking the desk counts; the copy above it still does not.
    asked = _reply(w, copy, PEER, tos=[ME])
    ids2, n2 = _waiting_ids(w)
    assert ids2[0] == f"mail-{asked}" and f"mail-{copy}" not in ids2
    assert n2 == n + 1


# (d) migration ------------------------------------------------------------------

def _drop_column(cn) -> None:
    cur = cn.cursor()
    try:
        cur.execute("ALTER TABLE mail_to DROP COLUMN asked")
        cn.commit()
    finally:
        cur.close()


def test_migration_adds_asked_and_recovers_room_copies(w):
    root = _send(w, [ME, THIRD])
    copy = _reply(w, root, THIRD)
    before = _asked(w.cn, copy)
    assert before == {PEER: 1, ME: 0}
    _drop_column(w.cn)
    first = migrate.ensure(w.cn)
    assert "mail_to.asked" in first["applied"]
    # ME's stored wake on the copy says room, so it comes back copied.
    assert _asked(w.cn, copy) == before
    assert _asked(w.cn, root) == {ME: 1, THIRD: 1}
    col = rows_done(
        w.cn,
        "SELECT IS_NULLABLE, COLUMN_DEFAULT FROM information_schema.COLUMNS"
        " WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'mail_to' AND COLUMN_NAME = 'asked'",
    )
    assert col and col[0]["IS_NULLABLE"] == "NO" and str(col[0]["COLUMN_DEFAULT"]) == "1"
    second = migrate.ensure(w.cn)
    assert not [a for a in second["applied"] if a.startswith("mail_to.asked")]


def test_migration_without_a_stored_wake_defaults_to_asked(w):
    root = _send(w, [ME, THIRD])
    copy = _reply(w, root, THIRD)
    cur = w.cn.cursor()
    try:
        cur.execute("DELETE FROM wake WHERE cause = 'mail' AND JSON_EXTRACT(payload, '$.id') = %s", (copy,))
        w.cn.commit()
    finally:
        cur.close()
    _drop_column(w.cn)
    migrate.ensure(w.cn)
    assert _asked(w.cn, copy) == {PEER: 1, ME: 1}


def test_a_run_killed_after_the_column_was_added_converges(w):
    root = _send(w, [ME, THIRD])
    copy = _reply(w, root, THIRD)
    _drop_column(w.cn)
    cur = w.cn.cursor()
    try:
        # The first statement of the step ran; the backfill and the NOT NULL did not.
        cur.execute("ALTER TABLE mail_to ADD COLUMN asked TINYINT(1) NULL AFTER receipt")
        w.cn.commit()
    finally:
        cur.close()
    out = migrate.ensure(w.cn)
    assert "mail_to.asked_backfill" in out["applied"]
    assert _asked(w.cn, copy) == {PEER: 1, ME: 0}
    assert int(scalar_done(w.cn, "SELECT COUNT(*) FROM mail_to WHERE asked IS NULL")) == 0


# (e) the Wall reads it -------------------------------------------------------------

from tests.server.records.test_doing_routes_818 import _get, wall  # noqa: E402,F401


def test_waiting_letters_carry_asked_in_connected_and_the_wall_route(w, wall):  # noqa: F811
    mid = _send(w, [ME], desk=PEER)
    letters = w.me(ME)["waiting_on_it"]["letters"]["newest"]
    mine = [x for x in letters if x["id"] == f"mail-{mid}"]
    assert mine and mine[0]["asked"] is True
    assert all(x["asked"] is True for x in letters)  # a copy never waits, so every listed letter was asked
    code, got = _get(wall, f"/api/v1/doing?desk={ME}")
    assert code == 200, got
    route = got[0]["waiting_on_it"]["letters"]["newest"]
    assert route == letters and all(set(x) == {"id", "from", "age", "asked"} for x in route)
