"""F11: a resumed desk lists only its own holds (#218)."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.sql

from agent_coord.server.push import connect_sync_frame
from agent_coord.server.records import hold
from tests.server.records.conftest import seed_names, take_hold


def test_own_empty_desk_and_no_holds(cn) -> None:
    assert hold.own(cn, "") == []
    assert hold.own(cn, "   ") == []
    seed_names(cn, ("unit", "roster"), ("f11-none", "desk"))
    assert hold.own(cn, "f11-none") == []


def test_own_ignores_other_desks(cn) -> None:
    seed_names(cn, ("unit", "roster"), ("f11-other", "desk"), ("f11-absent", "desk"))
    row = hold.upsert(cn, "unit", "f11-other", "f11-theirs.res")
    assert int(row[0]["ok"]) == 1
    assert hold.own(cn, "f11-absent") == []
    assert {r["resource"] for r in hold.own(cn, "f11-other")} == {"f11-theirs.res"}


def test_own_many_holds_set_equality(cn) -> None:
    seed_names(cn, ("unit", "roster"), ("f11-many", "desk"))
    assert int(hold.upsert(cn, "unit", "f11-many", "f11-one.res")[0]["ok"]) == 1
    assert int(hold.upsert(cn, "unit", "f11-many", "f11-two.res")[0]["ok"]) == 1
    assert {r["resource"] for r in hold.own(cn, "f11-many")} == {"f11-one.res", "f11-two.res"}


def test_own_since_is_updated_and_path_is_stored(cn) -> None:
    seed_names(cn, ("unit", "roster"), ("f11-since", "desk"))
    assert int(hold.upsert(cn, "unit", "f11-since", "docs/a.md")[0]["ok"]) == 1
    mine = hold.own(cn, "f11-since")
    assert len(mine) == 1
    assert mine[0]["resource"] == "docs/a.md"
    stored = next(
        r
        for r in hold.select(cn, "")
        if r.get("desk") == "f11-since" and r.get("resource") == "docs/a.md"
    )
    assert mine[0]["since"] == stored["updated"]


def test_own_omits_a_dropped_hold(cn) -> None:
    seed_names(cn, ("unit", "roster"), ("f11-drop", "desk"))
    taken, key = take_hold(cn, "unit", "f11-drop", "f11-drop.res")
    assert int(taken[0]["ok"]) == 1
    assert {r["resource"] for r in hold.own(cn, "f11-drop")} == {"f11-drop.res"}
    keyless = hold.drop(cn, "unit", "f11-drop", "f11-drop.res")
    assert keyless["ok"] is False
    assert {r["resource"] for r in hold.own(cn, "f11-drop")} == {"f11-drop.res"}
    released = hold.drop(cn, "unit", "f11-drop", "f11-drop.res", key)
    assert released["ok"] is True
    assert hold.own(cn, "f11-drop") == []


def test_connect_sync_frame_holds_match_and_sync_is_a_list(cn) -> None:
    seed_names(cn, ("unit", "roster"), ("f11-frame", "desk"))
    assert int(hold.upsert(cn, "unit", "f11-frame", "f11-frame.res")[0]["ok"]) == 1
    frame = connect_sync_frame(cn, "f11-frame")
    assert frame["kind"] == "sync"
    assert isinstance(frame["sync"], list)
    assert frame["holds"] == hold.own(cn, "f11-frame")
    assert {r["resource"] for r in frame["holds"]} == {"f11-frame.res"}
    assert all(not isinstance(item, dict) or "resource" not in item for item in frame["sync"])


def test_connect_sync_frame_own_failure_keeps_sync(cn, monkeypatch) -> None:
    def _boom(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr("agent_coord.server.records.hold.own", _boom)
    frame = connect_sync_frame(cn, "f11-frame")
    assert frame["kind"] == "sync"
    assert isinstance(frame["sync"], list)
    assert frame["holds"] == []
