# -*- coding: utf-8 -*-
"""Wall UI: strip-tab loading chrome and finished shell."""
from __future__ import annotations

import re

from agent_coord.web.wall_logic.packs import wall_ui_root

from ._wall_src import boot_source

ROOT = wall_ui_root()
BOARD = ROOT / "default" / "board.html"
BOOT = ROOT / "default" / "boot.js"
SHELL = ROOT / "default" / "shell.css"


def _boot() -> str:
    return BOOT.read_text(encoding="utf-8")


def test_shell_loading_css():
    css = SHELL.read_text(encoding="utf-8")
    assert "WALL_UI_LOADING" in css
    assert ".wall-loading" in css
    assert "@keyframes wall-spin" in css
    assert "wall-loading-spin" in css


def test_loading_helpers_present():
    src = _boot()
    for name in (
        "wallLoadingHtml",
        "wallStripLoadHtml",
        "wallShowLoading",
        "wallMarkShellLoading",
        "wallMarkTabLoading",
        "wallSyncStripTabLoading",
        "wallHasRealContent",
        "wallIsLoadingEl",
    ):
        assert f"function {name}" in src, name
    assert "data-wall-loading" in src
    assert "data-wall-strip-loading" in src
    assert "\\u231B" in src or "\u231B" in src


def test_rail_and_session_seeded_loading_chrome():
    html = BOARD.read_text(encoding="utf-8")
    assert 'id="rail-desks"' in html
    assert "data-wall-loading" in html
    assert "Loading here" in html or "Loading here\u2026" in html or "Loading session" in html
    assert 'id="mail"' in html


def test_domain_tab_panels_seeded_loading_chrome():
    """SESSION/FLOOR/TODO/SCORE/MAIL content boxes show hourglass on first paint."""
    html = BOARD.read_text(encoding="utf-8")
    assert html.count("data-wall-loading") >= 13
    assert "Loading..." in html or "Loading\u2026" in html
    assert "Loading scores" in html or "Loading scores\u2026" in html
    assert "Loading rooms" in html or "Loading rooms\u2026" in html
    assert "Loading party" in html or "Loading party\u2026" in html
    for body_id in ("parked", "wanted", "claimed", "jobs-done"):
        assert f'id="{body_id}"' in html
        m = re.search(rf'<div class="body" id="{body_id}">(.*?)</div>', html, re.S)
        assert m and "data-wall-loading" in m.group(1), body_id
    m = re.search(r'<div class="floor-map" id="floor-map"[^>]*>(.*?)</div>', html, re.S)
    assert m and "data-wall-loading" in m.group(1)
    m = re.search(
        r'<div class="score-desk-table" id="score-desk-table"[^>]*>(.*?)</div>',
        html,
        re.S,
    )
    assert m and "data-wall-loading" in m.group(1)


def test_strip_tabs_seeded_loading_chrome():
    """HERE, TODO, MAIL, SCORE are the first strip. COLLAB waits after them."""
    html = BOARD.read_text(encoding="utf-8")
    assert html.count("data-wall-strip-loading") >= 5
    assert html.count("kpi-loading") >= 5
    assert html.count("kpi-load") >= 5
    strip = html.split('id="strip"', 1)[1].split("</div>", 1)[0]
    order = ("strip-here", "strip-todo", "strip-mail", "strip-score", "strip-floor")
    pos = [strip.find(f'id="{sid}"') for sid in order]
    assert all(p >= 0 for p in pos)
    assert pos == sorted(pos)
    for sid in order:
        m = re.search(rf'<span[^>]*id="{sid}"[^>]*>', strip)
        assert m, sid
        tag = m.group(0)
        assert "kpi-loading" in tag, sid
        assert 'data-wall-strip-loading="1"' in tag, sid
        if sid == "strip-floor":
            assert "strip-later" in tag
        else:
            assert "strip-later" not in tag
    assert re.search(r'id="strip-floor"[^>]*>COLLAB', strip)


def test_shell_strip_tab_loading_css():
    css = SHELL.read_text(encoding="utf-8")
    assert ".kpi.kpi-loading .kpi-load" in css
    assert "kpi-load" in css
    assert "[data-wall-strip-loading" in css
    assert len(css.encode("utf-8")) < 16_000


def test_strip_paint_clears_loading_when_ready():
    src = _boot()
    assert "_stripReady" in src
    assert "wallStripLoadHtml" in src
    assert "kpi-loading" in src
    assert "data-wall-strip-loading" in src
    body = src.split("function strip(d)", 1)[1].split("function isMillNeedId", 1)[0]
    assert "_stripReady.session" in body
    assert "sessLoad" in body
    assert "mailLoad" in body
    assert "scoreLoad = !_officeScoreSeen" in body
    fill = src.split("function wallFillStripCounts()", 1)[1].split("function strip(d)", 1)[0]
    assert 'need.push("todos")' in fill
    assert 'need.push("mail")' in fill
    assert 'need.push("scores")' not in fill
    assert "hereScoreRows" in body
    bits = body.split("el.innerHTML", 1)[1].split("_wallStripNavDelegated", 1)[0]
    order = ("strip-here", "strip-todo", "strip-mail", "strip-score", "strip-floor")
    pos = [bits.find(f'id="{sid}"') for sid in order]
    assert all(p >= 0 for p in pos)
    assert pos == sorted(pos)
    assert bits.count("strip-later") == 1
    assert ">COLLAB" in bits
    repaint = src.split("function officeScoreRepaint()", 1)[1].split("function officeScoreLoad()", 1)[0]
    assert "_officeScoreSeen = true" in repaint
    assert "strip(" in repaint


def test_mail_structure_only_and_todos_early():
    src = boot_source()
    assert "structureOnly" in src
    assert "function wallPaintTodosEarly" in src
    assert "function wallPaintFloorPartEarly" in src
    assert "function wallFetchFloorParts" in src
    assert "Loading mailbox" in src or "Loading mailbox\\u2026" in src
    paint = (ROOT / "default" / "mail" / "mail-paint.js").read_text(encoding="utf-8").split("function paintMailRooms", 1)[1]
    assert "structureOnly" in paint
    assert "wallShowLoading" in paint or "wallLoadingHtml" in paint


def test_tick_progressive_onrow_mail_and_todos():
    src = _boot()
    body = src.split("async function _tickBody()", 1)[1]
    assert "wallPaintMailRoomsEarly(wallMergeV1Isolates(earlyRows))" in body
    assert "wallPaintTodosEarly(wallMergeV1Isolates(earlyRows))" in body
    assert "wallFetchFloorV1" in body
    assert "do NOT await /api/activity" in body
    assert "wallMarkTabLoading" in body


def test_load_rail_book_parallel_with_spinners():
    src = _boot()
    load = src.split("async function loadRailBook()", 1)[1].split(
        "const railBook = document.getElementById", 1
    )[0]
    assert "Promise.all" in load
    assert 'part("desks")' in load
    # 0.7.0: one Roster list replaces Projects and Roles.
    assert 'part("rosters")' in load
    assert 'part("projects")' not in load and 'part("roles")' not in load
    assert "wallShowLoading" in load
    assert "await desksP" in load


def test_show_tab_marks_loading():
    src = _boot()
    show = src.split("function showTab(name)", 1)[1].split("function mdLite", 1)[0]
    # Checking overlay + tick/reuse; no provisional wallMarkTabLoading in showTab
    assert "wallShowPaneOverlay" in show
    assert ("tick(true)" in show) or ("wallReuseInflightForReturn" in show)


def test_poll_uses_versioned_parts():
    src = _boot()
    body = src.split("async function _tickBody()", 1)[1]
    assert "wallV1Routes" in body
    assert "paintApiDown" in body
    assert "/api/floor" not in body
    assert "/api/v1/" in src


def test_human_readonly_and_perf_opt_in_untouched():
    src = _boot()
    assert "Marker: WALL_HUMAN_READONLY" in src
    html = BOARD.read_text(encoding="utf-8")
    assert "WALL_UI_PERF_GATE" in html or "wall_perf" in html


def test_shell_critical_pane_chrome():
    css = SHELL.read_text(encoding="utf-8")
    assert "WALL_UI_SHELL_CRITICAL" in css
    for needle in (
        ".pane.on",
        ".pane-body",
        ".pane-head",
        "main {",
        "#subnav.page-views",
        ".mail-browser",
        ".jobs-kanban",
        ".kpi.strip-nav.on",
        "#rail-desks",
    ):
        assert needle in css, needle
    assert len(css.encode("utf-8")) < 16_000


def test_shell_boot_inline_hash_sync():
    html = BOARD.read_text(encoding="utf-8")
    # hash sync extracted to shell-early.js (inline script budget)
    early = (ROOT / "default" / "shell-early.js").read_text(encoding="utf-8")
    assert "WALL_UI_SHELL_BOOT" in early
    assert 'data-wall-early="all"' in html
    assert html.count("shell-early.js") == 1
    assert "strip-nav on" in html and "kpi-loading" in html


def test_shell_critical_finished_chrome_layout():
    css = SHELL.read_text(encoding="utf-8")
    assert "WALL_UI_SHELL_CRITICAL" in css
    for needle in (
        "#rail-book > div:first-child",
        "#pane-session.on",
        ".pane-body > #sec-here",
        ".floor-split",
        ".mail-browser",
        ".jobs-kanban",
        "#filter-panel",
        "#howto-card",
        ".help-box",
    ):
        assert needle in css, needle
    assert len(css.encode("utf-8")) < 16_000


def test_shell_hourglass_not_mojibake():
    """The painted shell shows the hourglass, not its UTF-8 bytes read as cp1252."""
    html = BOARD.read_text(encoding="utf-8")
    assert "\u00e2\u0152\u203a" not in html
    assert html.count('<span class="wall-loading-ico" aria-hidden="true">&#x231B;</span>') >= 7
    assert 'aria-label="roster glance"' in html
    assert "project glance" not in html
