"""0.8.0 lane B (card 868, F168, F174): card, doing and name procedures on the beta book.

The book is the 0.8.0 schema as card 1207 left it (doing is only tw runs; seat as the desk kind table,
the kind-checked name FKs). Each test names one ported behavior:

- card moves: card 1207 moved them out of doing. The procedures set activity.act and todo.meta.evidence
  (ship and done set it, back removes it); the move's record is the rpc's transition row (test_lane_b_moves_080).
- live runs: clock-out, reset and retire end a desk's live tw runs as cleared (Tsk7); card 1207 dropped
  seat.doing_id and the focus rows.
- name commands: retire, rename, reclaim and mint go through sp_name_*; main's
  mill_name_delete / _rename / _reclaim are not in the book.
- trust: the procedures read b_trust(); init_trust_fn re-creates it.
"""
from __future__ import annotations

import mysql.connector
import pytest

from agent_coord.client.tokens import token_hash
from agent_coord.server.records import join as rec_join
from agent_coord.server.records import name as rec_name
from agent_coord.server.records import todo as rec_todo
from agent_coord.server.records.db import call, rows_done, scalar_done
from tests.server.records.conftest import seed_names

# fresh_schema: runs lane B against a beta book, not tip
pytestmark = [pytest.mark.sql, pytest.mark.fresh_schema]

ROSTER = "lb080"
ADMIN = "lb080-adm"
ANN = "lb080-ann"
BOB = "lb080-bob"


def _seat(cn, desk: str) -> str:
    digest = token_hash("seat-" + desk)
    rec_join.upsert(cn, ROSTER, desk, "", digest)
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


def _events(cn, card: int) -> list[int]:
    """Card 1207: doing has no item link, so any doing row by this module's card desks would be a move row."""
    rows = rows_done(
        cn,
        "SELECT g.id FROM doing g JOIN name dn ON dn.id = g.desk_id WHERE dn.type = 'desk' AND dn.name IN (%s, %s, %s)",
        (ADMIN, ANN, BOB),
    )
    return [int(r["id"]) for r in rows]


def _act(cn, card: int) -> tuple:
    """activity.act and its desk: the card's latest move."""
    row = rows_done(cn, "SELECT a.act, n.name AS desk FROM activity a JOIN name n ON n.id = a.desk_id"
                        " WHERE a.type = 'todo' AND a.id = %s", (card,))[0]
    return (row["act"], row["desk"])


def _meta_evidence(cn, card: int):
    return scalar_done(cn, "SELECT JSON_UNQUOTE(JSON_EXTRACT(meta, '$.evidence')) FROM todo WHERE id = %s", (card,))


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
    assert _events(book, card) == []
    assert _act(book, card) == ("create", ANN)


def test_parked_card_first_event_is_parked(book):
    rows = rec_todo.insert(book, ROSTER, ANN, "parked", '{"slug": "lb-ev-park"}')
    book.commit()
    card = int(rows[-1]["id"])
    assert _events(book, card) == []
    assert _act(book, card) == ("park", ANN)


def test_claim_ship_done_back_write_events_with_evidence(book):
    card = _card(book, "lb-ev-flow")
    bob = _desk_id(book, BOB)
    call(book, "cmd_claim", [bob, card, 0, "", None])
    assert _act(book, card) == ("claim", BOB)
    got = _pass(book, BOB, card, "ship", "sha abc123")
    assert got["evidence"] == "sha abc123"
    assert (_act(book, card), _meta_evidence(book, card)) == (("ship", BOB), "sha abc123")
    got = _pass(book, ANN, card, "done", None)
    # a done with no evidence keeps the ship's (main's todo.evidence rule)
    assert got["evidence"] == "sha abc123"
    assert (_act(book, card), _meta_evidence(book, card)) == (("done", ANN), "sha abc123")
    got = _pass(book, ANN, card, "back", None)
    assert got["evidence"] is None
    assert (_act(book, card), _meta_evidence(book, card)) == (("back", ANN), None)
    assert _events(book, card) == []


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
    assert _events(book, card) == []
    assert _act(book, card) == ("note", ANN)  # a body edit is a note, not a move


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
    # card 1207: no doing move rows were written, so none are left behind
    assert _events(book, card) == []


def test_attached_card_touch_keeps_the_parents_latest_move(book):
    parent = _card(book, "lb-att-parent")
    rows = rec_todo.insert_attached(book, ROSTER, ANN, "open", '{"slug": "lb-att-child"}', "todo", parent)
    book.commit()
    child = int(rows[-1]["id"])
    assert _events(book, child) == []
    assert _act(book, child) == ("create", ANN)
    # main wrote roster id 1 into the parent's activity desk. 0.8.0: activity.act is the latest move and
    # desk_id who made it; a tree touch is not a move, so the parent keeps its filer's create.
    row = rows_done(book, "SELECT desk_id, act FROM activity WHERE type='todo' AND id=%s", (parent,))[0]
    assert (row["desk_id"], row["act"]) == (_desk_id(book, ANN), "create")


# ---------- live tw runs end as cleared (card 1207) ----------

def _start(cn, desk: str, wid: str) -> int:
    rid = int(call(cn, "mill_doing_task", [desk, f"task:{desk}:{wid}", None, 1])[0]["id"])
    cn.commit()
    return rid


def _cleared(cn, rid: int) -> bool:
    return bool(scalar_done(
        cn, "SELECT COUNT(*) FROM transition WHERE activity_type = 'doing' AND activity_id = %s"
        " AND to_state = 'cleared' AND reason = 'clear'", (rid,)))


def test_clock_out_and_reset_clear_live_runs(book):
    desk = "lb080-dn"
    _seat(book, desk)
    first = _start(book, desk, "a")
    assert not _cleared(book, first)
    rec_join.delete(book, ROSTER, desk)  # clock-out
    book.commit()
    assert _cleared(book, first)
    rec_join.upsert(book, ROSTER, desk, "", token_hash("seat-" + desk))
    book.commit()
    second = _start(book, desk, "b")
    rec_join.reset(book, ROSTER, desk)
    book.commit()
    assert _cleared(book, second)
    # a cleared run is cleared once
    assert scalar_done(book, "SELECT COUNT(*) FROM transition WHERE activity_type = 'doing' AND activity_id = %s"
                             " AND to_state = 'cleared'", (first,)) == 1


def test_retire_clears_live_runs(book):
    desk = "lb080-dn-ret"
    _seat(book, desk)
    rid = _start(book, desk, "a")
    rec_name.retire(book, desk, "desk", by=ADMIN)
    book.commit()
    assert _cleared(book, rid)


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
