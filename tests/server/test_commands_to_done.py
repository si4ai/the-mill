# -*- coding: utf-8 -*-
"""A6 commands-to-done: stamp formula + score_tick scrape."""
from datetime import datetime, timezone
from pathlib import Path

from agent_coord.server import commands_to_done as vtd
from agent_coord.server.score_tick import (
    BOOK_PERF,
    BOOK_TARGET,
    KPI_COMMANDS_TO_DONE,
    measure,
    measure_commands_to_done,
)


def setup_function() -> None:
    vtd.reset_for_tests()


def test_book_commands_to_done_kpi_formula() -> None:
    assert KPI_COMMANDS_TO_DONE in BOOK_PERF
    assert BOOK_TARGET[KPI_COMMANDS_TO_DONE] == ""
    assert "command" in BOOK_PERF[KPI_COMMANDS_TO_DONE].lower()
    assert "note" in BOOK_PERF[KPI_COMMANDS_TO_DONE].lower()
    assert KPI_COMMANDS_TO_DONE == "mill-office.verbs_to_done"


def test_claim_to_done_counts_card_moves(monkeypatch) -> None:
    lines: list[str] = []

    def fake_perf(op: str, ms: float, **kv):
        parts = [f"op={op}", f"ms={ms:.1f}"] + [f"{k}={v}" for k, v in kv.items()]
        lines.append(" ".join(parts))

    monkeypatch.setattr("agent_coord.server.push.perf_log", fake_perf)
    desk = "DESK_builder"
    need = "floor-v1-parts"
    # claim starts window (verbs=1)
    vtd.note_card(desk, "claim", {"ok": True, "need_id": need, "id": 42, "status": "claimed"})
    snap = vtd.session_snapshot(need)
    assert snap and snap["verbs"] == 1 and snap["notes"] == 0
    # a retired note command is not a card verb and does not increment notes
    vtd.note_card(desk, "note", {"need_id": need, "id": 42, "detail": "a"})
    snap = vtd.session_snapshot(need)
    assert snap["verbs"] == 1
    assert snap["notes"] == 0
    # pass claimed -> shipped counts
    vtd.note_card(desk, "pass", {"ok": True, "need": need, "status": "shipped", "id": 42})
    snap = vtd.session_snapshot(need)
    assert snap["verbs"] == 2
    assert len(lines) == 0  # not done yet
    # pass shipped -> done stamps
    vtd.note_card(desk, "pass", {"ok": True, "need": need, "status": "done", "id": 42})
    assert len(lines) == 1
    assert "op=card.verbs_to_done" in lines[0]
    assert "verbs=3" in lines[0]  # claim + pass shipped + pass done
    assert "notes=0" in lines[0]
    assert "card=42" in lines[0]
    assert "need=floor-v1-parts" in lines[0]
    assert "desk=DESK_builder" in lines[0]
    assert vtd.session_snapshot(need) is None


def test_unclaim_clears_without_stamp(monkeypatch) -> None:
    lines: list[tuple] = []
    monkeypatch.setattr(
        "agent_coord.server.push.perf_log",
        lambda op, ms, **kv: lines.append((op, ms, kv)),
    )
    desk = "DESK_agent"
    need = "aws-56"
    vtd.note_card(desk, "claim", {"ok": True, "need_id": need, "id": 56, "status": "claimed"})
    vtd.note_card(desk, "unclaim", {"ok": True, "need": need, "status": "open"})
    assert lines == []
    assert vtd.session_snapshot(need) is None


def test_assign_starts_window_for_volunteer(monkeypatch) -> None:
    lines: list[tuple] = []
    monkeypatch.setattr(
        "agent_coord.server.push.perf_log",
        lambda op, ms, **kv: lines.append((op, ms, kv)),
    )
    need = "shot-a6"
    vtd.note_card(
        "DESK_admin",
        "assign",
        {"ok": True, "need_id": need, "id": 7, "status": "claimed", "volunteer": "DESK_scout"},
    )
    snap = vtd.session_snapshot(need)
    assert snap and snap["desk"] == "DESK_scout" and snap["verbs"] == 1
    vtd.note_card("DESK_scout", "pass", {"ok": True, "need": need, "status": "shipped", "id": 7})
    vtd.note_card("DESK_ask", "pass", {"ok": True, "need": need, "status": "done", "id": 7})
    assert len(lines) == 1
    assert lines[0][0] == "card.verbs_to_done"
    assert lines[0][2]["verbs"] == 3
    assert lines[0][2]["desk"] == "DESK_scout"
    assert lines[0][2]["notes"] == 0


def test_measure_commands_to_done_p50() -> None:
    text = "\n".join(
        [
            "2026-09-27T10:00:00Z op=card.verbs_to_done ms=100.0 verbs=2 notes=0 card=1 need=a desk=DESK_a ok=1",
            "2026-09-27T10:00:01Z op=card.verbs_to_done ms=300.0 verbs=8 notes=5 card=2 need=b desk=DESK_b ok=1",
            "2026-09-27T10:00:02Z op=card.verbs_to_done ms=200.0 verbs=4 notes=1 card=3 need=c desk=DESK_c ok=1",
            "2026-09-27T09:00:00Z op=card.verbs_to_done ms=999.0 verbs=99 notes=9 card=9 need=old desk=DESK_old ok=1",
        ]
    )
    since = datetime(2026, 9, 27, 9, 30, 0, tzinfo=timezone.utc)
    # sorted 2,4,8 -> p50 index round(0.5*2)=1 -> 4
    assert measure_commands_to_done(text, since) == 4


def test_measure_includes_commands_to_done_kpi(tmp_path: Path) -> None:
    (tmp_path / "mill-perf.log").write_text(
        "2026-09-27T10:00:00Z op=card.verbs_to_done ms=150.0 verbs=5 notes=2 card=56 need=aws-56 desk=DESK_x ok=1\n",
        encoding="utf-8",
    )
    now = datetime(2026, 9, 27, 10, 30, 0, tzinfo=timezone.utc)
    row = measure(dest=tmp_path, window_s=3600, now=now)
    assert row[KPI_COMMANDS_TO_DONE] == 5


def test_publish_book_perf_commands_to_done_empty_target() -> None:
    from agent_coord.server import score_tick as st

    note = st.BOOK_PERF[KPI_COMMANDS_TO_DONE]
    tgt = st.BOOK_TARGET.get(KPI_COMMANDS_TO_DONE, st.TARGET)
    row = {"kpi": KPI_COMMANDS_TO_DONE, "value": "5", "target": tgt, "note": note}
    assert row["target"] == ""
    assert row["value"] == "5"
