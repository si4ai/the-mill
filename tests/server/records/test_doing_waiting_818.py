"""#818 D3 on a real book: blocked-on rides --doing as fields on the doing row. Row F121.

(a) `--waiting-on "WHAT reason"` goes with --doing on any activity command:
    WHAT is a desk, mail-ID, todo-ID or hold-ID; the rest is the reason. It is
    stored on that command's doing row (waiting_type, waiting_id, waiting_why),
    nowhere else: no edge, link or adjacency table;
(b) without --doing, or naming no such desk or item, or the desk itself, it is
    refused and nothing is written (the command rolls back with its doing);
(c) `mill connected` shows the desk's own blocked-on, and the reverse view, the
    desks blocked on it, is a read: their current entry waits on the desk, a
    card it holds as volunteer, a hold it holds, or a letter it was asked on
    (mail_to.asked, F119; a copied desk is not blocked by it);
(d) it ends with its entry (pass, reply, drop, clear or a newer --doing);
(e) on an existing book `migrate.ensure()` widens waiting_type and adds
    waiting_why; a second ensure changes nothing; a run killed between them converges.
"""
from __future__ import annotations

import pytest

from agent_coord.install import migrate
from agent_coord.server.records.db import rows_done, scalar_done
from tests.server.records.conftest import seed_names
from tests.server.records.test_doing_flag_818 import World, _dispatch

pytestmark = pytest.mark.sql

ME = "d818w-me"
PEER = "d818w-peer"
THIRD = "d818w-third"
R = "r818"


class W(World):
    def ok(self, argv, desk=ME):
        return super().ok(argv, desk)

    def run(self, argv, desk=ME):
        return super().run(argv, desk)

    def me(self, desk=ME):
        return super().me(desk)

    def card(self, desk=PEER, **kw):
        return super().card(desk=desk, **kw)


@pytest.fixture(scope="module")
def w(cn, tmp_path_factory):
    from agent_coord.client.tokens import token_hash
    from agent_coord.server.records import join as here

    seed_names(cn, (R, "roster"), ("the-mill", "roster"), (ME, "desk"), (PEER, "desk"), (THIRD, "desk"))
    for d in (ME, PEER, THIRD):
        here.upsert(cn, R, d, "builder", token_hash=token_hash("tok-" + d), doing="present")
    mp = pytest.MonkeyPatch()
    world = W(cn, tmp_path_factory.mktemp("d818w"))
    mp.setenv("AGENT_COORD_MILL_HOME", str(tmp_path_factory.mktemp("d818whome")))
    mp.setenv("AGENT_COORD_MILL_URL", "http://127.0.0.1:9")
    mp.setattr("agent_coord.client.http.mill_http_call", lambda body: _dispatch(world, body))
    mp.setattr("agent_coord.server.api.mill.rpc._require_live_ws", lambda owner: None)
    for mod in ("agent_coord.client.http", "agent_coord.client.outbound"):
        mp.setattr(mod + ".resolve_desk_owner", lambda cli="": world.desk, raising=False)
    yield world
    mp.undo()


def _newest(cn, desk=ME) -> dict:
    return rows_done(
        cn,
        "SELECT g.id, g.text, g.on_type, g.on_id, g.waiting_type, g.waiting_id, g.waiting_why"
        " FROM doing g JOIN name n ON n.id = g.desk_id WHERE n.type = 'desk' AND n.name = %s"
        " ORDER BY g.created DESC, g.id DESC LIMIT 1",
        (desk,),
    )[0]


def _desk_id(cn, name) -> int:
    return int(scalar_done(cn, "SELECT id FROM name WHERE type = 'desk' AND name = %s", (name,)))


def _blocked(w, desk) -> list[dict]:
    return w.me(desk)["waiting_on_it"]["desks"]["newest"]


# (a) stored on the doing row -------------------------------------------------------

def test_waiting_on_a_desk_is_three_fields_on_the_doing_row(w):
    need, tid = w.card()
    res = w.ok(["claim", R, need, "--doing", "wiring the schema", "--waiting-on", f"{PEER} review of the column names"])
    assert res["doing_entry"]["waiting_on"] == {"on": f"desk-{PEER}", "why": "review of the column names"}
    row = _newest(w.cn)
    assert (row["on_type"], int(row["on_id"])) == ("todo", tid)
    assert (row["waiting_type"], int(row["waiting_id"]), row["waiting_why"]) == ("desk", _desk_id(w.cn, PEER), "review of the column names")


@pytest.mark.parametrize("kind", ["mail", "todo", "hold"])
def test_waiting_on_an_item(w, kind):
    if kind == "mail":
        nid = int(w.ok(["send", "--to-desk", PEER, "--body-file", str(w.body)])["id"])
    elif kind == "todo":
        _need, nid = w.card()
    else:
        res = w.ok(["hold", "d818w-lock-" + kind], desk=PEER)
        nid = int(res["id"])
    need, _ = w.card()
    w.ok(["claim", R, need, "--doing", "next step", "--waiting-on", f"{kind}-{nid}"])
    row = _newest(w.cn)
    assert (row["waiting_type"], int(row["waiting_id"]), row["waiting_why"] or "") == (kind, nid, "")


def test_no_edge_link_or_adjacency_table(w):
    names = [r["TABLE_NAME"].lower() for r in rows_done(
        w.cn, "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE()")]
    assert not [n for n in names if any(k in n for k in ("edge", "link", "adjac", "wait", "block"))]


# (b) refusals ----------------------------------------------------------------------

@pytest.mark.parametrize("what, why", [
    (None, "--waiting-on goes with --doing"),
    ("no-such-desk-818w", "no desk or item"),
    ("todo-999999", "no desk or item"),
    (ME, "a desk is not blocked on itself"),
])
def test_refused_and_nothing_written(w, what, why):
    need, tid = w.card()
    before = int(scalar_done(w.cn, "SELECT COUNT(*) FROM doing"))
    argv = ["claim", R, need]
    if what is None:
        argv += ["--waiting-on", f"{PEER} review"]
    else:
        argv += ["--doing", "trying", "--waiting-on", what]
    code, out, err = w.run(argv)
    assert code != 0 and why in (out + err), (out, err)
    assert int(scalar_done(w.cn, "SELECT COUNT(*) FROM doing")) == before
    assert scalar_done(w.cn, "SELECT status FROM todo WHERE id = %s", (tid,)) == "open"


# (c) connected ---------------------------------------------------------------------

def test_connected_shows_own_blocked_on_and_who_is_blocked_on_a_desk(w):
    need, tid = w.card()
    w.ok(["claim", R, need, "--doing", "wiring", "--waiting-on", f"{PEER} the column names"])
    mine = w.me(ME)
    assert mine["waiting_on"] == {"on": f"desk-{PEER}", "why": "the column names"}
    assert f"waiting on {PEER}" in mine["line"]
    peer = w.me(PEER)
    got = [x for x in peer["waiting_on_it"]["desks"]["newest"] if x["desk"] == ME]
    assert got and got[0]["on"] == f"desk-{PEER}" and got[0]["why"] == "the column names"
    assert peer["waiting_on_it"]["desks"]["n"] >= 1 and "blocked on it" in peer["line"]


def test_blocked_on_a_card_hold_or_letter_reads_back_to_its_desk(w):
    c_need, c_id = w.card()
    w.ok(["claim", R, c_need], desk=THIRD)
    need, _ = w.card()
    w.ok(["claim", R, need, "--doing", "after the card", "--waiting-on", f"todo-{c_id} schema first"])
    assert [x for x in _blocked(w, THIRD) if x["desk"] == ME and x["on"] == f"todo-{c_id}"]
    h = int(w.ok(["hold", "d818w-lock-b"], desk=THIRD)["id"])
    w.ok(["note", R, need, "--note", "n", "--doing", "after the lock", "--waiting-on", f"hold-{h}"])
    assert [x for x in _blocked(w, THIRD) if x["desk"] == ME and x["on"] == f"hold-{h}"]
    mid = int(w.ok(["send", "--to-desk", THIRD, "--body-file", str(w.body)])["id"])
    w.ok(["note", R, need, "--note", "n", "--doing", "after the answer", "--waiting-on", f"mail-{mid} an answer"])
    assert [x for x in _blocked(w, THIRD) if x["desk"] == ME and x["on"] == f"mail-{mid}"]
    # The waiting desk is never listed as blocked on itself (it sent the letter).
    assert not [x for x in _blocked(w, ME) if x["desk"] == ME]


def test_a_wait_on_a_letter_counts_only_its_asked_recipients(w):
    # PEER asks ME and THIRD; THIRD's reply-all asks PEER (the parent's sender)
    # and copies ME (#820). THIRD then waits on that reply for an answer.
    root = int(w.ok(["send", "--to-desk", ME, "--to-desk", THIRD, "--body-file", str(w.body)], desk=PEER)["id"])
    mid = int(w.ok(["reply", str(root), "--body-file", str(w.body)], desk=THIRD)["id"])
    asked = {str(r["name"]): int(r["asked"]) for r in rows_done(
        w.cn, "SELECT n.name, mt.asked FROM mail_to mt JOIN name n ON n.id = mt.desk_id"
              " WHERE mt.type = 'mail' AND mt.id = %s", (mid,))}
    assert asked == {PEER: 1, ME: 0}
    need, _ = w.card(desk=ME)
    w.ok(["claim", R, need, "--doing", "after the answer", "--waiting-on", f"mail-{mid} an answer"], desk=THIRD)
    # The asked desk sees THIRD blocked on it; the copied desk does not.
    assert [x for x in _blocked(w, PEER) if x["desk"] == THIRD and x["on"] == f"mail-{mid}"]
    assert not [x for x in _blocked(w, ME) if x["desk"] == THIRD and x["on"] == f"mail-{mid}"]


# (d) it ends with its entry --------------------------------------------------------

def test_blocked_on_ends_with_its_entry(w):
    need, _ = w.card()
    w.ok(["claim", R, need, "--doing", "wiring", "--waiting-on", f"{PEER} names"])
    assert [x for x in _blocked(w, PEER) if x["desk"] == ME]
    w.ok(["note", R, need, "--note", "n", "--doing", "unblocked now"])
    assert not [x for x in _blocked(w, PEER) if x["desk"] == ME]
    assert "waiting_on" not in w.me(ME)
    w.ok(["note", R, need, "--note", "n", "--doing", "blocked again", "--waiting-on", f"{PEER} names"])
    w.ok(["pass", R, need])
    assert not [x for x in _blocked(w, PEER) if x["desk"] == ME]


def test_history_keeps_the_blocked_on(w):
    need, _ = w.card()
    w.ok(["claim", R, need, "--doing", "for history", "--waiting-on", f"{PEER} a review"])
    h = w.ok(["connected", "--history", "--desk", ME])["history"][0]
    assert h["waiting_on"] == {"on": f"desk-{PEER}", "why": "a review"}


# (e) migration ---------------------------------------------------------------------

def _exec(cn, sql):
    cur = cn.cursor()
    try:
        cur.execute(sql)
        cn.commit()
    finally:
        cur.close()


def _col(cn, name):
    rows = rows_done(cn, "SELECT COLUMN_TYPE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE()"
                         " AND TABLE_NAME = 'doing' AND COLUMN_NAME = %s", (name,))
    return rows[0]["COLUMN_TYPE"] if rows else None


def test_migration_widens_waiting_type_and_adds_the_reason(w):
    _exec(w.cn, "UPDATE doing SET waiting_type = NULL, waiting_id = NULL WHERE waiting_type NOT IN ('mail', 'todo')")
    _exec(w.cn, "ALTER TABLE doing DROP COLUMN waiting_why, MODIFY COLUMN waiting_type ENUM('mail','todo') NULL")
    rows_before = int(scalar_done(w.cn, "SELECT COUNT(*) FROM doing"))
    first = migrate.ensure(w.cn)
    assert "doing.waiting_type" in first["applied"] and "doing.waiting_why" in first["applied"]
    assert _col(w.cn, "waiting_type") == "enum('mail','todo','hold','desk')"
    assert _col(w.cn, "waiting_why").startswith("varchar(200)")
    assert int(scalar_done(w.cn, "SELECT COUNT(*) FROM doing")) == rows_before
    second = migrate.ensure(w.cn)
    assert not [a for a in second["applied"] if a.startswith("doing.waiting")]


def test_a_run_killed_between_the_two_alters_converges(w):
    _exec(w.cn, "UPDATE doing SET waiting_type = NULL, waiting_id = NULL WHERE waiting_type NOT IN ('mail', 'todo')")
    _exec(w.cn, "ALTER TABLE doing DROP COLUMN waiting_why, MODIFY COLUMN waiting_type ENUM('mail','todo') NULL")
    _exec(w.cn, "ALTER TABLE doing MODIFY COLUMN waiting_type ENUM('mail','todo','hold','desk') NULL")
    out = migrate.ensure(w.cn)
    assert "doing.waiting_why" in out["applied"] and "doing.waiting_type" not in out["applied"]
    assert _col(w.cn, "waiting_why").startswith("varchar(200)")
