# -*- coding: utf-8 -*-
"""A1 wake -> first day-one command: stamp formula + score_tick scrape."""
from datetime import datetime, timezone
from pathlib import Path

from agent_coord.server import wake_first as wf
from agent_coord.server.score_tick import (
    BOOK_PERF,
    BOOK_TARGET,
    KPI_WAKE_MS,
    KPI_WAKE_RPC,
    measure,
    measure_wake_first,
)


def setup_function() -> None:
    wf.reset_for_tests()


def test_day_one_ok_commands_cover_skill_spine() -> None:
    need = {"todo", "open", "claim", "send", "reply", "hold", "inbox", "mail-thread", "pass", "drop"}
    assert need <= wf.DAY_ONE_OK_COMMANDS
    assert "wake" not in wf.DAY_ONE_OK_COMMANDS
    assert "heartbeat" not in wf.DAY_ONE_OK_COMMANDS


def test_wake_first_stamp_once_counts_rpc(monkeypatch, tmp_path: Path) -> None:
    lines: list[str] = []

    def fake_perf(op: str, ms: float, **kv):
        parts = [f"op={op}", f"ms={ms:.1f}"] + [f"{k}={v}" for k, v in kv.items()]
        lines.append(" ".join(parts))

    monkeypatch.setattr("agent_coord.server.push.perf_log", fake_perf)
    desk = "DESK_builder"
    wf.mark_wake(desk)
    wf.note_rpc(desk, "heartbeat", ok=True)  # skip
    wf.note_rpc(desk, "todo", ok=False)  # count fail
    wf.note_rpc(desk, "claim", ok=True)  # first ok -> stamp
    wf.note_rpc(desk, "send", ok=True)  # ignored after stamp
    assert len(lines) == 1
    assert "op=wake.first_ok" in lines[0]
    assert "rpc=2" in lines[0]  # failed todo + claim
    assert "wrong=1" in lines[0]  # A2: failed todo
    assert "retry=0" in lines[0]  # A2: claim had no prior fail
    assert "verb=claim" in lines[0]
    assert "desk=DESK_builder" in lines[0]
    snap = wf.session_snapshot(desk)
    assert snap and snap["stamped"] is True


def test_book_wake_first_kpi_formula() -> None:
    assert KPI_WAKE_MS in BOOK_PERF
    assert KPI_WAKE_RPC in BOOK_PERF
    assert BOOK_TARGET[KPI_WAKE_MS] == ""
    assert BOOK_TARGET[KPI_WAKE_RPC] == ""
    assert "p50" in BOOK_PERF[KPI_WAKE_MS]
    assert "rpc" in BOOK_PERF[KPI_WAKE_RPC].lower()
    # A2 keys share BOOK_PERF; presence checked in test_wrong_retry
    assert "mill-office.wrong_verb_n" in BOOK_PERF
    assert "mill-office.retry_before_ok" in BOOK_PERF


def test_measure_wake_first_p50() -> None:
    text = "\n".join(
        [
            "2026-09-27T10:00:00Z op=wake.first_ok ms=100.0 rpc=2 desk=DESK_a verb=claim ok=1",
            "2026-09-27T10:00:01Z op=wake.first_ok ms=300.0 rpc=4 desk=DESK_b verb=inbox ok=1",
            "2026-09-27T10:00:02Z op=wake.first_ok ms=200.0 rpc=3 desk=DESK_c verb=send ok=1",
            "2026-09-27T09:00:00Z op=wake.first_ok ms=999.0 rpc=9 desk=DESK_old verb=hold ok=1",
        ]
    )
    since = datetime(2026, 9, 27, 9, 30, 0, tzinfo=timezone.utc)
    ms, rpc = measure_wake_first(text, since)
    # sorted ms 100,200,300 -> p50 index round(0.5*2)=1 -> 200
    assert ms == 200
    # sorted rpc 2,3,4 -> 3
    assert rpc == 3


def test_measure_includes_wake_first_kpis(tmp_path: Path) -> None:
    (tmp_path / "mill-perf.log").write_text(
        "2026-09-27T10:00:00Z op=wake.first_ok ms=150.0 rpc=5 desk=DESK_x verb=todo ok=1\n",
        encoding="utf-8",
    )
    now = datetime(2026, 9, 27, 10, 30, 0, tzinfo=timezone.utc)
    row = measure(dest=tmp_path, window_s=3600, now=now)
    assert row[KPI_WAKE_MS] == 150
    assert row[KPI_WAKE_RPC] == 5


def test_publish_book_perf_empty_target() -> None:
    from agent_coord.server import score_tick as st

    book = {KPI_WAKE_MS: 120, KPI_WAKE_RPC: 3}
    rows = []
    for kpi, n in book.items():
        note = st.BOOK_PERF[kpi]
        tgt = st.BOOK_TARGET.get(kpi, st.TARGET)
        rows.append({"kpi": kpi, "value": str(int(n)), "target": tgt, "note": note})
    by = {r["kpi"]: r for r in rows}
    assert by[KPI_WAKE_MS]["target"] == ""
    assert by[KPI_WAKE_RPC]["target"] == ""
    assert by[KPI_WAKE_MS]["value"] == "120"
