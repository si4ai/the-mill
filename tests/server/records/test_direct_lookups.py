"""F23: send offline check, hold reads and the roster check read by WHERE, not by scanning."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

pytestmark = pytest.mark.sql

from agent_coord.const import CONST_DESK
from agent_coord.helpers.errors import CoordError
from agent_coord.helpers.projects import project_refusal
from agent_coord.server.api.mill import rpc
from agent_coord.server.records import floor as rec_floor
from agent_coord.server.records import hold as rec_hold
from agent_coord.server.records import join as rec_join
from agent_coord.server.records import name as rec_name
from tests.server.records.conftest import seed_names


class _Book:
    def __init__(self, cn):
        self._cn = cn


@pytest.fixture(scope="module")
def book(cn):
    seed_names(cn, ("dl", "roster"), ("dl-other", "roster"), ("dl_a", "desk"), ("dl_b", "desk"),
               ("dl_c", "desk"), ("dl_out", "desk"), ("dl_noseat", "desk"))
    for d in ("dl_a", "dl_b", "dl_c"):
        rec_join.upsert(cn, "dl", d, "", None, "present")
    rec_join.upsert(cn, "dl-other", "dl_out", "", None, "present")
    rec_hold.upsert(cn, "dl", "dl_a", "dl/one.md")
    rec_hold.upsert(cn, "dl", "dl_a", "dl/two.md")
    rec_hold.upsert(cn, "dl", "dl_b", "dl/three.md")
    rec_hold.upsert(cn, "dl", "dl_c", "dl/free.md")
    rec_hold.drop(cn, "dl", "dl_c", "dl/free.md")
    return _Book(cn)


def _age(cn, desk, minutes):
    cur = cn.cursor()
    cur.execute(
        "UPDATE seat h JOIN name n ON n.id = h.desk_id SET h.updated = %s WHERE n.type='desk' AND n.name=%s",
        (datetime.now() - timedelta(minutes=minutes), desk),
    )
    cn.commit()
    cur.close()


def _legacy_seen(cn, project, desk):
    did = rec_name.get(cn, desk, CONST_DESK)
    for j in rec_join.select(cn, project) or []:
        if int(j.get("desk_id") or 0) == int(did or -1):
            return j.get("updated") or j.get("created")
    return None


@pytest.mark.parametrize("project", ["dl", "dl-other", "", "no-such-roster"])
def test_seat_lookup_matches_the_project_seat_list(cn, book, project):
    ids = [rec_name.get(cn, d, CONST_DESK) for d in ("dl_a", "dl_b", "dl_c", "dl_out", "dl_noseat")]
    got = rec_join.seen(cn, project, ids)
    for d, did in zip(("dl_a", "dl_b", "dl_c", "dl_out", "dl_noseat"), ids):
        assert got.get(int(did)) == _legacy_seen(cn, project, d), (project, d)
    assert rec_join.seen(cn, project, []) == {}


def test_offline_dests_keeps_send_order_fresh_and_unknown(cn, book):
    _age(cn, "dl_a", 1)
    _age(cn, "dl_b", 30)
    _age(cn, "dl_c", 30)
    dests = [(CONST_DESK, d) for d in ("dl_c", "dl_a", "no-such-desk", "dl_out", "dl_b", "dl_c")]
    assert rpc._offline_dests(book, "dl", dests, set()) == ["dl_c", "no-such-desk", "dl_out", "dl_b", "dl_c"]
    # a roster-expanded desk and a non-desk target are skipped
    assert rpc._offline_dests(book, "dl", dests, {"dl_c"}) == ["no-such-desk", "dl_out", "dl_b"]
    assert rpc._offline_dests(book, "dl", [("roster", "dl")], set()) == []
    # no project: every seat counts, so dl_out's fresh seat is online
    _age(cn, "dl_out", 1)
    assert rpc._offline_dests(book, "", [(CONST_DESK, "dl_out"), (CONST_DESK, "dl_b")], set()) == ["dl_b"]


def test_offline_dests_skips_desks_when_the_seat_read_fails(cn, book, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("book down")

    monkeypatch.setattr(rec_join, "seen", boom)
    dests = [(CONST_DESK, "dl_b"), (CONST_DESK, "no-such-desk")]
    assert rpc._offline_dests(book, "dl", dests, set()) == ["no-such-desk"]


def _legacy_own(cn, desk):
    who = rec_name.bare(desk, CONST_DESK) if desk.strip() else ""
    return [
        {"resource": r["resource"], "since": r.get("updated")}
        for r in rec_hold.select(cn, "")
        if who and rec_name.bare(str(r.get("desk") or ""), CONST_DESK) == who and r.get("resource")
    ]


@pytest.mark.parametrize("desk", ["dl_a", "dl_b", "dl_c", "DL_A", "dl_noseat", "nobody", "", "  "])
def test_hold_own_matches_the_full_scan(cn, book, desk):
    assert rec_hold.own(cn, desk) == _legacy_own(cn, desk)


@pytest.mark.parametrize("resource", ["dl/one.md", "dl/free.md", "DL/ONE.MD", "dl/missing.md", ""])
def test_hold_peek_and_find_by_resource(cn, book, resource):
    out = rec_hold.peek(cn, "dl", resource)
    rows = [r for r in rec_hold.select(cn, "") if r.get("resource") == resource.strip()]
    if rows:
        assert out["id"] == rows[0]["id"] and out["owner"] == (rows[0].get("desk") or None)
    else:
        assert out["id"] is None and out["held"] is False


def test_find_returns_select_rows_and_columns(cn, book):
    every = rec_hold.select(cn, "")
    assert rec_hold.find(cn) == every
    assert rec_hold.find(cn, held=True) == [r for r in every if r.get("desk_id") is not None]
    assert rec_hold.find(cn, desk="dl_a") == [r for r in every if r.get("desk") == "dl_a"]
    assert rec_hold.find(cn, resource="dl/three.md") == [r for r in every if r.get("resource") == "dl/three.md"]
    assert rec_hold.find(cn, desk="dl_a", resource="dl/three.md") == []


def test_drop_refusals_read_one_resource(cn, book):
    assert rec_hold.drop(cn, "dl", "dl_b", "dl/one.md")["reason"] == "held by dl_a, not you"
    assert rec_hold.drop(cn, "dl", "dl_b", "dl/free.md")["reason"] == "not held by you"
    assert rec_hold.drop(cn, "dl", "dl_b", "dl/missing.md")["reason"] == "not held by you"
    assert rec_hold.own(cn, "dl_a")  # nothing released


def test_hold_list_and_floor_read_held_rows_only(cn, book):
    out = rpc._hold_list(book, "dl")["holds"]
    held = [r for r in rec_hold.select(cn, "") if r.get("desk")]
    assert [h["id"] for h in out] == [r["id"] for r in held]
    assert [x["id"] for x in rec_floor.build_holds(cn, [])] == [r["id"] for r in held]


def _legacy_live(cn):
    names = [str(r["name"]).strip() for r in rec_name.select(cn) if r.get("type") == "roster" and str(r["name"]).strip()]
    names.sort(key=lambda s: (s != "Office", s.lower()))
    return names


def test_live_projects_is_the_roster_slice_of_the_catalog(cn, book):
    assert rpc._live_projects(cn) == _legacy_live(cn)


@pytest.mark.parametrize("who", ["dl", "Office", "DL", "Dl-Other", "no-such-roster", "", "dl_a"])
def test_require_live_project_matches_the_catalog_rule(cn, book, who):
    err = project_refusal("hold", who.strip(), _legacy_live(cn))
    if err is None:
        assert rpc._require_live_project(cn, who, "hold") == who
    else:
        with pytest.raises(CoordError) as e:
            rpc._require_live_project(cn, who, "hold")
        assert str(e.value) == err


def test_direct_reads_leave_no_open_transaction(cn, book):
    rec_hold.own(cn, "dl_a")
    rec_join.seen(cn, "dl", [rec_name.get(cn, "dl_a", CONST_DESK)])
    rec_name.live_roster(cn, "dl")
    rec_name.live_roster_names(cn)
    assert not cn.in_transaction
