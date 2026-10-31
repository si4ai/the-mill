"""Card 931 / F223: Admin (and high-trust stale) drop of another desk's hold.

Stale = holder has no live connected seat (floor alive: time_connect set and
time_disconnect null or older than connect) AND the hold's since (activity.updated,
else hold.updated) is at least hold_stale_days old (default 7; config
hold_stale_days / AGENT_COORD_HOLD_STALE_DAYS).

Live or younger-than-threshold holds of another desk: Admin only, either trust.
Limited trust: only the holder or Admin. Own drop unchanged. Drop row is by the
acting desk with peer_id = holder; holder seat token is untouched.
"""
from __future__ import annotations

import pytest

from agent_coord.client.tokens import token_hash
from agent_coord.server.records import hold as rec_hold
from agent_coord.server.records import join as rec_join
from agent_coord.server.records.db import rows_done, scalar_done
from tests.server.records.conftest import admin_desk, seed_names

pytestmark = pytest.mark.sql

R = "r931"
HOLDER = "d931-holder"
OTHER = "d931-other"
ADMIN = "d931-admin"


@pytest.fixture(scope="module")
def book(cn):
    seed_names(cn, (R, "roster"), (HOLDER, "desk"), (OTHER, "desk"), (ADMIN, "desk"))
    for d in (HOLDER, OTHER):
        rec_join.upsert(cn, R, d, "builder", token_hash=token_hash("tok-" + d), doing="present")
    # admin_desk seats ADMIN with its own token; do not upsert it first (no-steal).
    admin_desk(cn, ADMIN)
    return cn


def _connect(cn, desk: str) -> None:
    rec_join.mark_socket(cn, desk, up=True)


def _disconnect(cn, desk: str) -> None:
    rec_join.mark_socket(cn, desk, up=True)
    rec_join.mark_socket(cn, desk, up=False)


def _take(cn, desk: str, res: str) -> int:
    out = rec_hold.upsert(cn, R, desk, res)
    assert int(out[0]["ok"]) == 1
    return int(out[0]["id"])


def _age_hold(cn, hid: int, days: int) -> None:
    """Backdate hold since (activity.updated and hold.updated) by days."""
    cur = cn.cursor()
    cur.execute(
        "UPDATE hold SET updated = TIMESTAMPADD(DAY, -%s, UTC_TIMESTAMP(6)) WHERE id = %s",
        (days, hid),
    )
    cur.execute(
        "UPDATE activity SET updated = TIMESTAMPADD(DAY, -%s, UTC_TIMESTAMP(6))"
        " WHERE type = 'hold' AND id = %s",
        (days, hid),
    )
    cn.commit()
    cur.close()


def _holder(cn, res: str) -> str | None:
    rows = rec_hold.find(cn, resource=res)
    assert len(rows) == 1, rows
    return rows[0].get("desk") or None


def _drop_row(cn, hid: int) -> dict | None:
    rows = rows_done(
        cn,
        "SELECT d.desk_id, dn.name AS actor, d.peer_id, pn.name AS peer, d.act"
        " FROM doing d"
        " JOIN name dn ON dn.id = d.desk_id"
        " LEFT JOIN name pn ON pn.id = d.peer_id"
        " WHERE d.on_type = 'hold' AND d.on_id = %s AND d.act = 'drop'"
        " ORDER BY d.id DESC LIMIT 1",
        (hid,),
    )
    return rows[0] if rows else None


def _token(cn, desk: str) -> str | None:
    return scalar_done(
        cn,
        "SELECT j.token_hash FROM seat j JOIN name n ON n.id = j.desk_id"
        " WHERE n.type = 'desk' AND n.name = %s",
        (desk,),
    )


def test_holder_drops_own_at_high_trust(book, monkeypatch) -> None:
    cn = book
    monkeypatch.setenv("AGENT_COORD_TRUST", "high")
    res = "h931/own-high"
    hid = _take(cn, HOLDER, res)
    _connect(cn, HOLDER)
    out = rec_hold.drop(cn, R, HOLDER, res)
    assert out.get("released") is True
    assert _holder(cn, res) is None
    row = _drop_row(cn, hid)
    assert row and row["actor"] == HOLDER
    assert row.get("peer") in (None, "")


def test_holder_drops_own_at_limited_trust(book, monkeypatch) -> None:
    cn = book
    monkeypatch.setenv("AGENT_COORD_TRUST", "limited")
    res = "h931/own-limited"
    _take(cn, HOLDER, res)
    _connect(cn, HOLDER)
    out = rec_hold.drop(cn, R, HOLDER, res)
    assert out.get("released") is True
    assert _holder(cn, res) is None


def test_admin_drops_live_other_at_high(book, monkeypatch) -> None:
    cn = book
    monkeypatch.setenv("AGENT_COORD_TRUST", "high")
    res = "h931/admin-live-high"
    hid = _take(cn, HOLDER, res)
    _connect(cn, HOLDER)
    tok_before = _token(cn, HOLDER)
    out = rec_hold.drop(cn, R, ADMIN, res)
    assert out.get("released") is True, out
    assert _holder(cn, res) is None
    row = _drop_row(cn, hid)
    assert row and row["actor"] == ADMIN and row["peer"] == HOLDER
    assert _token(cn, HOLDER) == tok_before


def test_admin_drops_live_other_at_limited(book, monkeypatch) -> None:
    cn = book
    monkeypatch.setenv("AGENT_COORD_TRUST", "limited")
    res = "h931/admin-live-lim"
    hid = _take(cn, HOLDER, res)
    _connect(cn, HOLDER)
    out = rec_hold.drop(cn, R, ADMIN, res)
    assert out.get("released") is True, out
    assert _holder(cn, res) is None
    row = _drop_row(cn, hid)
    assert row and row["actor"] == ADMIN and row["peer"] == HOLDER


def test_non_admin_live_other_refused_both_trusts(book, monkeypatch) -> None:
    cn = book
    res = "h931/live-refuse"
    _take(cn, HOLDER, res)
    _connect(cn, HOLDER)
    for trust in ("high", "limited"):
        monkeypatch.setenv("AGENT_COORD_TRUST", trust)
        out = rec_hold.drop(cn, R, OTHER, res)
        assert out.get("released") is False, (trust, out)
        assert "Admin" in str(out.get("reason") or "") or "held by" in str(out.get("reason") or "")
    assert _holder(cn, res) == HOLDER
    # cleanup for later tests sharing the module book
    assert rec_hold.drop(cn, R, HOLDER, res).get("released") is True


def test_non_admin_six_day_disconnected_refused_at_high(book, monkeypatch) -> None:
    cn = book
    monkeypatch.setenv("AGENT_COORD_TRUST", "high")
    res = "h931/6d-disc"
    hid = _take(cn, HOLDER, res)
    _disconnect(cn, HOLDER)
    _age_hold(cn, hid, 6)
    out = rec_hold.drop(cn, R, OTHER, res)
    assert out.get("released") is False, out
    assert _holder(cn, res) == HOLDER
    assert rec_hold.drop(cn, R, HOLDER, res).get("released") is True


def test_non_admin_eight_day_disconnected_ok_at_high(book, monkeypatch) -> None:
    cn = book
    monkeypatch.setenv("AGENT_COORD_TRUST", "high")
    res = "h931/8d-disc"
    hid = _take(cn, HOLDER, res)
    _disconnect(cn, HOLDER)
    _age_hold(cn, hid, 8)
    tok_before = _token(cn, HOLDER)
    out = rec_hold.drop(cn, R, OTHER, res)
    assert out.get("released") is True, out
    assert _holder(cn, res) is None
    row = _drop_row(cn, hid)
    assert row and row["actor"] == OTHER and row["peer"] == HOLDER
    assert _token(cn, HOLDER) == tok_before


def test_non_admin_eight_day_connected_refused(book, monkeypatch) -> None:
    cn = book
    monkeypatch.setenv("AGENT_COORD_TRUST", "high")
    res = "h931/8d-conn"
    hid = _take(cn, HOLDER, res)
    _connect(cn, HOLDER)
    _age_hold(cn, hid, 8)
    out = rec_hold.drop(cn, R, OTHER, res)
    assert out.get("released") is False, out
    assert _holder(cn, res) == HOLDER
    assert rec_hold.drop(cn, R, HOLDER, res).get("released") is True


def test_non_admin_eight_day_disconnected_refused_at_limited(book, monkeypatch) -> None:
    cn = book
    monkeypatch.setenv("AGENT_COORD_TRUST", "limited")
    res = "h931/8d-lim"
    hid = _take(cn, HOLDER, res)
    _disconnect(cn, HOLDER)
    _age_hold(cn, hid, 8)
    out = rec_hold.drop(cn, R, OTHER, res)
    assert out.get("released") is False, out
    assert _holder(cn, res) == HOLDER
    # Admin still can
    assert rec_hold.drop(cn, R, ADMIN, res).get("released") is True


def test_release_other_refuses_when_holder_changed(book, monkeypatch) -> None:
    """Check-then-act: SP must refuse when the holder changed since the Python check."""
    cn = book
    monkeypatch.setenv("AGENT_COORD_TRUST", "high")
    res = "h931/race-holder"
    hid = _take(cn, HOLDER, res)
    # Free, then OTHER takes the same row (holder changed hands).
    assert rec_hold.drop(cn, R, HOLDER, res).get("released") is True
    hid2 = _take(cn, OTHER, res)
    assert hid2 == hid
    assert _holder(cn, res) == OTHER
    tok_before = _token(cn, OTHER)
    # Python approved against HOLDER; SP must not drop OTHER.
    rows = rec_hold.delete_other(cn, hid, ADMIN, expect=HOLDER)
    assert rows and int(rows[0].get("ok") or 0) == 0, rows
    reason = str((rows[0] or {}).get("reason") or "").lower()
    assert "holder changed" in reason, rows[0]
    assert _holder(cn, res) == OTHER
    assert _token(cn, OTHER) == tok_before
    assert rec_hold.drop(cn, R, OTHER, res).get("released") is True
