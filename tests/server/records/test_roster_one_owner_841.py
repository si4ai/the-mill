"""The activity row carries the payload's roster (card 841, F134).

(a) `send --roster` tags the letter and its activity row with the same roster;
(b) the first reply under a letter (the write that roots its room) leaves the
    parent letter's activity roster alone;
(c) a card created under a parent card (`create todo --parent-type todo`)
    leaves the parent card's activity roster alone;
(d) `migrate.ensure` sets every mail and todo activity row back to its
    payload's roster, keeps `activity.updated`, and a second run changes nothing.
"""
from __future__ import annotations

import pytest

from agent_coord.install import migrate
from agent_coord.server.records import todo as rec_todo
from agent_coord.server.records.db import rows_done, scalar_done
from tests.server.records.conftest import seed_names
from tests.server.records.test_doing_flag_818 import World, _dispatch

pytestmark = pytest.mark.sql

ME = "d841-me"
PEER = "d841-peer"
R = "r841"
OTHER = "r841-other"


@pytest.fixture(scope="module")
def w(cn, tmp_path_factory):
    from agent_coord.client.tokens import token_hash
    from agent_coord.server.records import join as here

    seed_names(cn, (R, "roster"), (OTHER, "roster"), ("the-mill", "roster"), (ME, "desk"), (PEER, "desk"))
    for d in (ME, PEER):
        here.upsert(cn, R, d, "builder", token_hash=token_hash("tok-" + d), doing="present")
    mp = pytest.MonkeyPatch()
    world = World(cn, tmp_path_factory.mktemp("d841"))
    mp.setenv("AGENT_COORD_MILL_HOME", str(tmp_path_factory.mktemp("d841home")))
    mp.setenv("AGENT_COORD_MILL_URL", "http://127.0.0.1:9")
    mp.setattr("agent_coord.client.http.mill_http_call", lambda body: _dispatch(world, body))
    mp.setattr("agent_coord.server.api.mill.rpc._require_live_ws", lambda owner: None)
    for mod in ("agent_coord.client.http", "agent_coord.client.outbound"):
        mp.setattr(mod + ".resolve_desk_owner", lambda cli="": world.desk, raising=False)
    yield world
    mp.undo()


def _rosters(cn, typ: str, pid: int) -> tuple[str, str]:
    """(payload roster, activity roster) names for one mail or todo row."""
    row = rows_done(
        cn,
        f"SELECT pn.name AS payload, an.name AS activity FROM {typ} p"
        " JOIN activity a ON a.type = %s AND a.id = p.id"
        " JOIN name pn ON pn.id = p.roster_id JOIN name an ON an.id = a.roster_id"
        " WHERE p.id = %s",
        (typ, int(pid)),
    )[0]
    return str(row["payload"]), str(row["activity"])


def _card(w, need: str, *extra: str) -> int:
    w.ok(["create", "todo", R, need, "--detail", "card for 841", *extra], desk=PEER)
    return int(rec_todo.find(w.cn, R, need)["id"])


def _letter_on_other(w) -> int:
    """A letter tagged OTHER, with its activity row set to OTHER as well, so
    only the write under test can move it."""
    res = w.ok(["send", "--to-desk", ME, "--roster", OTHER, "--body-file", str(w.body)], desk=PEER)
    mid = int(res["id"])
    cur = w.cn.cursor()
    try:
        cur.execute(
            "UPDATE activity a JOIN mail m ON a.type = 'mail' AND a.id = m.id"
            " SET a.roster_id = m.roster_id, a.updated = a.updated WHERE m.id = %s",
            (mid,),
        )
        w.cn.commit()
    finally:
        cur.close()
    return mid


def test_send_roster_tags_letter_and_activity(w) -> None:
    res = w.ok(["send", "--to-desk", ME, "--roster", OTHER, "--body-file", str(w.body)], desk=PEER)
    assert _rosters(w.cn, "mail", int(res["id"])) == (OTHER, OTHER)


def test_first_reply_keeps_parent_letter_roster(w) -> None:
    mid = _letter_on_other(w)
    before = _rosters(w.cn, "mail", mid)
    assert before == (OTHER, OTHER)
    w.ok(["reply", str(mid), "--body-file", str(w.body)], desk=ME)
    assert _rosters(w.cn, "mail", mid) == before


def test_card_under_a_card_keeps_parent_roster(w) -> None:
    pid = _card(w, "c841-parent")
    assert _rosters(w.cn, "todo", pid) == (R, R)
    child = _card(w, "c841-child", "--parent-type", "todo", "--parent-id", str(pid))
    assert _rosters(w.cn, "todo", pid) == (R, R)
    assert _rosters(w.cn, "todo", child) == (R, R)


def _drift(cn) -> int:
    return int(
        scalar_done(
            cn,
            "SELECT (SELECT COUNT(*) FROM mail m JOIN activity a ON a.type = 'mail' AND a.id = m.id"
            " WHERE a.roster_id <> m.roster_id)"
            " + (SELECT COUNT(*) FROM todo t JOIN activity a ON a.type = 'todo' AND a.id = t.id"
            " WHERE a.roster_id <> t.roster_id)",
        )
    )


def test_ensure_backfills_activity_roster_once(w) -> None:
    cn = w.cn
    mid = _letter_on_other(w)
    tid = _card(w, "c841-drift")
    base = _drift(cn)
    cur = cn.cursor()
    try:
        # The drift the old write paths left: Office (id 1) on the activity row.
        cur.execute("UPDATE activity SET roster_id = 1, updated = updated WHERE type = 'mail' AND id = %s", (mid,))
        cur.execute("UPDATE activity SET roster_id = 1, updated = updated WHERE type = 'todo' AND id = %s", (tid,))
        cn.commit()
    finally:
        cur.close()
    assert _drift(cn) == base + 2
    stamp = "SELECT updated FROM activity WHERE (type = 'mail' AND id = %s) OR (type = 'todo' AND id = %s) ORDER BY type"
    before = [r["updated"] for r in rows_done(cn, stamp, (mid, tid))]
    first = migrate.ensure(cn)
    assert "activity.roster_from_payload" in first["applied"]
    assert _drift(cn) == 0
    assert _rosters(cn, "mail", mid) == (OTHER, OTHER)
    assert _rosters(cn, "todo", tid) == (R, R)
    assert [r["updated"] for r in rows_done(cn, stamp, (mid, tid))] == before
    again = migrate.ensure(cn)
    assert "activity.roster_from_payload" not in again["applied"]
    assert _drift(cn) == 0


def test_tree_add_rooting_keeps_parent_roster(w) -> None:
    """mill_tree_add roots a plan at a card that is on none (no tree name) and
    at a card not yet in the named tree: both parent touches keep its roster."""
    from agent_coord.server.records import tree as rec_tree

    for i, tree in enumerate(("", "t841-named")):
        parent = _card(w, f"c841-add-parent-{i}")
        child = _card(w, f"c841-add-child-{i}")
        rec_tree.add(w.cn, "todo", parent, "todo", child, tree=tree)
        assert _rosters(w.cn, "todo", parent) == (R, R), tree
        assert _rosters(w.cn, "todo", child) == (R, R), tree
