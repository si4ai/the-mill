"""Table-driven scorecards pure rules (hot, window, Needs fallback, pulse).

Contract: agent_coord.web.wall_logic.score is SoR; board.html must call-equivalent.
"""
from __future__ import annotations

import re

from pathlib import Path
from datetime import datetime, timedelta, timezone

import pytest

from agent_coord.web.wall_logic import (
    kpi_miss,
    score_desk_rows,
    score_desk_table_list,
    score_ensure_paint_contract,
    score_hot_list,
    score_in_window,
    score_prefer_desk,
    score_pulse_counts,
    score_window_ms,
)
from agent_coord.web.wall_logic.score import (
    BOARD_EQUIVALENT_MARKER,
    numish,
    score_delta,
    score_parse_at,
    score_source_job,
    score_spend_pulse,
    score_trend,
    score_waiting,
)


def _ms(dt: datetime) -> float:
    return dt.timestamp() * 1000.0


NOW = datetime(2026, 9, 10, 20, 0, 0, tzinfo=timezone.utc)
NOW_MS = _ms(NOW)


def test_marker_wall_logic_score_sor():
    assert BOARD_EQUIVALENT_MARKER == "WALL_LOGIC_SCORE_SOR"
    c = score_ensure_paint_contract()
    assert c["marker"] == "WALL_LOGIC_SCORE_SOR"
    assert c["pure"] is True
    assert c["ensure_fn"] == "ensureScorePaint"
    assert c["desk_table_fallback_when_needs_empty"] is True
    assert c["hot_list_no_fallback"] is True
    assert c["pulse_always_from_kpis"] is True
    assert "score" in c["tabs"] and "scorecards" in c["tabs"]
    assert c["hash_aliases"]["scorecards"] == "score"
    assert c["default_filter"] == "needs"


@pytest.mark.parametrize(
    "last,target,expect",
    [
        ("0.9", "1.0", True),
        ("1.0", "1.0", False),
        ("1.1", "1.0", False),
        ("fail", "pass", True),
        ("starve", "1", True),
        ("miss", "1", True),
        ("not run", "1", False),
        ("", "1", False),
        ("leftover", "1", False),
        ("shipped", "1", False),
        ("5", "0", True),
        ("0", "0", False),
        # Informational empty target (mill-office.activities): non-zero Last is not a miss.
        ("42", "", False),
        ("7", None, False),
        ("3", "   ", False),
    ],
)
def test_kpi_miss(last, target, expect):
    assert kpi_miss(last, target) is expect


@pytest.mark.parametrize(
    "s,expect",
    [
        ("1.5", 1.5),
        ("pass", None),
        ("*", None),
        ("not run", None),
        ("-", None),
        ("abc", None),
        ("*12*", 12.0),
    ],
)
def test_numish(s, expect):
    assert numish(s) == expect


def test_score_window_and_in_window():
    assert score_window_ms("24h") == 24 * 3600 * 1000
    assert score_window_ms("7d") == 7 * 24 * 3600 * 1000
    fresh = (NOW - timedelta(hours=1)).isoformat().replace("+00:00", "")
    stale = (NOW - timedelta(hours=30)).isoformat().replace("+00:00", "")
    assert score_in_window(fresh, "24h", NOW_MS) is True
    assert score_in_window(stale, "24h", NOW_MS) is False
    assert score_in_window(stale, "7d", NOW_MS) is True
    assert score_in_window(None, "24h", NOW_MS) is False
    z = (NOW - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert score_in_window(z, "24h", NOW_MS) is True
    assert score_parse_at("") is None


def test_hot_vs_in_window_pass():
    fresh = (NOW - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
    d = {
        "kpis": [
            {
                "owner": "builder",
                "kpi": "wall_ship",
                "value": "1",
                "target": "1",
                "updated_at": fresh,
                "project_id": "agent-coord",
                "note": "JOB:wall-unit-suite",
            },
            {
                "owner": "validator",
                "kpi": "jobs_done",
                "value": "0",
                "target": "1",
                "updated_at": fresh,
                "project_id": "agent-coord",
            },
        ]
    }
    rows = score_desk_rows(d, span="24h", now_ms=NOW_MS)
    by = {r["desk"]: r for r in rows}
    assert by["builder"]["hot"] is False
    assert by["builder"]["sourceJob"] == "wall-unit-suite"
    assert by["validator"]["hot"] is True
    assert by["validator"]["miss"] >= 1
    assert "over Target" in " ".join(by["validator"]["reasons"])


def test_missing_last_and_stale_are_hot():
    fresh = (NOW - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    stale = (NOW - timedelta(hours=40)).strftime("%Y-%m-%d %H:%M:%S")
    d = {
        "kpis": [
            {
                "owner": "auditor",
                "kpi": "audit",
                "value": "",
                "target": "1",
                "updated_at": fresh,
            },
            {
                "owner": "setter-upper",
                "kpi": "ship",
                "value": "1",
                "target": "1",
                "updated_at": stale,
            },
        ]
    }
    rows = score_desk_rows(d, span="24h", now_ms=NOW_MS)
    by = {r["desk"]: r for r in rows}
    assert by["auditor"]["hot"] is True and by["auditor"]["missing"] >= 1
    assert "missing Last" in " ".join(by["auditor"]["reasons"])
    assert by["setter-upper"]["hot"] is True and by["setter-upper"]["stale"] >= 1
    assert "stale publish" in by["setter-upper"]["reasons"]


def test_needs_empty_kpi_fallback_desk_table_only():
    fresh = (NOW - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    d = {
        "kpis": [
            {
                "owner": "builder",
                "kpi": "wall_ship",
                "value": "1",
                "target": "1",
                "updated_at": fresh,
            }
        ]
    }
    rows = score_desk_rows(d, span="24h", now_ms=NOW_MS)
    assert rows and rows[0]["hot"] is False
    listed, fell = score_desk_table_list(rows, "needs")
    assert fell is True
    assert len(listed) == 1
    listed_all, fell2 = score_desk_table_list(rows, "all")
    assert fell2 is False
    assert len(listed_all) == 1
    # Hot list does NOT fall back (paintScoreHot idle when Needs clear)
    hot = score_hot_list(rows, "needs")
    assert hot == []
    assert score_hot_list(rows, "all") == rows


def test_pulse_counts_from_kpis_even_when_no_hot():
    fresh = (NOW - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    d = {
        "kpis": [
            {
                "owner": "builder",
                "kpi": "wall_ship",
                "value": "1",
                "target": "1",
                "updated_at": fresh,
            },
            {
                "owner": "auditor",
                "kpi": "audit",
                "value": "1",
                "target": "1",
                "updated_at": fresh,
            },
        ],
        "agents": [{"owner": "builder", "waiting_on": "validator"}],
        "spend_lines": [
            {"at": fresh, "tokens": 10, "source": "grok"},
            {"at": fresh, "tokens": 5, "source": "mill"},
        ],
    }
    rows = score_desk_rows(d, span="24h", now_ms=NOW_MS)
    pulse = score_pulse_counts(d, rows, span="24h", now_ms=NOW_MS)
    assert pulse["kpi_n"] == 2
    assert pulse["desk_n"] == 2
    assert pulse["waiting"] == 1
    # TOKEN_DETAIL/TOKENS_EST: mill excluded from LLM; exact grok=10 only
    assert pulse["tokens"] == 10
    assert pulse["exact"] is True
    assert pulse["cmds"] == 2
    assert pulse["trend"]["word"] == "better"
    assert pulse["stale_n"] == 0


def test_trend_worse_and_flat():
    assert score_trend([]) == {"word": "flat", "cls": ""}
    assert score_trend([{"hot": True}, {"hot": True}])["word"] == "worse"
    assert score_trend([{"hot": True}, {"hot": False}, {"hot": False}])["word"] == "flat"
    assert score_trend([{"hot": False}])["word"] == "better"


def test_prefer_desk_and_delta_and_source_job():
    rows = [
        {"desk": "a", "hot": False, "miss": 0, "missing": 0},
        {"desk": "b", "hot": True, "miss": 2, "missing": 0},
    ]
    assert score_prefer_desk(rows, "") == "b"
    assert score_prefer_desk(rows, "a") == "a"
    assert score_prefer_desk([], "") == ""
    assert score_delta(rows[1]) == "-2"
    assert score_delta({"miss": 0, "missing": 1}) == "?"
    assert score_delta({"miss": 0, "missing": 0}) == "|"
    assert score_source_job("JOB:wall-score-pure-extract; ok", "kpi") == "wall-score-pure-extract"
    assert score_source_job("", "wall_ship") == "wall_ship"


def test_spend_fallback_aggregate_without_at():
    # Empty spend_lines -> primary path uses spend (includes mill tokens).
    d_primary = {
        "spend_lines": [],
        "spend": [
            {"source": "grok", "tokens": 7, "cmds": 2},
            {"source": "mill", "tokens": 99, "cmds": 9},
        ],
    }
    sp0 = score_spend_pulse(d_primary, "24h", NOW_MS)
    # Aggregates without at: mill skipped for LLM; grok exact=7
    assert sp0["tokens"] == 7
    assert sp0["exact"] is True
    # Primary sums to 0 -> fallback aggregate excludes mill (board scoreSpendPulse).
    fresh = (NOW - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    d = {
        "spend_lines": [{"at": fresh, "tokens": 0, "source": "mill"}],
        "spend": [
            {"source": "grok", "tokens": 7, "cmds": 2},
            {"source": "mill", "tokens": 99, "cmds": 9},
        ],
    }
    sp = score_spend_pulse(d, "24h", NOW_MS)
    assert sp["tokens"] == 7
    assert sp["cmds"] == 3  # mill line counted + grok cmds from fallback


def test_waiting_live_agents_alias():
    assert score_waiting({"live_agents": [{"waiting_on": "x"}, {"waiting_on": ""}]}) == 1
    assert score_waiting({}) == 0


def test_owner_fallback_project_id_and_unknown():
    fresh = (NOW - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    d = {
        "kpis": [
            {"project_id": "agent-coord", "kpi": "x", "value": "1", "target": "1", "updated_at": fresh},
            {"kpi": "y", "value": "1", "target": "1", "updated_at": fresh},
        ]
    }
    rows = score_desk_rows(d, span="24h", now_ms=NOW_MS)
    desks = {r["desk"] for r in rows}
    assert "agent-coord" in desks
    assert "(unknown)" in desks


def test_spend_tokens_est_dim_vs_exact():
    """Exact tokens win; est-only when vendor tokens null; mill bytes separate."""
    fresh = (NOW - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    est_only = {
        "spend_lines": [
            {"at": fresh, "source": "mill", "bytes_out": 9000, "tokens": None},
            {"at": fresh, "source": "est_chars4", "tokens": None, "tokens_est": 50, "owner": "builder"},
        ]
    }
    sp = score_spend_pulse(est_only, "24h", NOW_MS)
    assert sp["tokens"] is None
    assert sp["exact"] is False
    assert sp["tokens_est"] == 50
    assert sp["millBytes"] == 9000

    exact = {
        "spend_lines": [
            {"at": fresh, "source": "mill", "bytes_out": 100},
            {"at": fresh, "source": "grok", "tokens": 12, "tokens_est": 99, "owner": "builder"},
            {"at": fresh, "source": "est_chars4", "tokens": None, "tokens_est": 40, "owner": "builder"},
        ]
    }
    sp2 = score_spend_pulse(exact, "24h", NOW_MS)
    assert sp2["exact"] is True
    assert sp2["tokens"] == 12  # exact wins; est row not mixed into solid total
    assert sp2["tokens_est"] == 40
    assert sp2["millBytes"] == 100


def test_score_js_activities_h_chip_label_and_empty_target():
    """mill-office.activities -> activities/h; empty target never numeric miss in score.js."""
    root = Path(__file__).resolve().parents[2]
    score_js = (root / "agent_coord/web/wall_ui/default/score/score.js").read_text(encoding="utf-8")
    assert 'SCORE_OFFICE_CHIPS = ["mill-office.activities"]' in score_js or (
        "SCORE_OFFICE_CHIPS" in score_js and "mill-office.activities" in score_js
    )
    assert '"mill-office.activities": "activities/h"' in score_js
    assert "function scoreKpiLabel" in score_js
    assert "function scoreFindKpi" in score_js
    # empty-target gate present (informational)
    assert "Informational KPIs" in score_js
    boot = (root / "agent_coord/web/wall_ui/default/boot.js").read_text(encoding="utf-8")
    # The strip catalogs every book KPI, then scoreKpiLabel maps activities/h.
    assert 'add("system")' in boot
    assert "add(hereKpiName(k))" in boot
    assert "scoreKpiLabel" in boot
    assert "activities/h" in score_js
    board = (root / "agent_coord/web/wall_ui/default/board.html").read_text(encoding="utf-8")
    assert re.search(r"score/score\.js\?v=wow\d+", board)
    lazy = (root / "agent_coord/web/wall_ui/lib/lazy.js").read_text(encoding="utf-8")
    assert "score/score.js?v=" in lazy


def test_score_desk_rows_activities_nonzero_empty_target_not_hot_miss():
    """ROLE_Admin mill-office.activities with Last>0 and target '' must not count as miss."""
    fresh = (NOW - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    d = {
        "kpis": [
            {
                "owner": "ROLE_Admin",
                "kpi": "mill-office.activities",
                "value": "12",
                "target": "",
                "updated_at": fresh,
                "project_id": "PROJ_Office",
            }
        ]
    }
    rows = score_desk_rows(d, span="24h", now_ms=NOW_MS)
    assert len(rows) == 1
    r = rows[0]
    assert r["miss"] == 0
    assert kpi_miss("12", "") is False
