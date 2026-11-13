"""#818 D2 on a real book: a card keeps the time it was claimed. Row F120.

(a) claim, claim --take-over, assign and a pass --back that puts the card
    back to claimed set todo.claimed_at; a note, an eta or a second claim by
    the same desk leaves it; unclaim, pass and pass --done clear it;
(b) card 1207: `mill connected` no longer lists cards waiting on a desk (waiting_on_it is gone);
(c) on an existing book `migrate.ensure()` adds the column and backfills
    every claimed card from its volunteer's watcher row (written on the
    volunteer's first write on the card: the claim, or the create when it
    filed the card), capped at todo.updated, else todo.updated; cards that are
    not claimed stay NULL. A second ensure changes nothing, and a run killed
    after the column was added converges.
"""
from __future__ import annotations

import pytest

from agent_coord.install import migrate
from agent_coord.server.records.db import rows_done, scalar_done
from tests.server.records.conftest import seed_names
from tests.server.records.test_doing_only_tw_1207 import World, _dispatch

pytestmark = pytest.mark.sql

ME = "d818c-me"
PEER = "d818c-peer"
R = "r1207"  # World.card files cards on the shared harness roster


class W(World):
    """World with this module's desks as the defaults."""

    def ok(self, argv, desk=ME):
        return super().ok(argv, desk)

    def me(self, desk=ME):
        return super().me(desk)

    def card(self, desk=PEER, **kw):
        return super().card(desk=desk, **kw)


@pytest.fixture(scope="module")
def w(cn, tmp_path_factory):
    from agent_coord.client.tokens import token_hash
    from agent_coord.server.records import join as here

    seed_names(cn, (R, "roster"), ("the-mill", "roster"), (ME, "desk"), (PEER, "desk"))
    for d in (ME, PEER):
        here.upsert(cn, R, d, "builder", token_hash=token_hash("tok-" + d))
    mp = pytest.MonkeyPatch()
    world = W(cn, tmp_path_factory.mktemp("d818c"))
    mp.setenv("AGENT_COORD_MILL_HOME", str(tmp_path_factory.mktemp("d818chome")))
    mp.setenv("AGENT_COORD_MILL_URL", "http://127.0.0.1:9")
    mp.setattr("agent_coord.client.http.mill_http_call", lambda body: _dispatch(world, body))
    mp.setattr("agent_coord.server.api.mill.rpc._require_live_ws", lambda owner: None)
    for mod in ("agent_coord.client.http", "agent_coord.client.outbound"):
        mp.setattr(mod + ".resolve_desk_owner", lambda cli="": world.desk, raising=False)
    yield world
    mp.undo()


def _card(w, desk=PEER) -> tuple[str, int]:
    return w.card(desk=desk)


def _row(cn, tid: int) -> dict:
    return rows_done(cn, "SELECT status, updated, claimed_at FROM todo WHERE id = %s", (tid,))[0]


def _exec(cn, sql: str, args: tuple = ()) -> None:
    cur = cn.cursor()
    try:
        cur.execute(sql, args)
        cn.commit()
    finally:
        cur.close()


def _back(cn, tid: int, hours: int) -> None:
    """Move the card's claim and its last change back in time (the clock stands still in a test)."""
    has = int(scalar_done(
        cn,
        "SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE()"
        " AND TABLE_NAME = 'todo' AND COLUMN_NAME = 'claimed_at'",
    ))
    claim = "claimed_at = claimed_at - INTERVAL %s HOUR, " if has else ""
    args = (hours, hours, tid) if has else (hours, tid)
    _exec(cn, "UPDATE todo SET " + claim + "updated = updated - INTERVAL %s HOUR WHERE id = %s", args)


# (a) the writes ------------------------------------------------------------------

def test_claim_sets_it_and_a_note_or_a_second_claim_leaves_it(w):
    need, tid = _card(w)
    assert _row(w.cn, tid)["claimed_at"] is None
    w.ok(["claim", R, need])
    first = _row(w.cn, tid)["claimed_at"]
    assert first is not None
    w.ok(["todo", R, need, "--started"])
    w.ok(["claim", R, need, "--eta", "2h"])
    row = _row(w.cn, tid)
    assert row["claimed_at"] == first and row["updated"] > first


def test_unclaim_pass_and_done_clear_it(w):
    for how in ("unclaim", "pass", "done"):
        need, tid = _card(w)
        w.ok(["claim", R, need])
        if how == "done":
            w.ok(["pass", R, need])
            w.ok(["pass", R, need, "--back"])
            assert _row(w.cn, tid)["claimed_at"] is not None
            w.ok(["pass", R, need])
            w.ok(["pass", R, need, "--done"], desk=PEER)
        else:
            w.ok([how, R, need])
        assert _row(w.cn, tid)["claimed_at"] is None, how


def test_pass_back_to_claimed_sets_it_again(w):
    need, tid = _card(w)
    w.ok(["claim", R, need])
    w.ok(["pass", R, need])
    assert _row(w.cn, tid)["claimed_at"] is None
    w.ok(["pass", R, need, "--back"])
    row = _row(w.cn, tid)
    assert row["status"] == "claimed" and row["claimed_at"] is not None


def test_take_over_and_assign_set_it(w):
    need, tid = _card(w)
    w.ok(["claim", R, need])
    _back(w.cn, tid, 3)
    old = _row(w.cn, tid)["claimed_at"]
    w.ok(["claim", R, need, "--take-over"], desk=PEER)
    assert _row(w.cn, tid)["claimed_at"] > old
    need2, tid2 = _card(w)
    w.ok(["assign", R, need2, ME], desk=PEER)
    assert _row(w.cn, tid2)["claimed_at"] is not None


# (c) migration -------------------------------------------------------------------

def test_migration_backfills_claimed_cards_from_the_volunteer_watcher(w):
    mine, t_mine = _card(w, desk=ME)        # ME files and later claims it
    theirs, t_theirs = _card(w)  # ME's first write on it is the claim
    idle, t_idle = _card(w)
    _exec(w.cn, "UPDATE todo SET created = created - INTERVAL 4 HOUR WHERE id = %s", (t_mine,))
    _exec(w.cn, "UPDATE watcher SET updated = updated - INTERVAL 4 HOUR WHERE type = 'todo' AND id = %s", (t_mine,))
    w.ok(["claim", R, mine])
    w.ok(["claim", R, theirs])
    claim_theirs = _row(w.cn, t_theirs)["claimed_at"]
    w.ok(["todo", R, theirs, "--started"], desk=PEER)
    _exec(w.cn, "ALTER TABLE todo DROP COLUMN claimed_at")
    first = migrate.ensure(w.cn)
    assert "todo.claimed_at" in first["applied"]
    w_theirs = scalar_done(
        w.cn,
        "SELECT w.updated FROM watcher w JOIN name n ON n.id = w.desk_id"
        " WHERE w.type = 'todo' AND w.id = %s AND n.name = %s",
        (t_theirs, ME),
    )
    got = _row(w.cn, t_theirs)
    assert got["claimed_at"] == min(w_theirs, got["updated"])
    assert abs((got["claimed_at"] - claim_theirs).total_seconds()) < 1
    # A card the desk filed: its watcher row is the create (the best bound kept).
    got_mine = _row(w.cn, t_mine)
    assert got_mine["claimed_at"] < got_mine["updated"]
    assert _row(w.cn, t_idle)["claimed_at"] is None
    second = migrate.ensure(w.cn)
    assert not [a for a in second["applied"] if a.startswith("todo.claimed_at")]


def test_a_run_killed_after_the_column_was_added_converges(w):
    need, tid = _card(w)
    w.ok(["claim", R, need])
    _exec(w.cn, "ALTER TABLE todo DROP COLUMN claimed_at")
    _exec(w.cn, "ALTER TABLE todo ADD COLUMN claimed_at DATETIME(6) NULL")
    out = migrate.ensure(w.cn)
    assert "todo.claimed_at_backfill" in out["applied"]
    assert _row(w.cn, tid)["claimed_at"] is not None
    assert int(scalar_done(
        w.cn, "SELECT COUNT(*) FROM todo WHERE status = 'claimed' AND claimed_at IS NULL"
    )) == 0
