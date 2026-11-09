"""card 1098 fold: admin transition analysis pane shape (wall-ui contract)."""
from __future__ import annotations

import pytest

from agent_coord.server import transition as tr
from agent_coord.server import transition_admin as ta
from agent_coord.server.transition_enums import ActivityType, Reason, State
from tests.server.records.conftest import admin_desk


def _q(cn, sql, args=()):
    cur = cn.cursor()
    try:
        cur.execute(sql, args)
        return cur.fetchall() if cur.with_rows else []
    finally:
        cur.close()


def _exec(cn, sql, args=()):
    cur = cn.cursor()
    try:
        cur.execute(sql, args)
    finally:
        cur.close()


def _ensure_activity(cn, typ: str, aid: int, desk_id: int) -> None:
    cur = cn.cursor()
    try:
        cur.execute(
            "INSERT IGNORE INTO activity (type, id, desk_id, created)"
            " VALUES (%s, %s, %s, UTC_TIMESTAMP())",
            (typ, aid, desk_id),
        )
    finally:
        cur.close()


def test_since_key_accepts_24h_7d_only():
    assert ta._since_key("24h") == "24h"
    assert ta._since_key("7d") == "7d"
    assert ta._since_key("24H") == "24h"
    assert ta._since_key("") is None
    assert ta._since_key(None) is None
    assert ta._since_key("1h") is None
    assert ta._since_key("all") is None


def test_analysis_error_shape_on_bad_cn():
    """analysis.error is the only failure signal; lists stay empty."""

    class Boom:
        def cursor(self):
            raise RuntimeError("no book")

    out = ta.analysis(Boom())
    assert out.get("error")
    assert "error" in out
    assert out["by_type"] == []
    assert out["by_pair"] == []
    assert out["wake"] == []
    assert out["saved_rows"] == 0
    assert "since" not in out


@pytest.mark.sql
def test_analysis_by_type_saved_rows_and_by_pair_zero_fire(cn, monkeypatch):
    """by_type carries saved_rows; by_pair lists every configured pair (incl. zero)."""
    monkeypatch.setenv("AGENT_COORD_TRANSITION_MODE", "compress")
    monkeypatch.setenv(
        "AGENT_COORD_TRANSITION_PAIRS",
        "doing:seated/connected,hold:free/held,hold:held/held",
    )

    desk = admin_desk(cn)
    desk_id = _q(cn, "SELECT id FROM name WHERE type='desk' AND name=%s", (desk,))[0][0]
    aid = 91098101
    _ensure_activity(cn, "doing", aid, desk_id)

    # two flips -> one compressed row n=2 => saved_rows contributes 1
    tr.put(
        cn,
        activity_type=ActivityType.doing,
        activity_id=aid,
        from_state=State.seated,
        to_state=State.connected,
        reason=Reason.connect,
        desk_id=desk_id,
        role="actor",
        join_key=f"admin-pane:{desk_id}:1",
    )
    tr.put(
        cn,
        activity_type=ActivityType.doing,
        activity_id=aid,
        from_state=State.connected,
        to_state=State.seated,
        reason=Reason.disconnect,
        desk_id=desk_id,
        role="actor",
        join_key=f"admin-pane:{desk_id}:2",
    )
    cn.commit()

    out = ta.analysis(cn)
    assert "error" not in out
    doing = next(r for r in out["by_type"] if r["activity_type"] == "doing")
    assert doing["rows"] >= 1
    assert doing["events"] >= doing["rows"]
    assert doing["saved_rows"] == doing["events"] - doing["rows"]
    assert out["saved_rows"] == out["total_events"] - out["total_rows"]

    pairs = {(p["activity_type"], p["from_state"], p["to_state"]): p for p in out["by_pair"]}
    # sorted ends: connected < seated alphabetically
    doing_pair = pairs[("doing", "connected", "seated")]
    assert doing_pair["rows"] >= 1
    assert doing_pair["saved_rows"] == doing_pair["events"] - doing_pair["rows"]
    # zero-fire configured pair still present
    held = pairs[("hold", "held", "held")]
    assert held["rows"] == 0 and held["events"] == 0 and held["saved_rows"] == 0
    free = pairs[("hold", "free", "held")]
    assert free["rows"] == 0

    wake_labels = {w["label"] for w in out["wake"]}
    assert wake_labels >= {
        "queued",
        "sent",
        "missed",
        "done",
        "auto_done",
        "receipt_unopened",
        "receipt_opened",
    }


@pytest.mark.sql
def test_analysis_since_24h_filters_and_echoes(cn, monkeypatch):
    monkeypatch.setenv("AGENT_COORD_TRANSITION_MODE", "capture")
    monkeypatch.setenv("AGENT_COORD_TRANSITION_PAIRS", "doing:seated/connected")

    desk = admin_desk(cn)
    desk_id = _q(cn, "SELECT id FROM name WHERE type='desk' AND name=%s", (desk,))[0][0]
    aid = 91098102
    _ensure_activity(cn, "doing", aid, desk_id)
    tr.put(
        cn,
        activity_type=ActivityType.doing,
        activity_id=aid,
        from_state=State.seated,
        to_state=State.connected,
        reason=Reason.connect,
        desk_id=desk_id,
        role="actor",
        join_key=f"admin-pane-since:{desk_id}",
    )
    cn.commit()
    # age the row past 24h
    _exec(
        cn,
        "UPDATE transition SET at = UTC_TIMESTAMP() - INTERVAL 2 DAY"
        " WHERE activity_type='doing' AND activity_id=%s",
        (aid,),
    )
    cn.commit()

    all_rows = ta.analysis(cn)
    win = ta.analysis(cn, since="24h")
    assert win.get("since") == "24h"
    assert "error" not in win
    # aged row excluded from the window
    assert win["total_rows"] < all_rows["total_rows"] or win["total_rows"] == 0


@pytest.mark.sql
def test_analysis_wake_receipt_and_auto_done(cn, monkeypatch):
    """wake[] reads real transition reasons + mail_to.receipt and W9 meta.auto."""
    monkeypatch.setenv("AGENT_COORD_TRANSITION_MODE", "capture")
    monkeypatch.delenv("AGENT_COORD_TRANSITION_PAIRS", raising=False)

    desk = admin_desk(cn)
    desk_id = _q(cn, "SELECT id FROM name WHERE type='desk' AND name=%s", (desk,))[0][0]
    wid = 91098103
    _ensure_activity(cn, "wake", wid, desk_id)
    tr.put(
        cn,
        activity_type=ActivityType.wake,
        activity_id=wid,
        from_state=State.none,
        to_state=State.queued,
        reason=Reason.wake_queue,
        desk_id=desk_id,
        role="actor",
        join_key=f"wake:{wid}",
    )
    tr.put(
        cn,
        activity_type=ActivityType.wake,
        activity_id=wid,
        from_state=State.queued,
        to_state=State.missed,
        reason=Reason.wake_owed,
        desk_id=desk_id,
        role="actor",
        join_key=f"wake:{wid}",
    )
    # W9 auto wake-done
    tr.put(
        cn,
        activity_type=ActivityType.wake,
        activity_id=wid,
        from_state=State.lease_live,
        to_state=State.idle,
        reason=Reason.wake_done,
        desk_id=desk_id,
        role="actor",
        join_key=f"wake:{wid}",
        meta={"wasted": 0, "auto": 1, "pending0": 0},
    )
    cn.commit()

    # receipt dests: one unopened, one opened (Office roster name row)
    roster_id = _q(
        cn, "SELECT id FROM name WHERE type='roster' AND name='Office' LIMIT 1"
    )[0][0]

    def _letter(body: str) -> int:
        cur = cn.cursor()
        try:
            cur.execute(
                "INSERT INTO mail (desk_id, roster_id, body)"
                " VALUES (%s, %s, %s)",
                (desk_id, roster_id, body),
            )
            return int(cur.lastrowid)
        finally:
            cur.close()

    mid_u = _letter("admin-pane-receipt-unopened")
    mid_o = _letter("admin-pane-receipt-opened")
    _exec(
        cn,
        "INSERT INTO mail_to (type, id, desk_id, receipt, asked)"
        " VALUES ('mail', %s, %s, 1, 1)",
        (mid_u, desk_id),
    )
    _exec(
        cn,
        "INSERT INTO mail_to (type, id, desk_id, receipt, asked, opened)"
        " VALUES ('mail', %s, %s, 1, 1, UTC_TIMESTAMP())",
        (mid_o, desk_id),
    )
    cn.commit()

    out = ta.analysis(cn)
    assert "error" not in out
    by = {w["label"]: w["value"] for w in out["wake"]}
    assert by["queued"] >= 1
    assert by["missed"] >= 1
    assert by["done"] >= 1
    assert by["auto_done"] >= 1
    assert by["receipt_unopened"] >= 1
    assert by["receipt_opened"] >= 1


def test_glance_block_marks_failed_windows_stored_false_without_error_key():
    """glance seal drops 'error'; a failed read carries stored=False and no figures."""

    class Boom:
        def cursor(self):
            raise RuntimeError("no book")

    out = ta.glance_block(Boom())
    assert set(out) == {"mode", "pairs", "pairs_state", "windows"}
    assert out["mode"] in ("compress", "capture")
    assert set(out["windows"]) == {"all", "24h", "7d"}
    for win in out["windows"].values():
        assert win == {"stored": False}


@pytest.mark.sql
def test_glance_block_matches_analysis_for_each_window(cn, monkeypatch):
    monkeypatch.setenv("AGENT_COORD_TRANSITION_MODE", "compress")
    out = ta.glance_block(cn)
    assert out["mode"] == "compress"
    for key, since in (("all", None), ("24h", "24h"), ("7d", "7d")):
        want = ta.analysis(cn, limit=10, since=since)
        got = dict(out["windows"][key])
        assert got.pop("stored") is True
        assert got == want
        assert "error" not in got


def test_pairs_state_lists_defaults_and_marks_switched_off_pairs(monkeypatch):
    monkeypatch.setenv("AGENT_COORD_TRANSITION_PAIRS", "hold:free/held,doing:seated/connected")
    rows = {r["pair"]: r for r in ta.pairs_state()}
    assert rows["hold:free/held"]["compress"] is True
    assert rows["doing:connected/seated"]["compress"] is True
    # default pair left off the list still gets a row, switched off
    assert rows["hold:held/held"]["compress"] is False
    monkeypatch.setenv("AGENT_COORD_TRANSITION_PAIRS", "doing:seated/connected,x:a/b")
    rows = {r["pair"]: r for r in ta.pairs_state()}
    assert rows["x:a/b"]["compress"] is True
    assert rows["hold:free/held"]["compress"] is False
