# -*- coding: utf-8 -*-
"""Beta name family and trust (card 868, F161): admin.md sections 1, 2, 4 and rows F60, F65, F92, F135, enforced
inside sp_name_* / cmd_trust on beta_ddl.sql. One test per gated cell. Each reads the trust row the procedure
reads; nothing is passed as an app argument.
"""
from __future__ import annotations

import mysql.connector
import pytest

pytestmark = pytest.mark.sql

H = {d: (c * 64)[:64] for d, c in (("adm", "a"), ("ann", "b"), ("bob", "c"), ("cat", "d"), ("dan", "e"))}


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
    def set_(level):
        call(cn, "cmd_trust", "adm", level)
    yield set_
    call(cn, "cmd_trust", "adm", "high")


def nid(c, t, n):
    r = q(c, "SELECT id FROM name WHERE type = %s AND name = %s", (t, n))
    return r[0][0] if r else None


def last_event(c, name_id):
    return q(c, "SELECT verb, old_name, new_name, desk_id, trust FROM name_event WHERE name_id = %s ORDER BY id DESC LIMIT 1", (name_id,))[0]


# ---- section 2: mint (trust-gated)
@pytest.mark.parametrize("kind", ["roster", "label"])
def test_mint_high_any_desk(cn, trust, kind):
    trust("high")
    assert call(cn, "sp_name_mint", "ann", kind, f"h-{kind}")[0][3] == "created"
    assert last_event(cn, nid(cn, kind, f"h-{kind}"))[:4] == ("mint", None, f"h-{kind}", nid(cn, "desk", "ann"))


@pytest.mark.parametrize("kind", ["roster", "label"])
def test_mint_limited_refused_for_plain_desk(cn, trust, kind):
    trust("limited")
    refused(cn, "limited-trust", "sp_name_mint", "ann", kind, f"l-{kind}")
    assert nid(cn, kind, f"l-{kind}") is None


@pytest.mark.parametrize("kind", ["roster", "label"])
def test_mint_limited_admin_ok(cn, trust, kind):
    trust("limited")
    call(cn, "sp_name_mint", "adm", kind, f"la-{kind}")
    assert last_event(cn, nid(cn, kind, f"la-{kind}"))[4] == "limited"


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
def test_rename_admin_ok_with_history(cn, trust, level):
    trust(level)
    call(cn, "sp_name_mint", "adm", "label", f"ra-{level}")
    i = nid(cn, "label", f"ra-{level}")
    call(cn, "sp_name_rename", "adm", None, "label", f"ra-{level}", f"rb-{level}")
    assert last_event(cn, i) == ("rename", f"ra-{level}", f"rb-{level}", nid(cn, "desk", "adm"), level)


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
    refused(cn, "type is roster, label or desk", "sp_name_retire", "adm", "tree", "any-tree")


@pytest.mark.parametrize("level", ["high", "limited"])
def test_retire_plain_desk_refused(cn, trust, level):
    trust(level)
    refused(cn, "Admin only: retire", "sp_name_retire", "ann", "label", "h-label")


@pytest.mark.parametrize("seed, text", [("Office", "cannot delete Office"), ("Admin", "cannot delete Admin")])
def test_seeds_never_retired(cn, seed, text):
    refused(cn, text, "sp_name_retire", "adm", "roster", seed)


def test_seeds_never_reclaimed(cn):
    refused(cn, "cannot reclaim a seed", "sp_name_reclaim", "adm", "roster", "Admin")


def test_hard_delete_refused(cn):
    with pytest.raises(mysql.connector.Error) as ei:
        q(cn, "DELETE FROM name WHERE type = 'label' AND name = 'h-label'")
    assert "DELETE refused" in str(ei.value)


def test_retire_desk_clears_seat_and_frees_holds_f65_f135(cn):
    cat = nid(cn, "desk", "cat")
    call(cn, "sp_name_mint", "cat", "res", "lock-1")
    r = nid(cn, "res", "lock-1")
    q(cn, "INSERT INTO hold (desk_id, resource_id) VALUES (%s, %s)", (cat, r))
    hid = q(cn, "SELECT id FROM hold WHERE resource_id = %s", (r,))[0][0]
    q(cn, "INSERT INTO activity (type, id, desk_id, roster_id) VALUES ('hold', %s, %s, 1)", (hid, cat))
    q(cn, "UPDATE seat SET delivery_mode = 'webhook', endpoint_url = 'http://x', endpoint_key = 'k' WHERE desk_id = %s", (cat,))
    out = call(cn, "sp_name_retire", "adm", "desk", "cat")
    assert out[0][3] == "deleted" and out[0][4] == 1
    seat = q(cn, "SELECT token_hash, endpoint_url, endpoint_key, delivery_mode FROM seat WHERE desk_id = %s", (cat,))[0]
    assert seat == (None, None, None, "websocket")
    assert q(cn, "SELECT desk_id FROM hold WHERE id = %s", (hid,))[0][0] is None
    assert last_event(cn, cat)[0] == "retire"


def test_retired_name_not_reused_and_reclaim_same_id(cn):
    call(cn, "sp_name_mint", "adm", "label", "old-l")
    i = nid(cn, "label", "old-l")
    call(cn, "sp_name_retire", "adm", "label", "old-l")
    refused(cn, "name retired", "sp_name_mint", "adm", "label", "old-l")
    refused(cn, "name retired: mill reclaim first", "sp_name_rename", "adm", None, "label", "old-l", "new-l")
    refused(cn, "Admin only: reclaim", "sp_name_reclaim", "ann", "label", "old-l")
    call(cn, "sp_name_reclaim", "adm", "label", "old-l")
    assert nid(cn, "label", "old-l") == i and last_event(cn, i)[0] == "reclaim"


def test_reclaim_refused_while_a_live_seat_is_a_member(cn):
    call(cn, "sp_name_mint", "adm", "roster", "busy-r")
    r = nid(cn, "roster", "busy-r")
    q(cn, "INSERT INTO member (name_id, desk_id) VALUES (%s, %s)", (r, nid(cn, "desk", "bob")))
    call(cn, "sp_name_retire", "adm", "roster", "busy-r")
    refused(cn, "mill reset first", "sp_name_reclaim", "adm", "roster", "busy-r")


def test_name_history_append_only(cn):
    for stmt in ("UPDATE name_event SET new_name = 'x' WHERE id = 1", "DELETE FROM name_event WHERE id = 1"):
        with pytest.raises(mysql.connector.Error) as ei:
            q(cn, stmt)
        assert "append-only" in str(ei.value)


# ---- trust setting: show any seated desk, set Admin; Admin grant is the host procedure
def test_trust_show_any_set_admin(cn, trust):
    assert call(cn, "cmd_trust", "ann", None)[0][0] == "high"
    refused(cn, "Admin only: set trust", "cmd_trust", "ann", "limited")
    trust("limited")
    assert call(cn, "cmd_trust", "ann", "")[0][0] == "limited"


def test_admin_remove_needs_admin_and_last_admin_stays(cn):
    refused(cn, "Admin only: remove from Admin", "sp_admin_set", "ann", "adm", 0)
    refused(cn, "the last Admin stays", "sp_admin_set", "adm", "adm", 0)
