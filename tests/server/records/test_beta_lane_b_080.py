"""0.8.0 lane B (card 868, F168, F174): card, doing and name procedures on the beta book.

The book is the 0.8.0 schema (doing move rows, seat.doing_id, seat as the desk kind table,
the kind-checked name FKs). Each test names one ported behavior:

- card moves: every status or volunteer change is one doing move row by the acting desk
  (act, peer_id, evidence on ship and done); the card's `evidence` is read from them.
- seat.doing_id: after every focus write path it names the desk's newest focus row
  (act focus or clear, ORDER BY created DESC, id DESC), never a move row.
- name commands: retire, rename, reclaim and mint go through sp_name_*; main's
  mill_name_delete / _rename / _reclaim are not in the book.
- trust: the procedures read b_trust(); init_trust_fn re-creates it.
"""
from __future__ import annotations

import mysql.connector
import pytest

from agent_coord.client.tokens import token_hash
from agent_coord.server.records import doing as rec_doing
from agent_coord.server.records import join as rec_join
from agent_coord.server.records import name as rec_name
from agent_coord.server.records import todo as rec_todo
from agent_coord.server.records.db import call, rows_done, scalar_done
from tests.server.records.conftest import seed_names

pytestmark = pytest.mark.sql

ROSTER = "lb080"
ADMIN = "lb080-adm"
ANN = "lb080-ann"
BOB = "lb080-bob"


def _seat(cn, desk: str) -> str:
    digest = token_hash("seat-" + desk)
    rec_join.upsert(cn, ROSTER, desk, "", digest, None)
    cn.commit()
    return digest


@pytest.fixture(scope="module")
def book(cn):
    from tests.beta_book import set_trust

    seed_names(cn, (ROSTER, "roster"))
    for d in (ADMIN, ANN, BOB):
        _seat(cn, d)
    call(cn, "sp_admin_set", [None, ADMIN, 1])
    set_trust(cn, "high")
    yield cn
    set_trust(cn, "high")


def _events(cn, card: int) -> list[tuple]:
    """The card's move rows in id order: (act, peer, evidence, acting desk)."""
    rows = rows_done(
        cn,
        "SELECT g.act, pn.name AS peer, IFNULL(g.evidence, '') AS evidence, dn.name AS desk"
        " FROM doing g JOIN name dn ON dn.id = g.desk_id"
        " LEFT JOIN name pn ON pn.id = g.peer_id"
        " WHERE g.on_type = 'todo' AND g.on_id = %s AND g.act NOT IN ('focus', 'clear', 'finish')"
        " ORDER BY g.id",
        (card,),
    )
    return [(r["act"], r["peer"], r["evidence"], r["desk"]) for r in rows]


def _card(cn, body: str) -> int:
    rows = rec_todo.insert(cn, ROSTER, ANN, "open", '{"slug": "%s"}' % body)
    cn.commit()
    return int(rows[-1]["id"])


def _desk_id(cn, desk: str) -> int:
    return int(scalar_done(cn, "SELECT id FROM name WHERE type='desk' AND name=%s", (desk,)))


def _pass(cn, desk: str, card: int, step: str, ev=None) -> dict:
    rows = call(cn, "cmd_pass", [_desk_id(cn, desk), card, step, ev])
    return rows[-1]


# ---------- card move rows ----------

def test_new_card_writes_its_first_event(book):
    card = _card(book, "lb-ev-new")
    assert _events(book, card) == [("create", None, "", ANN)]


def test_parked_card_first_event_is_parked(book):
    rows = rec_todo.insert(book, ROSTER, ANN, "parked", '{"slug": "lb-ev-park"}')
    book.commit()
    assert _events(book, int(rows[-1]["id"])) == [("park", None, "", ANN)]


def test_claim_ship_done_back_write_events_with_evidence(book):
    card = _card(book, "lb-ev-flow")
    bob = _desk_id(book, BOB)
    call(book, "cmd_claim", [bob, card, 0, "", None])
    got = _pass(book, BOB, card, "ship", "sha abc123")
    assert got["evidence"] == "sha abc123"
    got = _pass(book, ANN, card, "done", None)
    # a done with no evidence keeps the ship's (main's todo.evidence rule)
    assert got["evidence"] == "sha abc123"
    got = _pass(book, ANN, card, "back", None)
    assert got["evidence"] is None
    assert _events(book, card) == [
        ("create", None, "", ANN),
        ("claim", None, "", BOB),
        ("ship", None, "sha abc123", BOB),
        ("done", None, "sha abc123", ANN),
        ("back", None, "", ANN),
    ]


def test_card_reads_show_the_newest_events_evidence(book):
    card = _card(book, "lb-ev-read")
    call(book, "cmd_claim", [_desk_id(book, BOB), card, 0, "", None])
    _pass(book, BOB, card, "ship", "proof line")
    assert rec_todo.get(book, card)[0]["evidence"] == "proof line"
    page = call(book, "mill_todo_page", [ROSTER, "", 0, card])
    assert [r["evidence"] for r in page] == ["proof line"]
    listed = [r for r in rec_todo.select(book, ROSTER) if int(r["id"]) == card]
    assert listed[0]["evidence"] == "proof line"
    rid = _desk_id(book, ANN)  # any id list; the roster's id is what counts
    roster_id = int(scalar_done(book, "SELECT id FROM name WHERE type='roster' AND name=%s", (ROSTER,)))
    rows = call(book, "mill_todo_select_rosters", ["[%d]" % roster_id, ""])
    assert [r["evidence"] for r in rows if int(r["id"]) == card] == ["proof line"]
    assert rid


def test_a_body_only_update_writes_no_event(book):
    card = _card(book, "lb-ev-note")
    rec_todo.update(book, card, ANN, "", "", '{"slug": "lb-ev-note", "detail": "x"}')
    book.commit()
    assert len(_events(book, card)) == 1


def test_todo_has_no_evidence_column(book):
    cols = rows_done(
        book,
        "SELECT COLUMN_NAME FROM information_schema.COLUMNS"
        " WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'todo' AND COLUMN_NAME = 'evidence'",
    )
    assert cols == []


def test_deleting_a_card_with_history_works(book):
    card = _card(book, "lb-ev-del")
    call(book, "cmd_claim", [_desk_id(book, BOB), card, 0, "", None])
    rec_todo.delete(book, card, ANN)
    book.commit()
    assert scalar_done(book, "SELECT COUNT(*) FROM todo WHERE id = %s", (card,)) == 0
    # doing is append-only history with no FK to todo: the move rows stay
    assert [e[0] for e in _events(book, card)] == ["create", "claim"]


def test_attached_card_touch_keeps_the_parents_latest_move(book):
    parent = _card(book, "lb-att-parent")
    rows = rec_todo.insert_attached(book, ROSTER, ANN, "open", '{"slug": "lb-att-child"}', "todo", parent)
    book.commit()
    child = int(rows[-1]["id"])
    assert _events(book, child) == [("create", None, "", ANN)]
    # main wrote roster id 1 into the parent's activity desk. 0.8.0: activity.act is the latest move and
    # desk_id who made it; a tree touch is not a move, so the parent keeps its filer's create.
    row = rows_done(book, "SELECT desk_id, act FROM activity WHERE type='todo' AND id=%s", (parent,))[0]
    assert (row["desk_id"], row["act"]) == (_desk_id(book, ANN), "create")


# ---------- seat.doing_id ----------

def _newest(cn, desk: str):
    return scalar_done(
        cn,
        "SELECT g.id FROM doing g JOIN name d ON d.id = g.desk_id"
        " WHERE d.type='desk' AND d.name=%s AND g.act IN ('focus', 'clear')"
        " ORDER BY g.created DESC, g.id DESC LIMIT 1",
        (desk,),
    )


def _now_row(cn, desk: str):
    return scalar_done(
        cn,
        "SELECT dn.doing_id FROM seat dn JOIN name d ON d.id = dn.desk_id"
        " WHERE d.type='desk' AND d.name=%s",
        (desk,),
    )


def _same(cn, desk: str):
    newest = _newest(cn, desk)
    assert newest is not None
    assert _now_row(cn, desk) == newest


def test_seat_doing_id_follows_every_write_path(book):
    """Validator check 2 (F181). Mutant: mill_doing_insert skips the UPDATE seat; this fails."""
    desk = "lb080-dn"
    _seat(book, desk)
    _same(book, desk)  # join: its focus (or clear) row
    card = _card(book, "lb-dn-card")
    rec_doing.put(book, desk, "working on it", "todo", card)
    book.commit()
    _same(book, desk)
    call(book, "cmd_claim", [_desk_id(book, desk), card, 0, "", None])  # a move row: seat.doing_id stays
    book.commit()
    _same(book, desk)
    rec_doing.finish(book, desk, "todo", card)
    book.commit()
    _same(book, desk)
    rec_doing.put(book, desk, "again", "todo", card)
    book.commit()
    rec_join.delete(book, ROSTER, desk)  # clock-out: a clear row
    book.commit()
    _same(book, desk)
    rec_join.upsert(book, ROSTER, desk, "", token_hash("seat-" + desk), "new join text")
    book.commit()
    _same(book, desk)
    rec_join.reset(book, ROSTER, desk)
    book.commit()
    _same(book, desk)


def test_seat_doing_id_after_retire_names_the_clear_row(book):
    desk = "lb080-dn-ret"
    _seat(book, desk)
    rec_doing.put(book, desk, "busy", "todo", _card(book, "lb-dn-ret"))
    book.commit()
    rec_name.retire(book, desk, "desk", by=ADMIN)
    book.commit()
    _same(book, desk)
    row = rows_done(book, "SELECT text, act FROM doing WHERE id = %s", (_now_row(book, desk),))[0]
    assert (row["text"], row["act"]) == ("", "clear")


def test_doing_now_read_reports_a_cleared_entry(book):
    desk = "lb080-dn-read"
    _seat(book, desk)
    card = _card(book, "lb-dn-read")
    rec_doing.put(book, desk, "reading", "todo", card)
    book.commit()
    rows = [r for r in rec_doing.now(book, desk) if r.get("part") == "desk"]
    assert rows[0]["text"] == "reading" and rows[0]["ended_by"] is None
    assert rows[0]["last_text"] == "reading"
    rec_join.delete(book, ROSTER, desk)
    book.commit()
    rows = [r for r in rec_doing.now(book, desk) if r.get("part") == "desk"]
    assert rows[0]["text"] == "reading" and rows[0]["ended_by"] == "cleared"


# ---------- name verbs through sp_name_* ----------

def test_main_name_procedures_are_gone(book):
    names = {
        r["ROUTINE_NAME"]
        for r in rows_done(
            book,
            "SELECT ROUTINE_NAME FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA = DATABASE()",
        )
    }
    assert not {"mill_name_delete", "mill_name_rename", "mill_name_reclaim"} & names
    assert {"sp_name_mint", "sp_name_mint_desk", "sp_name_rename", "sp_name_retire",
            "sp_name_reclaim", "cmd_trust", "sp_admin_set", "sp_label_renumber"} <= names


def test_admin_retires_and_reclaims_a_roster(book):
    seed_names(book, ("lb080-gone", "roster"))
    out = rec_name.retire(book, "lb080-gone", "roster", by=ADMIN)
    assert out[-1]["op"] == "deleted" and out[-1]["name_type"] == "roster"
    out = rec_name.reclaim(book, "lb080-gone", "roster", by=ADMIN)
    assert out[-1]["op"] == "reclaimed"


def test_a_desk_that_is_not_admin_cannot_retire_a_roster(book):
    seed_names(book, ("lb080-keep", "roster"))
    with pytest.raises(mysql.connector.Error) as ei:
        rec_name.retire(book, "lb080-keep", "roster", by=ANN)
    assert "Admin only: retire" in str(ei.value)


def test_a_desk_retires_itself_with_its_own_seat(book):
    desk = "lb080-self"
    digest = _seat(book, desk)
    out = rec_name.retire(book, desk, "desk", by=desk, by_hash=digest)
    assert out[-1]["op"] == "deleted"
    assert rec_join.token_hash_for_desk(book, desk) in (None, "")


def test_a_desk_renames_itself_with_its_own_seat(book):
    desk = "lb080-ren"
    digest = _seat(book, desk)
    out = rec_name.rename(book, desk, desk + "2", "desk", by=desk, by_hash=digest)
    assert out[-1]["op"] == "renamed" and out[-1]["name"] == desk + "2"


def test_mint_goes_through_sp_name_mint(book):
    out = rec_name.mint(book, "lb080-new-roster", "roster", by=ADMIN)
    assert out[-1]["op"] == "created"
    out = rec_name.mint(book, "lb080-new-roster", "roster", by=ADMIN)
    assert out[-1]["op"] == "exists"


def test_limited_trust_refuses_a_non_admin_mint(book):
    from tests.beta_book import set_trust

    set_trust(book, "limited")
    try:
        with pytest.raises(mysql.connector.Error) as ei:
            rec_name.mint(book, "lb080-lim", "label", by=ANN)
        assert "limited-trust" in str(ei.value)
        assert rec_name.mint(book, "lb080-lim", "label", by=ADMIN)[-1]["op"] == "created"
    finally:
        set_trust(book, "high")


def test_name_put_reads_b_trust_for_rosters(book):
    from tests.beta_book import set_trust

    set_trust(book, "limited")
    try:
        with pytest.raises(mysql.connector.Error) as ei:
            scalar_done(book, "SELECT MILL_NAME_PUT('roster', 'lb080-lim-roster')")
        assert "limited-trust" in str(ei.value)
        # a live name still resolves, and plans and resources mint at either trust
        assert scalar_done(book, "SELECT MILL_NAME_PUT('roster', %s)", (ROSTER,))
        assert scalar_done(book, "SELECT MILL_NAME_PUT('tree', 'lb080-tree')")
    finally:
        set_trust(book, "high")


def test_a_minted_desk_has_its_seat(book):
    seed_names(book, ("lb080-mailonly", "desk"))
    did = _desk_id(book, "lb080-mailonly")
    assert scalar_done(book, "SELECT token_hash IS NULL FROM seat WHERE desk_id = %s", (did,)) == 1


def test_label_put_mints_only_as_trust_allows(book):
    """mill_label_put mints through MILL_NAME_PUT, which reads b_trust() (checklist: label mint has a trust check)."""
    from tests.beta_book import set_trust

    card = _card(book, "lb-lab")
    set_trust(book, "limited")
    try:
        with pytest.raises(mysql.connector.Error) as ei:
            call(book, "mill_label_put", ["todo", card, "lb080-unknown-label", None])
        assert "limited-trust" in str(ei.value)
        assert rec_name.get(book, "lb080-unknown-label", "label") is None
    finally:
        set_trust(book, "high")
    call(book, "mill_label_put", ["todo", card, "lb080-unknown-label", None])
    assert rec_name.get(book, "lb080-unknown-label", "label") is not None


def test_a_named_desk_that_never_joined_is_not_on_the_floor(book):
    """A desk named by a letter has a seat row (FKs) but has not joined: not listed, no doing, no wake."""
    seed_names(book, ("lb080-never", "desk"))
    listed = {str(r.get("desk")) for r in call(book, "mill_join_select", [""])}
    assert "lb080-never" not in listed and ANN in listed
    assert not [r for r in call(book, "mill_doing_now", ["lb080-never", None, 1]) if r.get("part") == "desk"]
    from agent_coord.server.records import join as rec_join

    with pytest.raises(Exception, match="wake: desk has not joined"):
        rec_join.wake_arm(book, "lb080-never", "https://example.invalid/wake", "k" * 32)


def test_admin_set_unknown_desk_is_name_not_found(book):
    with pytest.raises(mysql.connector.Error) as ei:
        call(book, "sp_admin_set", [ADMIN, "lb080-nobody", 1])
    assert "name not found" in str(ei.value)


# ---------- sp version (no sp_deploy table; the owner, 2026-10-26) ----------

def test_sp_version_reads_the_pack_stamp_with_no_deploy_table(book):
    assert scalar_done(
        book,
        "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'sp_deploy'",
    ) == 0
    got = scalar_done(book, "SELECT mill_sp_version()")
    assert got is None or (got.startswith("sp-") and len(got) == 15)


# ---------- trust function ----------

def test_init_trust_fn_recreates_b_trust(book):
    from agent_coord.server.records.trust_fn import init_trust_fn

    try:
        assert init_trust_fn(book, "limited") == "limited"
        assert scalar_done(book, "SELECT b_trust()") == "limited"
        assert call(book, "cmd_trust", [ANN, None])[-1]["trust"] == "limited"
    finally:
        init_trust_fn(book, "high")
    assert scalar_done(book, "SELECT b_trust()") == "high"
