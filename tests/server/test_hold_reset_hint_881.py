"""Card 881 / F215: reset and retire poke HOLD hints for each freed hold (H12/H13).

A desk waiting on `watch hold NAME` must wake when reset or retire frees the
lock; the hint shape matches a drop (`type=hold`, command=drop).
"""
from __future__ import annotations

import pytest

from agent_coord.client.tokens import token_hash
from agent_coord.server.api.mill import rpc
from agent_coord.server.records import hold as rec_hold
from agent_coord.server.records import join as rec_join
from agent_coord.server.records import name as rec_name
from tests.server.records.conftest import admin_desk, seed_names

pytestmark = pytest.mark.sql

R = "r881"
GONE = "d881-gone"
DEAD = "d881-dead"
ADMIN = "d881-admin"


@pytest.fixture()
def book(cn):
    seed_names(cn, (R, "roster"), (GONE, "desk"), (DEAD, "desk"), (ADMIN, "desk"))
    # Admin seat for reset
    from agent_coord.server.records.db import rows_done

    # Ensure ADMIN is Admin for require_admin - use admin_desk fixture desk
    adm = admin_desk(cn)
    for d in (GONE, DEAD):
        rec_join.upsert(cn, R, d, "builder", token_hash=token_hash("tok-" + d), doing="present")
    assert int(rec_hold.upsert(cn, R, GONE, "h881/a")[0]["ok"]) == 1
    assert int(rec_hold.upsert(cn, R, GONE, "h881/b")[0]["ok"]) == 1
    assert int(rec_hold.upsert(cn, R, DEAD, "h881/c")[0]["ok"]) == 1
    return cn, adm


class _B:
    def __init__(self, cn):
        self._cn = cn


def test_reset_pokes_drop_hint_for_each_freed_hold(book, monkeypatch):
    cn, adm = book
    poked: list[tuple] = []

    def capture(c, typ, nid, command, *, owner=None, fresh=False):
        poked.append((typ, int(nid), command))

    monkeypatch.setattr(rpc, "_poke", capture)
    ids = {int(r["id"]) for r in rec_hold.find(cn, desk=GONE, held=True)}
    assert len(ids) == 2
    out = rpc._h_reset(_B(cn), {"desk": GONE}, R, adm)
    assert out["ok"] is True
    got = {(t, i, c) for t, i, c in poked}
    assert got == {("hold", i, "drop") for i in ids}, (got, ids)


def test_retire_pokes_drop_hint_for_freed_hold(book, monkeypatch):
    cn, adm = book
    poked: list[tuple] = []

    def capture(c, typ, nid, command, *, owner=None, fresh=False):
        poked.append((typ, int(nid), command))

    monkeypatch.setattr(rpc, "_poke", capture)
    hid = int(rec_hold.find(cn, desk=DEAD, held=True)[0]["id"])
    # Self-retire needs matching owner + seat hash; use admin retire --yes path
    # via rec_name.retire through the non-yes branch requires hash. Prefer admin path.
    # Direct: call retire with yes after setting body the admin catalog expects -
    # simpler path: non-yes self-retire after seating DEAD with a known hash.
    from agent_coord.server.records.db import scalar

    # Seat DEAD already has token; compute hash for _seat_hash path by using
    # rec_name.retire from records (no poke) then... we need RPC. Use admin.
    # admin_cat.retire needs body shape - fall back to calling the non-yes
    # path with by_hash: monkeypatch _seat_hash to accept.
    monkeypatch.setattr(rpc, "_seat_hash", lambda *a, **k: "x")
    # Self-retire requires owner == slug
    rows = rpc._h_retire(_B(cn), {"slug": DEAD}, R, DEAD)
    assert rows is not None
    got = {(t, i, c) for t, i, c in poked}
    assert ("hold", hid, "drop") in got, (got, hid)
