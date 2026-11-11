# -*- coding: utf-8 -*-
"""Card 1002 / F-wasted-wake-score: no-action wakes counted and tagged by trigger.

Measure only. A wake that ends in wake-done with no send/reply/claim/note/pass/hold/label
counts as wasted (mark and read alone still waste). Tags: hold_release, room_or_fyi_mail,
rering_handled, version_notice, other. mill score shows per-desk and per-office count,
share and trigger breakdown. Does not change wake behavior (card 949 rules stay off).
"""
from __future__ import annotations

import pytest

from datetime import datetime, timezone
from pathlib import Path

from agent_coord.server import wasted_wake as ww
from agent_coord.server.score_tick import BOOK_PERF, BOOK_TARGET, measure


def setup_function() -> None:
    ww.reset_for_tests()


def test_trigger_tags_are_the_five_named() -> None:
    assert ww.TRIGGERS == (
        "hold_release",
        "room_or_fyi_mail",
        "rering_handled",
        "version_notice",
        "other",
    )


def test_classify_trigger_priority() -> None:
    assert ww.classify_trigger(frame={"kind": "hint", "type": "hold"}, reason="addressed") == "hold_release"
    assert ww.classify_trigger(frame={"kind": "mail", "id": 1}, reason="room") == "room_or_fyi_mail"
    assert (
        ww.classify_trigger(frame={"kind": "mail", "id": 2}, reason="addressed", opened=True)
        == "rering_handled"
    )
    assert (
        ww.classify_trigger(frame={"kind": "hint", "type": "version"}, reason="addressed")
        == "version_notice"
    )
    assert ww.classify_trigger(frame={"kind": "mail", "id": 3}, reason="addressed") == "other"


def test_action_commands_exclude_mark_and_read() -> None:
    need = {"send", "reply", "claim", "note", "pass", "hold", "label"}
    assert need <= ww.ACTION_COMMANDS
    for noise in ("mark", "inbox", "mail-thread", "wake-done", "todo", "heartbeat", "peek"):
        assert noise not in ww.ACTION_COMMANDS


def test_no_action_wake_done_is_wasted(monkeypatch) -> None:
    lines: list[str] = []

    def fake_perf(op: str, ms: float = 0.0, **kv):
        parts = [f"op={op}"] + [f"{k}={v}" for k, v in kv.items()]
        lines.append(" ".join(parts))

    monkeypatch.setattr("agent_coord.server.push.perf_log", fake_perf)
    desk = "desk_a"
    ww.mark_lease(desk, trigger="hold_release")
    ww.note_rpc(desk, "inbox", ok=True)  # read alone: still waste
    ww.note_rpc(desk, "mark", ok=True)  # mark alone: still waste
    out = ww.finish_lease(desk)
    assert out is not None
    assert out["wasted"] is True
    assert out["trigger"] == "hold_release"
    assert any("op=wake.done" in L and "wasted=1" in L for L in lines)
    assert any("trigger=hold_release" in L for L in lines)
    assert any("desk=desk_a" in L for L in lines)


def test_action_between_wake_and_done_is_not_wasted(monkeypatch) -> None:
    lines: list[str] = []

    def fake_perf(op: str, ms: float = 0.0, **kv):
        parts = [f"op={op}"] + [f"{k}={v}" for k, v in kv.items()]
        lines.append(" ".join(parts))

    monkeypatch.setattr("agent_coord.server.push.perf_log", fake_perf)
    desk = "desk_b"
    ww.mark_lease(desk, trigger="other")
    ww.note_rpc(desk, "reply", ok=True)
    out = ww.finish_lease(desk)
    assert out is not None
    assert out["wasted"] is False
    assert len(lines) == 1
    assert "op=wake.done" in lines[0]
    assert "wasted=0" in lines[0]


def test_counts_share_and_trigger_breakdown() -> None:
    ww.mark_lease("d1", trigger="hold_release")
    ww.finish_lease("d1")
    ww.mark_lease("d1", trigger="room_or_fyi_mail")
    ww.note_rpc("d1", "send", ok=True)
    ww.finish_lease("d1")
    ww.mark_lease("d1", trigger="hold_release")
    ww.finish_lease("d1")
    snap = ww.desk_snapshot("d1")
    assert snap["wakes"] == 3
    assert snap["wasted"] == 2
    assert snap["share"] == 2 / 3
    assert snap["triggers"]["hold_release"] == 2
    assert snap["triggers"].get("room_or_fyi_mail", 0) == 0  # that wake had an action
    office = ww.office_snapshot()
    assert office["wakes"] == 3
    assert office["wasted"] == 2
    assert office["triggers"]["hold_release"] == 2


def test_book_perf_kpi_keys() -> None:
    assert ww.KPI_WASTED in BOOK_PERF
    assert ww.KPI_SHARE in BOOK_PERF
    assert BOOK_TARGET[ww.KPI_WASTED] == "0"
    assert BOOK_TARGET[ww.KPI_SHARE] == "0"


def test_measure_share_is_wasted_over_all_wakes(tmp_path: Path) -> None:
    """Published share = wasted / total finished leases (1 of 4 -> 25), not always 100."""
    (tmp_path / "mill-perf.log").write_text(
        "\n".join(
            [
                "2026-11-01T10:00:00Z op=wake.done trigger=hold_release desk=a wasted=1 wakes=1",
                "2026-11-01T10:00:01Z op=wake.done trigger=other desk=b wasted=0 wakes=1",
                "2026-11-01T10:00:02Z op=wake.done trigger=room_or_fyi_mail desk=c wasted=0 wakes=1",
                "2026-11-01T10:00:03Z op=wake.done trigger=other desk=d wasted=0 wakes=1",
                "2026-11-01T09:00:00Z op=wake.done trigger=other desk=old wasted=1 wakes=1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    now = datetime(2026, 11, 1, 10, 30, 0, tzinfo=timezone.utc)
    row = measure(dest=tmp_path, window_s=3600, now=now)
    assert row["mill-office.wasted_wake_n"] == 1
    assert row["mill-office.wasted_wake_share"] == 25


def test_measure_omits_share_when_no_wakes(tmp_path: Path) -> None:
    """Empty sample is omitted (None), never published as 0 or 100."""
    (tmp_path / "mill-perf.log").write_text(
        "2026-11-01T10:00:00Z op=wake.first ms=12\n",
        encoding="utf-8",
    )
    now = datetime(2026, 11, 1, 10, 30, 0, tzinfo=timezone.utc)
    row = measure(dest=tmp_path, window_s=3600, now=now)
    assert row["mill-office.wasted_wake_n"] is None
    assert row["mill-office.wasted_wake_share"] is None


def test_kpi_keys_are_literal_office_names() -> None:
    assert ww.KPI_WASTED == "mill-office.wasted_wake_n"
    assert ww.KPI_SHARE == "mill-office.wasted_wake_share"


def test_score_view_shape() -> None:
    ww.mark_lease("v1", trigger="version_notice")
    ww.finish_lease("v1")
    view = ww.score_view("v1")
    assert view["wasted"] == 1
    assert view["wakes"] == 1
    assert view["share"] == 1.0
    assert view["triggers"]["version_notice"] == 1
    assert view["unit"] == "wakes"


def test_post_desk_reply_lease_done_chain(monkeypatch) -> None:
    """Real wake POST -> action RPC hook -> lease_done; share uses all wakes."""
    from agent_coord.server import wake
    from agent_coord.server.api.mill import rpc
    from tests.server.webhook_fixtures import arm, opener

    class _Resp:
        status = 200

        def read(self, _n: int = 0) -> bytes:
            return b""

        def __enter__(self):
            return self

        def __exit__(self, *_a) -> bool:
            return False

    lines: list[str] = []

    def fake_perf(op: str, ms: float = 0.0, **kv):
        parts = [f"op={op}"] + [f"{k}={v}" for k, v in kv.items()]
        lines.append(" ".join(parts))

    arm(monkeypatch)
    monkeypatch.setattr("agent_coord.server.push.perf_log", fake_perf)
    monkeypatch.setattr(rpc, "_require_live_ws", lambda owner=None: None)

    class Fake:
        _tokens: dict = {}
        _cn = object()

        def resolve_bearer(self, token):
            return "chain"

        def _guard_owner(self, *a, **k):
            return {}

    def _reply(c, body, project, owner):
        return {"ok": True, "id": 1}

    monkeypatch.setitem(rpc.HANDLERS, "reply", _reply)
    with opener(lambda req, timeout: _Resp()):
        assert wake.post_desk(object(), "chain", {"kind": "hint", "type": "hold", "id": 9}) == "sent"
    # dispatch success path must call wasted_wake.note_rpc (catches unwiring)
    rpc.dispatch(
        Fake(),
        {"verb": "reply", "project": "the-mill", "owner": "chain", "id": 1, "body": "x"},
        token="t",
    )
    got = wake.lease_done(None, "chain")
    assert got in ("none", "sent", "sitting", "stale")
    snap = ww.desk_snapshot("chain")
    assert snap["wakes"] == 1
    assert snap["wasted"] == 0
    assert snap["share"] == 0.0
    assert any("op=wake.done" in L and "wasted=0" in L for L in lines)
    assert snap["triggers"].get("hold_release", 0) == 0  # acted: trigger not counted as waste


def test_publish_skips_omitted_wasted_wake_kpis(monkeypatch) -> None:
    from agent_coord.server import score_tick
    import agent_coord.server.records.score as rec_score

    published: list[tuple[str, str]] = []

    class _Cn:
        def cursor(self):
            return self

        def execute(self, *a, **k):
            return None

        def fetchall(self):
            return [("mill-office.wasted_wake_n",), ("mill-office.wasted_wake_share",)]

        def close(self):
            return None

    def admin_upsert(cn, kpi, val, tgt, note):
        published.append((kpi, val))
        return 1

    monkeypatch.setattr("agent_coord.server.records.connect", lambda: _Cn())
    monkeypatch.setattr(rec_score, "admin_upsert", admin_upsert)
    monkeypatch.setattr(rec_score, "upsert", lambda *a, **k: 1)
    monkeypatch.setattr(score_tick, "measure_book", lambda cn: {})
    # Host KPIs still publish; only the None wasted-wake keys must be omitted.
    counts = {k: 0 for k in score_tick.HOST_KPIS}
    counts.update(
        {
            score_tick.KPI_TICKS: 0,
            score_tick.KPI_IDLE: 0,
            score_tick.KPI_DROP: 0,
            "mill-office.wasted_wake_n": None,
            "mill-office.wasted_wake_share": None,
            "desks": {},
        }
    )
    out = score_tick.publish(counts)
    assert out["ok"] is True
    assert "mill-office.wasted_wake_n" in (out.get("omitted") or [])
    assert "mill-office.wasted_wake_share" in (out.get("omitted") or [])
    keys = [k for k, _ in published]
    assert "mill-office.wasted_wake_n" not in keys
    assert "mill-office.wasted_wake_share" not in keys


@pytest.mark.sql
def test_finish_lease_writes_wake_done_transition(cn) -> None:
    """Card 1002 on 0.8.6: wasted/why-fired durability on existing transition (W9)."""
    from agent_coord.server.transition_enums import ActivityType, Reason, State
    from tests.server.records.conftest import seed_names

    seed_names(cn, ("ww1002", "roster"), ("wwd", "desk"))
    cur = cn.cursor()
    cur.execute("SELECT id FROM name WHERE type='desk' AND name='wwd'")
    desk_id = int(cur.fetchone()[0])
    cur.close()

    ww.reset_for_tests()
    ww.mark_lease("wwd", trigger="hold_release", wake_id=910002)
    # no action -> wasted
    out = ww.finish_lease("wwd", cn=cn, desk_id=desk_id)
    assert out is not None and out["wasted"] is True and out["trigger"] == "hold_release"
    cn.commit()
    cur = cn.cursor(dictionary=True)
    cur.execute(
        "SELECT activity_type, activity_id, from_state, to_state, reason, desk_id, join_key, meta"
        " FROM transition WHERE activity_type='wake' AND activity_id=910002"
        " ORDER BY id DESC LIMIT 1"
    )
    row = cur.fetchone()
    cur.close()
    assert row is not None
    assert row["from_state"] == State.lease_live.value
    assert row["to_state"] == State.idle.value
    assert row["reason"] == Reason.wake_done.value
    assert int(row["desk_id"]) == desk_id
    assert str(row["join_key"]) == f"wake-lease:{desk_id}:910002"
    meta = row["meta"]
    if isinstance(meta, (bytes, bytearray)):
        meta = meta.decode()
    import json

    if isinstance(meta, str):
        meta = json.loads(meta)
    assert meta.get("wasted") == 1
    assert meta.get("trigger") == "hold_release"
    # no bodies/names/hosts
    blob = json.dumps(meta)
    assert "wwd" not in blob
    assert "host" not in blob.lower()


@pytest.mark.sql
def test_useful_wake_transition_marks_wasted_zero(cn) -> None:
    from tests.server.records.conftest import seed_names

    seed_names(cn, ("ww1002b", "roster"), ("wwb", "desk"))
    cur = cn.cursor()
    cur.execute("SELECT id FROM name WHERE type='desk' AND name='wwb'")
    desk_id = int(cur.fetchone()[0])
    cur.close()
    ww.reset_for_tests()
    ww.mark_lease("wwb", trigger="other", wake_id=910003)
    ww.note_rpc("wwb", "reply", ok=True)
    out = ww.finish_lease("wwb", cn=cn, desk_id=desk_id)
    assert out is not None and out["wasted"] is False
    cn.commit()
    cur = cn.cursor(dictionary=True)
    cur.execute(
        "SELECT meta FROM transition WHERE activity_type='wake' AND activity_id=910003"
        " ORDER BY id DESC LIMIT 1"
    )
    row = cur.fetchone()
    cur.close()
    assert row
    meta = row["meta"]
    import json

    if isinstance(meta, (bytes, bytearray)):
        meta = meta.decode()
    if isinstance(meta, str):
        meta = json.loads(meta)
    assert meta.get("wasted") == 0


def test_mark_lease_stores_wake_row_id_and_meta_fields(monkeypatch) -> None:
    """Card 1098 item 5: W9 activity_id is the wake row id; meta carries pending0/auto."""
    lines: list[str] = []

    def fake_perf(op: str, ms: float = 0.0, **kv):
        lines.append(" ".join([f"op={op}"] + [f"{k}={v}" for k, v in kv.items()]))

    monkeypatch.setattr("agent_coord.server.push.perf_log", fake_perf)
    ww.mark_lease("w5", trigger="other", wake_id=555001, pending0=2, addressed=1, kind="mail")
    out = ww.finish_lease("w5")
    assert out is not None and out["wasted"] is True
    # unit path has no cn; stamp carried wake_id for the SQL path tested below


@pytest.mark.sql
def test_w9_attaches_to_wake_row_id(cn) -> None:
    from tests.server.records.conftest import admin_desk, seed_names
    from agent_coord.server.records import push as rec_push

    seed_names(cn, ("ww1098", "roster"), ("ww1098d", "desk"))
    cur = cn.cursor()
    cur.execute("SELECT id FROM name WHERE type='desk' AND name='ww1098d'")
    desk_id = int(cur.fetchone()[0])
    cur.close()
    wid = rec_push.row_id(rec_push.put(cn, "ww1098d", "hint", {"type": "todo", "id": 1}, "queued"))
    cn.commit()
    ww.reset_for_tests()
    ww.mark_lease("ww1098d", trigger="other", wake_id=wid, pending0=1, addressed=1, kind="hint")
    out = ww.finish_lease("ww1098d", cn=cn, desk_id=desk_id)
    assert out is not None
    cn.commit()
    cur = cn.cursor(dictionary=True)
    cur.execute(
        "SELECT activity_id, meta FROM transition"
        " WHERE activity_type='wake' AND reason='wake_done' AND activity_id=%s"
        " ORDER BY id DESC LIMIT 1",
        (wid,),
    )
    row = cur.fetchone()
    cur.close()
    assert row is not None and int(row["activity_id"]) == wid
    import json
    meta = row["meta"]
    if isinstance(meta, (bytes, bytearray)):
        meta = meta.decode()
    if isinstance(meta, str):
        meta = json.loads(meta)
    assert meta.get("pending0") == 1
    assert meta.get("addressed") == 1
    assert meta.get("kind") == "hint"
    assert meta.get("auto") == 0


def test_auto_done_on_mark_when_lease_clear(monkeypatch) -> None:
    """mark of the only lease letter with nothing addressed pending -> W9 auto=1."""
    from agent_coord.server import wake as wake_mod

    lines: list[str] = []
    monkeypatch.setattr("agent_coord.server.push.perf_log", lambda *a, **k: lines.append(a))
    wake_mod.gate_clear("auto-d")
    # simulate a live lease with one mail
    import time
    with wake_mod._GATE_LOCK:
        wake_mod._GATE["auto-d"] = time.monotonic()
        wake_mod._EPOCH["auto-d"] = "tok"
        wake_mod._LEASE_MAIL["auto-d"] = {42}
    ww.reset_for_tests()
    ww.mark_lease("auto-d", trigger="other", wake_id=9001, kind="mail", addressed=1)
    monkeypatch.setattr(wake_mod, "mail_picked_up", lambda cn, d, mid: mid == 42)
    monkeypatch.setattr("agent_coord.server.records.push.pending_addressed", lambda cn, d: False)
    monkeypatch.setattr("agent_coord.server.mail_push.has_unopened_receipt", lambda cn, d: False)
    got = wake_mod.auto_done(object(), "auto-d")
    assert got in ("none", "sent", "sitting", "stale")
    snap = ww.desk_snapshot("auto-d")
    assert snap["wakes"] == 1
    # second explicit wake-done is stale/no-op
    assert wake_mod.lease_done(None, "auto-d") in ("stale", "none")


def test_auto_done_skips_when_addressed_still_waits(monkeypatch) -> None:
    from agent_coord.server import wake as wake_mod
    import time

    wake_mod.gate_clear("auto-w")
    with wake_mod._GATE_LOCK:
        wake_mod._GATE["auto-w"] = time.monotonic()
        wake_mod._EPOCH["auto-w"] = "tok"
        wake_mod._LEASE_MAIL["auto-w"] = {7}
    ww.reset_for_tests()
    ww.mark_lease("auto-w", trigger="other", wake_id=9002)
    monkeypatch.setattr(wake_mod, "mail_picked_up", lambda cn, d, mid: True)
    monkeypatch.setattr("agent_coord.server.records.push.pending_addressed", lambda cn, d: True)
    assert wake_mod.auto_done(object(), "auto-w") == ""
    assert ww.desk_snapshot("auto-w")["wakes"] == 0  # lease not finished


def test_reply_auto_done_is_not_wasted(monkeypatch) -> None:
    """A reply that auto-ends the only letter in a lease is acted, not wasted.

    0.8.10 regression (card 1090): auto_done ran in after_commit inside
    _run_command, before dispatch called wasted_wake.note_rpc, so the reply
    that ended the lease was scored wasted. auto_done must count the
    triggering command first.
    """
    from agent_coord.server import wake as wake_mod
    import time

    lines: list[str] = []

    def fake_perf(op: str, ms: float = 0.0, **kv):
        lines.append(" ".join([f"op={op}"] + [f"{k}={v}" for k, v in kv.items()]))

    monkeypatch.setattr("agent_coord.server.push.perf_log", fake_perf)
    wake_mod.gate_clear("auto-r")
    with wake_mod._GATE_LOCK:
        wake_mod._GATE["auto-r"] = time.monotonic()
        wake_mod._EPOCH["auto-r"] = "tok"
        wake_mod._LEASE_MAIL["auto-r"] = {42}
    ww.reset_for_tests()
    ww.mark_lease("auto-r", trigger="other", wake_id=9105, kind="mail", addressed=1)
    monkeypatch.setattr(wake_mod, "mail_picked_up", lambda cn, d, mid: mid == 42)
    monkeypatch.setattr("agent_coord.server.records.push.pending_addressed", lambda cn, d: False)
    monkeypatch.setattr("agent_coord.server.mail_push.has_unopened_receipt", lambda cn, d: False)
    # Production order on the reply path: after_commit(auto_done), then note_rpc.
    got = wake_mod.auto_done(object(), "auto-r", command="reply")
    ww.note_rpc("auto-r", "reply", ok=True)
    assert got in ("none", "sent", "sitting", "stale")
    snap = ww.desk_snapshot("auto-r")
    assert snap["wakes"] == 1
    assert snap["wasted"] == 0
    assert any("op=wake.done" in L and "wasted=0" in L for L in lines)


def test_mark_auto_done_is_still_wasted(monkeypatch) -> None:
    """mark alone still wastes, even when it auto-ends the lease (card 1090)."""
    from agent_coord.server import wake as wake_mod
    import time

    lines: list[str] = []

    def fake_perf(op: str, ms: float = 0.0, **kv):
        lines.append(" ".join([f"op={op}"] + [f"{k}={v}" for k, v in kv.items()]))

    monkeypatch.setattr("agent_coord.server.push.perf_log", fake_perf)
    wake_mod.gate_clear("auto-m")
    with wake_mod._GATE_LOCK:
        wake_mod._GATE["auto-m"] = time.monotonic()
        wake_mod._EPOCH["auto-m"] = "tok"
        wake_mod._LEASE_MAIL["auto-m"] = {42}
    ww.reset_for_tests()
    ww.mark_lease("auto-m", trigger="other", wake_id=9106, kind="mail", addressed=1)
    monkeypatch.setattr(wake_mod, "mail_picked_up", lambda cn, d, mid: mid == 42)
    monkeypatch.setattr("agent_coord.server.records.push.pending_addressed", lambda cn, d: False)
    monkeypatch.setattr("agent_coord.server.mail_push.has_unopened_receipt", lambda cn, d: False)
    got = wake_mod.auto_done(object(), "auto-m", command="mark")
    ww.note_rpc("auto-m", "mark", ok=True)
    assert got in ("none", "sent", "sitting", "stale")
    snap = ww.desk_snapshot("auto-m")
    assert snap["wakes"] == 1
    assert snap["wasted"] == 1
    assert any("op=wake.done" in L and "wasted=1" in L for L in lines)


def test_reply_and_mark_handlers_pass_command_to_auto_done() -> None:
    """Catch unwiring: the reply and mark handlers must name the command."""
    import inspect

    from agent_coord.server.api.mill import rpc

    assert 'command="reply"' in inspect.getsource(rpc._h_reply)
    assert 'command="mark"' in inspect.getsource(rpc._h_mark)


@pytest.mark.sql
def test_reply_auto_done_w9_meta_wasted_zero_auto(cn, monkeypatch) -> None:
    """Reply auto-end writes W9 meta wasted=0, auto=1 (card 1090)."""
    import time

    from agent_coord.server import wake as wake_mod
    from tests.server.records.conftest import seed_names
    from agent_coord.server.records import push as rec_push

    seed_names(cn, ("ww1090", "roster"), ("ww1090d", "desk"))
    cur = cn.cursor()
    cur.execute("SELECT id FROM name WHERE type='desk' AND name='ww1090d'")
    desk_id = int(cur.fetchone()[0])
    cur.close()
    wid = rec_push.row_id(rec_push.put(cn, "ww1090d", "hint", {"type": "mail", "id": 42}, "queued"))
    cn.commit()
    wake_mod.gate_clear("ww1090d")
    with wake_mod._GATE_LOCK:
        wake_mod._GATE["ww1090d"] = time.monotonic()
        wake_mod._EPOCH["ww1090d"] = "tok"
        wake_mod._LEASE_MAIL["ww1090d"] = {42}
    ww.reset_for_tests()
    ww.mark_lease("ww1090d", trigger="other", wake_id=wid, pending0=0, addressed=1, kind="mail")
    monkeypatch.setattr(wake_mod, "mail_picked_up", lambda c, d, mid: mid == 42)
    monkeypatch.setattr("agent_coord.server.records.push.pending_addressed", lambda c, d: False)
    monkeypatch.setattr("agent_coord.server.mail_push.has_unopened_receipt", lambda c, d: False)
    got = wake_mod.auto_done(cn, "ww1090d", command="reply")
    assert got in ("none", "sent", "sitting", "stale")
    cn.commit()
    cur = cn.cursor(dictionary=True)
    cur.execute(
        "SELECT meta FROM transition"
        " WHERE activity_type='wake' AND reason='wake_done' AND activity_id=%s"
        " ORDER BY id DESC LIMIT 1",
        (wid,),
    )
    row = cur.fetchone()
    cur.close()
    assert row is not None
    import json

    meta = row["meta"]
    if isinstance(meta, (bytes, bytearray)):
        meta = meta.decode()
    if isinstance(meta, str):
        meta = json.loads(meta)
    assert meta.get("wasted") == 0
    assert meta.get("auto") == 1
