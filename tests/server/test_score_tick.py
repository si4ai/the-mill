# -*- coding: utf-8 -*-
from datetime import datetime, timezone

from agent_coord.server.score_tick import (
    KPI_API_MS,
    KPI_API_N,
    KPI_DROP,
    KPI_ERR_N,
    KPI_FLOOR_MS,
    KPI_FLOOR_N,
    KPI_IDLE,
    KPI_TICKS,
    KPI_WS_MISS,
    KPI_WS_PUSH,
    count_api,
    count_drops,
    count_perf,
    measure,
)


def test_count_perf_heartbeat_and_idle() -> None:
    text = "\n".join(
        [
            "2026-09-17T10:00:00Z op=api.mill.heartbeat ms=120 status=200",
            "2026-09-17T10:00:15Z op=api.mill.heartbeat ms=110 status=200",
            "2026-09-17T10:01:00Z op=api.mill.inbox ms=164 status=200",
            "2026-09-17T10:01:01Z op=api.mill.send ms=80 status=200",
            "2026-09-17T09:00:00Z op=api.mill.heartbeat ms=100 status=200",
        ]
    )
    since = datetime(2026, 9, 17, 9, 30, 0, tzinfo=timezone.utc)
    ticks, idle = count_perf(text, since)
    assert ticks == 2
    assert idle == 1


def test_count_api_commands() -> None:
    text = "\n".join(
        [
            "2026-09-17T10:00:00Z POST /api/mill/heartbeat 200 ms=63",
            "2026-09-17T10:00:01Z POST /api/mill/wake 400 ms=20",
            "2026-09-17T10:00:02Z POST /api/mill/send 200 ms=80",
        ]
    )
    since = datetime(2026, 9, 17, 9, 0, 0, tzinfo=timezone.utc)
    ticks, idle = count_api(text, since)
    assert ticks == 1
    assert idle == 1


def test_measure_prefers_perf(tmp_path) -> None:
    (tmp_path / "mill-perf.log").write_text(
        "2026-09-17T10:00:00Z op=api.mill.heartbeat ms=1 status=200\n",
        encoding="utf-8",
    )
    (tmp_path / "mill-api.log").write_text(
        "2026-09-17T10:00:00Z POST /api/mill/heartbeat 200 ms=1\n",
        encoding="utf-8",
    )
    now = datetime(2026, 9, 17, 10, 30, 0, tzinfo=timezone.utc)
    row = measure(dest=tmp_path, window_s=3600, now=now)
    assert row[KPI_TICKS] == 1
    assert row[KPI_IDLE] == 0
    assert row[KPI_DROP] == 0


def test_count_drops_perf_and_backchannel() -> None:
    since = datetime(2026, 9, 17, 10, 0, 0, tzinfo=timezone.utc)
    perf = "\n".join(
        [
            "2026-09-17T10:00:01Z op=ws.recv ms=0.0 desk=DESK_alice hint=MAIL id=1 q=256 drop=1 frame_b=48",
            "2026-09-17T10:00:02Z op=ws.recv ms=0.0 desk=DESK_alice hint=MAIL id=2 q=1 drop=0 frame_b=48",
            "2026-09-17T09:00:00Z op=ws.recv ms=0.0 desk=DESK_alice hint=MAIL id=9 q=256 drop=1 frame_b=48",
        ]
    )
    bc = "2026-09-17T10:00:01Z hint drop desk=DESK_alice hint=MAIL id=1 q=255\n"
    assert count_drops(perf, since) == 1
    assert count_drops(bc, since, backchannel=True) == 1


def test_measure_hint_drop_prefers_perf(tmp_path) -> None:
    (tmp_path / "mill-perf.log").write_text(
        "2026-09-17T10:00:00Z op=ws.recv ms=0.0 desk=DESK_alice hint=MAIL id=1 q=256 drop=1 frame_b=48\n",
        encoding="utf-8",
    )
    (tmp_path / "mill-backchannel.log").write_text(
        "2026-09-17T10:00:00Z hint drop desk=DESK_alice hint=MAIL id=1 q=255\n",
        encoding="utf-8",
    )
    now = datetime(2026, 9, 17, 10, 30, 0, tzinfo=timezone.utc)
    row = measure(dest=tmp_path, window_s=3600, now=now)
    assert row[KPI_DROP] == 1


def test_measure_host_surfaces(tmp_path) -> None:
    (tmp_path / "mill-api.log").write_text(
        "\n".join(
            [
                "2026-09-17T10:00:00Z POST /api/mill/send 200 req_b=10 resp_b=20 ms=5",
                "2026-09-17T10:00:01Z GET /api/floor 200 resp_b=27000 ms=80",
                "2026-09-17T10:00:02Z POST /api/mill/inbox 500 req_b=8 resp_b=40 ms=3",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "mill-backchannel.log").write_text(
        "\n".join(
            [
                "2026-09-17T10:00:00Z ws push desk=DESK_alice hint=MAIL ok=1",
                "2026-09-17T10:00:01Z fanout miss desk=DESK_bob hint=TODO",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    now = datetime(2026, 9, 17, 10, 30, 0, tzinfo=timezone.utc)
    row = measure(dest=tmp_path, window_s=3600, now=now)
    assert row[KPI_API_N] == 2
    assert row[KPI_FLOOR_N] == 1
    assert row[KPI_ERR_N] == 1
    assert row[KPI_WS_PUSH] == 1
    assert row[KPI_WS_MISS] == 1


def test_api_ms_p95_includes_ws_command(tmp_path) -> None:
    (tmp_path / "mill-perf.log").write_text(
        "\n".join(
            [
                "2026-09-17T10:00:00Z op=api.mill.reply ms=40.0 desk=a verb=reply ok=1",
                "2026-09-17T10:00:01Z op=verb ms=180.5 desk=b verb=todo ok=1",
                "2026-09-17T10:00:02Z op=api.floor ms=9000.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    now = datetime(2026, 9, 17, 10, 30, 0, tzinfo=timezone.utc)
    row = measure(dest=tmp_path, window_s=3600, now=now)
    assert row[KPI_API_MS] == 180
    assert row[KPI_FLOOR_MS] == 9000
    assert row[KPI_TICKS] == 0
    assert row[KPI_IDLE] == 1


def test_book_activities_kpi_formula() -> None:
    from agent_coord.server.score_tick import BOOK_SQL, BOOK_TARGET, WINDOW_S

    assert "mill-office.activities" in BOOK_SQL
    sql, note = BOOK_SQL["mill-office.activities"]
    assert "FROM activity" in sql
    assert f"INTERVAL {WINDOW_S} SECOND" in sql
    assert "updated >=" in sql
    assert "informational" in note
    assert BOOK_TARGET["mill-office.activities"] == ""
    assert WINDOW_S == 3600


def test_measure_book_activities_window() -> None:
    """Opt-in book path: COUNT activity rows in WINDOW_S via measure_book."""
    from agent_coord.server import score_tick as st

    class FakeCur:
        def __init__(self) -> None:
            self.ops: list[tuple] = []

        def execute(self, sql, args=None) -> None:
            self.ops.append((sql, args))

        def fetchall(self):
            # score rows that opt in the activities KPI
            if self.ops and "FROM score" in self.ops[-1][0]:
                return [("mill-office.activities",), ("todo.open",)]
            return []

        def fetchone(self):
            sql = self.ops[-1][0]
            if "FROM activity" in sql:
                return (42,)
            if "FROM todo" in sql:
                return (3,)
            return (0,)

        def close(self) -> None:
            pass

    class FakeCn:
        def cursor(self):
            return FakeCur()

    out = st.measure_book(FakeCn())
    assert out["mill-office.activities"] == 42
    assert out["todo.open"] == 3


def test_publish_book_activities_empty_target() -> None:
    """Informational book KPI publishes target "" (like api_n/floor_n)."""
    from agent_coord.server import score_tick as st

    book = {"mill-office.activities": 7, "todo.shipped": 1}
    rows = []
    for kpi, n in book.items():
        note = st.BOOK_SQL[kpi][1]
        tgt = st.BOOK_TARGET.get(kpi, st.TARGET)
        rows.append({"kpi": kpi, "value": str(int(n)), "target": tgt, "note": note})
    by_kpi = {r["kpi"]: r for r in rows}
    assert by_kpi["mill-office.activities"]["target"] == ""
    assert by_kpi["mill-office.activities"]["value"] == "7"
    assert by_kpi["todo.shipped"]["target"] == "0"


def test_p50_empty_sample_is_missing_not_zero() -> None:
    """Card 1019: no samples means missing, never a green numeric zero."""
    from agent_coord.server.score_tick import _p50

    assert _p50([]) is None


def test_p95_empty_sample_is_missing_not_zero() -> None:
    """Card 1019: empty p95 sample is missing, not 0."""
    from agent_coord.server.score_tick import _p95

    assert _p95([]) is None


def test_publish_omits_missing_host_ms_and_keeps_measured_zero() -> None:
    """Card 1019: None host ms omitted; measured 0 still publishes as 0."""
    from unittest.mock import MagicMock, patch

    from agent_coord.server import score_tick as st

    admin: list[tuple[str, str]] = []
    cn = MagicMock()
    cur = MagicMock()
    cur.fetchall.return_value = []
    cn.cursor.return_value = cur

    def _admin(_c, kpi, val, *a):
        admin.append((kpi, val))
        return [{"id": 1}]

    counts = {
        st.KPI_TICKS: 0,
        st.KPI_IDLE: 2,
        st.KPI_DROP: 0,
        st.KPI_API_MS: None,  # empty percentile sample
        st.KPI_FLOOR_MS: None,
        st.KPI_API_N: 3,  # real count
        "desks": {},
    }
    with patch("agent_coord.server.records.connect", return_value=cn), patch(
        "agent_coord.server.records.score.admin_upsert", side_effect=_admin
    ), patch("agent_coord.server.records.score.upsert", return_value=[{"id": 2}]), patch(
        "agent_coord.server.records.db.call", return_value=[]
    ), patch("agent_coord.server.score_tick.measure_book", return_value={}):
        out = st.publish(counts)
    assert out["ok"] is True
    by_kpi = {k: v for k, v in admin}
    assert by_kpi[st.KPI_TICKS] == "0"
    assert by_kpi[st.KPI_IDLE] == "2"
    assert by_kpi[st.KPI_API_N] == "3"
    assert st.KPI_API_MS not in by_kpi
    assert st.KPI_FLOOR_MS not in by_kpi
    omitted = out.get("omitted") or []
    assert st.KPI_API_MS in omitted and st.KPI_FLOOR_MS in omitted
