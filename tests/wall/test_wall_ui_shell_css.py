# -*- coding: utf-8 -*-
"""Wall instant shell: tiny shell.css + deferred board.css; keep slim parts= poll."""
from __future__ import annotations

import re
from pathlib import Path

from agent_coord.web.wall_logic.packs import wall_ui_root

ROOT = wall_ui_root()
BOARD_HTML = ROOT / "default" / "board.html"
SHELL_CSS = ROOT / "default" / "shell.css"
BOOT = ROOT / "default" / "boot.js"


def _html() -> str:
    return BOARD_HTML.read_text(encoding="utf-8")


def _shell() -> str:
    return SHELL_CSS.read_text(encoding="utf-8")


def test_shell_css_exists_and_marked():
    assert SHELL_CSS.is_file(), "default/shell.css missing"
    src = _shell()
    assert "WALL_UI_DEFAULT_SHELL_CSS" in src
    assert len(src.encode("utf-8")) < 16_000, "shell.css grew too fat for Wave 1"


def test_board_html_instant_shell_load_order():
    html = _html()
    theme_i = html.find('href="/lib/theme.css')
    if theme_i < 0:
        theme_i = html.find('href="lib/theme.css')
    shell_i = html.find('href="/shell.css')
    if shell_i < 0:
        shell_i = html.find('href="shell.css')
    board_i = html.find('href="/board.css')
    if board_i < 0:
        board_i = html.find('href="board.css')
    assert 0 <= theme_i < shell_i < board_i
    assert re.search(r'<link[^>]+href="/?shell\.css[^>]*>', html)
    assert re.search(
        r'<link[^>]+id="board-css"[^>]+href="/?board\.css[^>]*media="print"',
        html,
    )
    assert re.search(r'<script[^>]+src="/?lib/board-css\.js', html)
    assert "onload=" not in html
    ns = html.find("<noscript>")
    assert ns >= 0 and "board.css" in html[ns : ns + 200]
    assert re.search(r'<script\s+defer\s+src="/?boot\.js', html)


def test_slim_parts_poll_not_regressed():
    src = BOOT.read_text(encoding="utf-8")
    assert "function wallParts()" in src
    assert "stripNeed" not in src
    assert 'mailView === "rooms") ? "mail,trees" : "mail"' in src
    assert "return core;" in src
    assert "function wallV1Routes" in src
    assert 'parts === "agents"' in src


def test_shell_critical_first_paint_chrome():
    src = _shell()
    assert "WALL_UI_SHELL_CRITICAL" in src
    assert ".pane.on" in src
    assert ".pane-body" in src
    assert ".mail-browser" in src or ".jobs-kanban" in src


def test_shell_structure_layout_rules():
    src = _shell()
    assert "WALL_UI_SHELL_CRITICAL" in src
    for needle in (
        "#shell",
        "#rail",
        "grid-template-columns",
        "#rail-book > div:first-child",
        ".pane.on",
        "#pane-session.on",
        ".pane-body",
        ".mail-browser",
        ".jobs-kanban",
        ".floor-split",
        "#filter-panel",
        "#howto-card",
    ):
        assert needle in src, needle
    assert len(src.encode("utf-8")) < 16_000

