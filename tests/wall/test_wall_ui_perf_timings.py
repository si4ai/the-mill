# -*- coding: utf-8 -*-
"""wall_perf appends timings=1 on /api/v1/* GET and parses body.timings into strip."""
from __future__ import annotations

from agent_coord.web.wall_logic.packs import wall_ui_root

ROOT = wall_ui_root()
BOARD = ROOT / "default" / "board.html"
EARLY = ROOT / "default" / "shell-early.js"
PERF = ROOT / "lib" / "perf.js"


def _perf() -> str:
    return PERF.read_text(encoding="utf-8")


def _early() -> str:
    return EARLY.read_text(encoding="utf-8")


def test_with_timings_appends_v1_only():
    src = _perf()
    assert "function withTimingsParam" in src
    assert "/api/v1/" in src
    assert "wallPerfWithTimings" in src
    assert 'set("timings", "1")' in src or "timings=1" in src


def test_parse_timings_and_strip_fields():
    src = _perf()
    assert "sql_ms" in src
    assert "resp_b" in src
    assert "wall-perf-strip" in src
    assert "showStrip" in src or "ensureStrip" in src
    assert "Server-Timing" not in src


def test_shell_early_loads_perf_when_gated():
    early = _early()
    assert "perf.js" in early
    html = BOARD.read_text(encoding="utf-8")
    assert "WALL_UI_PERF_GATE" in html or 'data-wall-early="perf"' in html

