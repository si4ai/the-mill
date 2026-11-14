# -*- coding: utf-8 -*-
"""Wall user palettes: soft default, choice persists, full token set per mode."""
from __future__ import annotations

import re

from agent_coord.web.wall_logic.packs import wall_ui_root

ROOT = wall_ui_root()
BOOT = ROOT / "default" / "boot.js"
EARLY = ROOT / "default" / "shell-early.js"
THEME = ROOT / "lib" / "theme.css"
BOARD = ROOT / "default" / "board.html"

PALS = ("soft", "extreme", "cooler", "warmer", "high-contrast")
MODES = ("light", "dark")
TOKENS = (
    "--bg", "--panel", "--shop", "--shop-2", "--edge", "--ink", "--dim",
    "--amber", "--green", "--red", "--cyan", "--mag", "--lamp",
    "--deep", "--well", "--shadow",
)
RD_TOKENS = (
    "--rd-k-hold", "--rd-k-doing",
    "--rd-end-finished", "--rd-end-failed", "--rd-end-stale", "--rd-end-force",
)


def _rule(css: str, selector: str) -> str:
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert m, selector
    return m.group(1)


def test_more_menu_has_palette_picker():
    html = BOARD.read_text(encoding="utf-8")
    assert 'id="palette-pref"' in html
    assert 'aria-label="Palette"' in html
    for pal in PALS:
        assert f'data-palette="{pal}"' in html
    assert 'data-palette="current"' not in html
    assert 'data-palette="standard"' not in html


def test_shell_early_sets_data_palette_from_storage():
    src = EARLY.read_text(encoding="utf-8")
    assert 'localStorage.getItem("wall-palette")' in src
    assert 'setAttribute("data-palette", pal)' in src
    assert 'pal = "soft"' in src
    for pal in PALS:
        assert pal in src
    # unknown values fall back to soft
    assert 'pal = "soft"' in src.split("wall-palette", 1)[1]


def test_boot_persists_palette_choice():
    src = BOOT.read_text(encoding="utf-8")
    assert "(function wirePalettePref" in src
    wire = src.split("(function wirePalettePref", 1)[1].split("})();", 1)[0]
    assert 'localStorage.setItem(KEY, pal)' in wire
    assert 'KEY = "wall-palette"' in wire
    assert 'setAttribute("data-palette", pal)' in wire
    assert 'if (!ALLOW[pal]) pal = "soft"' in wire
    body = src.split("function wallPreserveThemeChrome", 1)[1].split("factory-density", 1)[0]
    assert 'localStorage.getItem("wall-palette")' in body
    assert 'setAttribute("data-palette", pal)' in body


def test_every_palette_defines_full_token_set_for_light_and_dark():
    css = THEME.read_text(encoding="utf-8")
    missing = []
    for pal in PALS:
        for mode in MODES:
            sel = f'html[data-palette="{pal}"][data-theme="{mode}"]'
            body = _rule(css, sel)
            for tok in TOKENS:
                if tok + ":" not in body.replace(" ", ""):
                    # allow "tok:" with spaces: "--bg: "
                    if not re.search(re.escape(tok) + r"\s*:", body):
                        missing.append(f"{sel} {tok}")
            rd = _rule(css, sel + " #rd")
            for tok in RD_TOKENS:
                if not re.search(re.escape(tok) + r"\s*:", rd):
                    missing.append(f"{sel} #rd {tok}")
    assert not missing, "missing tokens:\n" + "\n".join(missing)


def test_soft_is_the_default_look_in_theme_css():
    css = THEME.read_text(encoding="utf-8")
    # Base dark tokens (no palette attr) match soft dark, not the old extreme near-black.
    root = css.split(":root", 1)[1].split("html, body", 1)[0]
    assert "--bg: #121821;" in root
    assert "--bg: #080a0d;" not in root
    soft = _rule(css, 'html[data-palette="soft"][data-theme="dark"]')
    assert "--bg: #121821" in soft
    ext = _rule(css, 'html[data-palette="extreme"][data-theme="dark"]')
    assert "--bg: #080a0d" in ext
