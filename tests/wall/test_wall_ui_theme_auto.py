# -*- coding: utf-8 -*-
"""Wall UI: theme Auto follows prefers-color-scheme via matchMedia."""
from __future__ import annotations

from agent_coord.web.wall_logic.packs import wall_ui_root

ROOT = wall_ui_root()
BOOT = ROOT / "default" / "boot.js"
EARLY = ROOT / "default" / "shell-early.js"
THEME_CSS = ROOT / "lib" / "theme.css"
BOARD_CSS = ROOT / "default" / "board.css"


def test_shell_early_resolves_auto_via_matchmedia():
    src = EARLY.read_text(encoding="utf-8")
    assert "prefers-color-scheme: dark" in src
    assert "data-theme-pref" in src
    assert 'setAttribute("data-theme", resolved)' in src


def test_wire_theme_pref_matchmedia_listener():
    src = BOOT.read_text(encoding="utf-8")
    assert "(function wireThemePref" in src
    wire = src.split("(function wireThemePref", 1)[1].split("})();", 1)[0]
    assert "matchMedia" in wire
    assert "prefers-color-scheme: dark" in wire
    assert "addEventListener" in wire and "change" in wire
    assert "data-theme-pref" in wire
    assert "systemTheme" in wire
    assert 'setAttribute("data-theme", resolved)' in wire
    assert 'colorScheme = "light dark"' in wire


def test_preserve_theme_chrome_resolves_auto():
    src = BOOT.read_text(encoding="utf-8")
    body = src.split("function wallPreserveThemeChrome", 1)[1].split("function ", 1)[0]
    assert "prefers-color-scheme: dark" in body
    assert "resolved" in body
    assert 'colorScheme = "light dark"' in body


def test_theme_css_palette_keys_data_theme_not_pref_alone():
    css = THEME_CSS.read_text(encoding="utf-8")
    assert 'html[data-theme-pref="auto"]' not in css
    assert 'html[data-theme="light"]' in css
    assert 'html[data-theme="dark"]' in css
    assert "@media (prefers-color-scheme: dark)" in css
    assert "@media (prefers-color-scheme: light)" in css


def test_board_css_theme_aligned():
    css = BOARD_CSS.read_text(encoding="utf-8")
    assert 'html[data-theme="light"]' in css
    assert 'html[data-theme="dark"]' in css
    assert 'html[data-theme-pref="auto"]' not in css
