# -*- coding: utf-8 -*-
"""Card 1002 / F-wasted-wake-score: no-action wakes counted and tagged by trigger.

Measure only. A wake that ends in wake-done with no send/reply/claim/note/pass/hold/label
counts as wasted (mark and read alone still waste). Tags: hold_release, room_or_fyi_mail,
rering_handled, version_notice, other. mill score shows per-desk and per-office count,
share and trigger breakdown. Does not change wake behavior (card 949 rules stay off).
"""
from __future__ import annotations

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
    assert len(lines) == 1
    assert "op=wake.wasted" in lines[0]
    assert "trigger=hold_release" in lines[0]
    assert "desk=desk_a" in lines[0]


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
    assert lines == []


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


def test_measure_scrapes_wasted_wake(tmp_path: Path) -> None:
    (tmp_path / "mill-perf.log").write_text(
        "\n".join(
            [
                "2026-11-01T10:00:00Z op=wake.wasted trigger=hold_release desk=a wasted=1 wakes=1",
                "2026-11-01T10:00:01Z op=wake.wasted trigger=other desk=b wasted=1 wakes=1",
                "2026-11-01T09:00:00Z op=wake.wasted trigger=other desk=old wasted=1 wakes=1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    now = datetime(2026, 11, 1, 10, 30, 0, tzinfo=timezone.utc)
    row = measure(dest=tmp_path, window_s=3600, now=now)
    assert row[ww.KPI_WASTED] == 2
    # share: 2 wasted in window; wakes counted on lines is 2 -> share 100 (percent int)
    assert row[ww.KPI_SHARE] == 100


def test_score_view_shape() -> None:
    ww.mark_lease("v1", trigger="version_notice")
    ww.finish_lease("v1")
    view = ww.score_view("v1")
    assert view["wasted"] == 1
    assert view["wakes"] == 1
    assert view["share"] == 1.0
    assert view["triggers"]["version_notice"] == 1
    assert view["unit"] == "wakes"
