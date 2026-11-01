# -*- coding: utf-8 -*-
"""Beta name family and trust (card 868, F161): admin.md sections 1, 2, 4 and rows F60, F65, F92, F135, enforced
inside sp_name_* / cmd_trust on beta_ddl.sql. One test per gated cell. Trust is set the way the server sets it
(b_trust() re-created from config.toml); nothing is passed as an app argument. There is no name history table.
"""
from __future__ import annotations

import mysql.connector
import pytest

# fresh_schema: beta name/trust procedures on a beta book
pytestmark = [pytest.mark.sql, pytest.mark.fresh_schema]

H = {d: (c * 64)[:64] for d, c in (("adm", "a"), ("ann", "b"), ("bob", "c"), ("cat", "d"), ("dan", "e"),
                                   ("eve", "f"), ("fay", "0"))}


@pytest.fixture(scope="module")
def cn():
    try:
        from tests.beta_book import drop_book, make_book

        c, db = make_book("mill_bname868")
    except Exception as exc:
        pytest.skip(f"no MySQL: {exc}")
    for d, h in H.items():
        call(c, "sp_name_mint_desk", d, h)
    call(c, "sp_admin_set", None, "adm", 1)
    yield c
    drop_book(c, db)


def call(c, proc, *args):
    cur = c.cursor()
    try:
        cur.callproc(proc, args)
        out = []
        for r in cur.stored_results():
            out = r.fetchall()
        return out
    finally:
        cur.close()


def q(c, sql, args=()):
    cur = c.cursor()
    try:
        cur.execute(sql, args)
        return cur.fetchall() if cur.with_rows else []
    finally:
        cur.close()


def refused(c, text, proc, *args):
    with pytest.raises(mysql.connector.Error) as ei:
        call(c, proc, *args)
    assert text in str(ei.value), str(ei.value)


@pytest.fixture
def trust(cn):
    from tests.beta_book import set_trust

    yield lambda level: set_trust(cn, level)
    set_trust(cn, "high")


def nid(c, t, n):
    r = q(c, "SELECT id FROM name WHERE type = %s AND name = %s", (t, n))
    return r[0][0] if r else None


def row(c, name_id):
    return q(c, "SELECT type, name, deleted IS NOT NULL FROM name WHERE id = %s", (name_id,))[0]


# ---- section 2: mint (trust-gated)
@pytest.mark.parametrize("kind", ["roster", "label"])
def test_mint_high_any_desk(cn, trust, kind):
    trust("high")
    assert call(cn, "sp_name_mint", "ann", kind, f"h-{kind}")[0][3] == "created"
    assert row(cn, nid(cn, kind, f"h-{kind}")) == (kind, f"h-{kind}", 0)


@pytest.mark.parametrize("kind", ["roster", "label"])
def test_mint_limited_refused_for_plain_desk(cn, trust, kind):
    trust("limited")
    refused(cn, "limited-trust", "sp_name_mint", "ann", kind, f"l-{kind}")
    assert nid(cn, kind, f"l-{kind}") is None


@pytest.mark.parametrize("kind", ["roster", "label"])
def test_mint_limited_admin_ok(cn, trust, kind):
    trust("limited")
    assert call(cn, "sp_name_mint", "adm", kind, f"la-{kind}")[0][3] == "created"
    assert nid(cn, kind, f"la-{kind}") is not None


def test_mint_roster_is_its_name_row_only(cn):
    # No roster table (owner rule 2026-10-25): a roster has no data of its own, so the name row is the roster.
    call(cn, "sp_name_mint", "adm", "roster", "kind-r")
    i = nid(cn, "roster", "kind-r")
    assert i is not None
    q(cn, "INSERT INTO member (name_id, desk_id) VALUES (%s, %s)", (i, nid(cn, "desk", "ann")))
    assert q(cn, "SELECT COUNT(*) FROM member WHERE name_id = %s", (i,)) == [(1,)]


def test_desk_column_refuses_a_roster_id(cn):
    with pytest.raises(mysql.connector.Error) as ei:
        q(cn, "INSERT INTO watcher (type, id, desk_id) VALUES ('todo', 1, 1)")  # 1 = Office, a roster
    assert "foreign key" in str(ei.value).lower()


@pytest.mark.parametrize("kind", ["tree", "res"])
def test_mint_plan_or_resource_any_desk_even_limited(cn, trust, kind):
    trust("limited")
    assert call(cn, "sp_name_mint", "ann", kind, f"any-{kind}")[0][3] == "created"


def test_mint_desk_only_at_connect(cn):
    refused(cn, "a desk mints itself at connect", "sp_name_mint", "ann", "desk", "zed")


def test_mint_office_is_roster_1_even_after_rename(cn):
    assert call(cn, "sp_name_mint", "adm", "roster", "office")[0][:1] == (1,)
    call(cn, "sp_name_rename", "adm", None, "roster", "Office", "Hall")
    try:
        refused(cn, "Office names roster id 1", "sp_name_mint", "adm", "roster", "office")
    finally:
        call(cn, "sp_name_rename", "adm", None, "roster", "Hall", "Office")


# ---- section 1: rename, retire, reclaim are Admin at either trust
@pytest.mark.parametrize("level", ["high", "limited"])
def test_rename_plain_desk_refused(cn, trust, level):
    trust(level)
    call(cn, "sp_name_mint", "adm", "roster", f"rn-{level}")
    refused(cn, "Admin only: rename", "sp_name_rename", "ann", None, "roster", f"rn-{level}", f"rn2-{level}")


@pytest.mark.parametrize("level", ["high", "limited"])
def test_rename_admin_is_a_plain_update(cn, trust, level):
    trust(level)
    call(cn, "sp_name_mint", "adm", "label", f"ra-{level}")
    i = nid(cn, "label", f"ra-{level}")
    call(cn, "sp_name_rename", "adm", None, "label", f"ra-{level}", f"rb-{level}")
    assert row(cn, i) == ("label", f"rb-{level}", 0) and nid(cn, "label", f"ra-{level}") is None
    # No hold on a renamed-away name: the old string mints a new id at once.
    call(cn, "sp_name_mint", "adm", "label", f"ra-{level}")
    assert nid(cn, "label", f"ra-{level}") not in (None, i)


def test_desk_self_rename_with_own_hash(cn):
    i = nid(cn, "desk", "dan")
    call(cn, "sp_name_rename", "dan", H["dan"], "desk", "dan", "dan2")
    assert nid(cn, "desk", "dan2") == i
    call(cn, "sp_name_rename", "dan2", H["dan"], "desk", "dan2", "dan")


def test_desk_self_rename_wrong_hash_refused(cn):
    refused(cn, "Admin only: rename", "sp_name_rename", "dan", H["bob"], "desk", "dan", "dan3")


def test_desk_renames_another_desk_refused(cn):
    refused(cn, "Admin only: rename", "sp_name_rename", "dan", H["dan"], "desk", "bob", "bob2")


@pytest.mark.parametrize("spelling", ["Admin", "admin", " ADMIN ", "\u00c1dmin"])
def test_admin_never_renamed(cn, spelling):
    refused(cn, "cannot rename Admin", "sp_name_rename", "adm", None, "roster", spelling, "boss")
    assert q(cn, "SELECT name FROM name WHERE id = 2")[0][0] == "Admin"


def test_office_rename_by_admin_follows_id_1(cn):
    call(cn, "sp_name_rename", "adm", None, "roster", "Office", "Hall")
    try:
        assert q(cn, "SELECT mill_roster_id('Office'), mill_roster_id('Hall')")[0] == (1, 1)
        call(cn, "sp_name_mint", "adm", "roster", "other-r")
        refused(cn, "Office names roster id 1", "sp_name_rename", "adm", None, "roster", "other-r", "OFFICE")
    finally:
        call(cn, "sp_name_rename", "adm", None, "roster", "Hall", "Office")


def test_f60_type_outside_roster_label_desk_refused(cn):
    refused(cn, "type is roster, label or desk", "sp_name_retire", "adm", None, "tree", "any-tree")


@pytest.mark.parametrize("level", ["high", "limited"])
def test_retire_plain_desk_refused(cn, trust, level):
    trust(level)
    refused(cn, "Admin only: retire", "sp_name_retire", "ann", None, "label", "h-label")


@pytest.mark.parametrize("seed, text", [("Office", "cannot delete Office"), ("Admin", "cannot delete Admin")])
def test_seeds_never_retired(cn, seed, text):
    refused(cn, text, "sp_name_retire", "adm", None, "roster", seed)


def test_seeds_never_reclaimed(cn):
    refused(cn, "cannot reclaim a seed", "sp_name_reclaim", "adm", "roster", "Admin")


def test_hard_delete_refused(cn):
    # Mint a label this test owns so the DELETE hits a row (trigger fires).
    call(cn, "sp_name_mint", "adm", "label", "h-hard-del")
    with pytest.raises(mysql.connector.Error) as ei:
        q(cn, "DELETE FROM name WHERE type = 'label' AND name = 'h-hard-del'")
    assert "DELETE refused" in str(ei.value)


def _held(c, desk, res):
    d = nid(c, "desk", desk)
    call(c, "sp_name_mint", desk, "res", res)
    q(c, "INSERT INTO hold (desk_id, resource_id) VALUES (%s, %s)", (d, nid(c, "res", res)))
    hid = q(c, "SELECT id FROM hold WHERE resource_id = %s", (nid(c, "res", res),))[0][0]
    q(c, "INSERT INTO activity (type, id, desk_id, roster_id, act) VALUES ('hold', %s, %s, 1, 'hold')", (hid, d))
    q(c, "UPDATE seat SET delivery_mode = 'webhook', endpoint_url = 'http://x', endpoint_key = 'k' WHERE desk_id = %s", (d,))
    return d, hid


def _retired_shape(c, desk, hid, actor):
    seat = q(c, "SELECT token_hash, endpoint_url, endpoint_key, delivery_mode, doing_id FROM seat WHERE desk_id = %s",
             (desk,))[0]
    assert seat[:4] == (None, None, None, "websocket")
    assert q(c, "SELECT desk_id FROM hold WHERE id = %s", (hid,))[0][0] is None
    assert row(c, desk)[2] == 1
    # The focus ends with a clear row on the desk, and seat.doing_id names it (decision 2).
    assert q(c, "SELECT desk_id, act, text FROM doing WHERE id = %s", (seat[4],)) == [(desk, "clear", "")]
    # C5: the drop row is by the acting desk (self or Admin), never NULL, on the hold; the holder is the peer when
    # another desk acted.
    assert q(c, "SELECT desk_id, act, peer_id FROM doing WHERE on_type = 'hold' AND on_id = %s", (hid,)) == [
        (actor, "drop", None if actor == desk else desk)]
    assert q(c, "SELECT desk_id, act FROM activity WHERE type = 'hold' AND id = %s", (hid,)) == [(actor, "drop")]


def test_retire_desk_clears_seat_and_frees_holds_f65_f135(cn):
    cat, hid = _held(cn, "cat", "lock-1")
    out = call(cn, "sp_name_retire", "adm", None, "desk", "cat")
    assert out[0][3] == "deleted" and out[0][4] == 1
    _retired_shape(cn, cat, hid, nid(cn, "desk", "adm"))


def test_desk_self_retire_with_own_hash_card_880(cn):
    # Card 880 (F177): a desk retires itself with its own seat token hash, as sp_name_rename's p_by_hash.
    eve, hid = _held(cn, "eve", "lock-eve")
    out = call(cn, "sp_name_retire", "eve", H["eve"], "desk", "eve")
    assert out[0][3] == "deleted" and out[0][4] == 1
    _retired_shape(cn, eve, hid, eve)


def test_desk_self_retire_wrong_hash_or_other_desk_refused(cn):
    refused(cn, "Admin only: retire", "sp_name_retire", "fay", H["bob"], "desk", "fay")
    refused(cn, "Admin only: retire", "sp_name_retire", "fay", H["fay"], "desk", "bob")
    refused(cn, "Admin only: retire", "sp_name_retire", "fay", H["fay"], "label", "h-label")
    assert row(cn, nid(cn, "desk", "fay"))[2] == 0


def test_retired_name_not_reused_and_reclaim_same_id(cn):
    call(cn, "sp_name_mint", "adm", "label", "old-l")
    i = nid(cn, "label", "old-l")
    call(cn, "sp_name_retire", "adm", None, "label", "old-l")
    refused(cn, "name retired", "sp_name_mint", "adm", "label", "old-l")
    refused(cn, "name retired: mill reclaim first", "sp_name_rename", "adm", None, "label", "old-l", "new-l")
    refused(cn, "Admin only: reclaim", "sp_name_reclaim", "ann", "label", "old-l")
    call(cn, "sp_name_reclaim", "adm", "label", "old-l")
    assert nid(cn, "label", "old-l") == i and row(cn, i)[2] == 0


def test_reclaim_refused_while_a_live_seat_is_a_member(cn):
    call(cn, "sp_name_mint", "adm", "roster", "busy-r")
    r = nid(cn, "roster", "busy-r")
    q(cn, "INSERT INTO member (name_id, desk_id) VALUES (%s, %s)", (r, nid(cn, "desk", "bob")))
    call(cn, "sp_name_retire", "adm", None, "roster", "busy-r")
    refused(cn, "mill reset first", "sp_name_reclaim", "adm", "roster", "busy-r")


def test_no_name_history_table(cn):
    assert q(cn, "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE()"
                 " AND TABLE_NAME = 'name_event'") == [(0,)]


# ---- trust setting: show any seated desk, set Admin; Admin grant is the host procedure
def test_trust_show_any_set_admin(cn, trust):
    assert call(cn, "cmd_trust", "ann", None)[0] == ("high", "show")
    refused(cn, "Admin only: set trust", "cmd_trust", "ann", "limited")
    refused(cn, "mill trust: high or limited", "cmd_trust", "adm", "low-ish")
    # The procedure answers the level to apply; the server writes config.toml and re-creates b_trust().
    assert call(cn, "cmd_trust", "adm", "limited")[0] == ("limited", "set")
    assert call(cn, "cmd_trust", "ann", "")[0][0] == "high"
    trust("limited")
    assert call(cn, "cmd_trust", "ann", "")[0][0] == "limited"


def test_admin_remove_needs_admin_and_last_admin_stays(cn):
    refused(cn, "Admin only: remove from Admin", "sp_admin_set", "ann", "adm", 0)
    refused(cn, "the last Admin stays", "sp_admin_set", "adm", "adm", 0)
