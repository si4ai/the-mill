"""score_tick never looks Admin up as a desk; office rows have no desk (beta 0.8.0)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]


def test_office_kpis_use_admin_upsert_desk_kpis_use_desk():
    from agent_coord.server import score_tick as st

    admin_calls, desk_calls = [], []
    cn = MagicMock()
    cur = MagicMock()
    cur.fetchall.return_value = []
    cn.cursor.return_value = cur
    with patch("agent_coord.server.records.connect", return_value=cn), patch(
        "agent_coord.server.records.score.admin_upsert",
        side_effect=lambda _c, kpi, *a: admin_calls.append(kpi) or [{"id": 1}],
    ), patch(
        "agent_coord.server.records.score.upsert",
        side_effect=lambda _c, roster, desk, kpi, *a: desk_calls.append((roster, desk, kpi)) or [{"id": 2}],
    ), patch("agent_coord.server.records.db.call", return_value=[]):
        out = st.publish({st.KPI_TICKS: 1, "desks": {"d1": {st.KPI_TICKS: 1}}})
    assert out["ok"] is True and "fallback" not in out
    assert set(st.DESK_KPIS) | set(st.HOST_KPIS) <= set(admin_calls)
    assert desk_calls and all(desk == "d1" and roster == st.ROSTER for roster, desk, _ in desk_calls)
    assert all(desk != st.OWNER for _, desk, _ in desk_calls)


def test_no_upsert_names_admin_as_a_desk():
    src = (ROOT / "agent_coord" / "server" / "score_tick.py").read_text(encoding="utf-8")
    assert "ROSTER, OWNER, kpi" not in src and "ROSTER,\n                OWNER," not in src
    assert "desk_id=2" not in src


def test_fallback_updates_the_office_rows_with_no_desk():
    # Beta 0.8.0: office rows are roster 1 with desk_id NULL; the fallback reads no roster ids.
    from agent_coord.server import score_tick as st

    cur = MagicMock()
    cn = MagicMock()
    cn.cursor.return_value = cur
    st._publish_sql(cn, {st.KPI_TICKS: 3, st.KPI_IDLE: 0, st.KPI_DROP: 0})
    updates = [c for c in cur.execute.call_args_list if "UPDATE score" in c.args[0]]
    assert len(updates) == 3
    assert all("roster_id=1 AND desk_id IS NULL" in c.args[0] for c in updates)
    assert all(c.args[1][0] in ("3", "0") for c in updates)
    assert cn.commit.called


def test_fallback_failure_does_not_commit():
    import pytest

    from agent_coord.server import score_tick as st

    cur = MagicMock()
    cur.execute.side_effect = RuntimeError("book down")
    cn = MagicMock()
    cn.cursor.return_value = cur
    with pytest.raises(RuntimeError, match="book down"):
        st._publish_sql(cn, {})
    assert not cn.commit.called


def test_fallback_has_no_admin_desk_lookup():
    src = (ROOT / "agent_coord" / "server" / "score_tick.py").read_text(encoding="utf-8")
    assert "Admin roster missing" not in src
    assert "desk_id=%s" not in src.split("def _publish_sql", 1)[1].split("def tick", 1)[0]



def test_regression_row_f19_documented():
    doc = (ROOT / "docs" / "protocol" / "records.md").read_text(encoding="utf-8")
    assert "Regression row F19 (score-tick-admin-roster)" in doc
    sql = (ROOT / "agent_coord" / "server" / "sql" / "sp_score.sql").read_text(encoding="utf-8")
    assert "DROP PROCEDURE IF EXISTS mill_score_admin_upsert;" in sql
    wipe = (ROOT / "agent_coord" / "server" / "sql" / "wipe.sql").read_text(encoding="utf-8")
    assert "DROP PROCEDURE IF EXISTS mill_score_admin_upsert;" in wipe
