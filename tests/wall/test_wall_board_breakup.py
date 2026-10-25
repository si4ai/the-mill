# -*- coding: utf-8 -*-
"""board.html Path A breakup: shell markers, no huge inline CSS/JS."""
from __future__ import annotations

import re
from pathlib import Path

from agent_coord.web.wall_logic.packs import default_board_path, wall_ui_root

ROOT = Path(__file__).resolve().parents[2]


def test_board_shell_links_and_markers():
    board = default_board_path().read_text(encoding="utf-8")
    assert re.search(r"""href=["']/?board\.css(?:\?[^"']*)?["']""", board)
    assert re.search(r"""src=["']/?boot\.js(?:\?[^"']*)?["']""", board)
    assert "lib/keys.js" in board
    assert "lib/theme.css" in board
    for name in ("popup.js", "data.js", "tabs.js", "table.js", "graph.js", "theme.js", "keys.js"):
        assert f"lib/{name}" in board
    assert "WALL_UI_LIB_KEYS" in board or "wall-keys-help" in board
    assert "WALL_UI_DEFAULT_BOARD_CSS" in board
    assert "WALL_UI_DEFAULT_BOOT" in board
    assert "shell-early.js" in board
    assert 'id="wall-keys-help"' in board


def test_no_large_inline_style_or_script():
    board = default_board_path().read_text(encoding="utf-8")
    styles = re.findall(r"<style\b[^>]*>(.*?)</style>", board, flags=re.I | re.S)
    # critical welcome + .dismiss close chrome (Host lock); was 800 pre-welcome
    assert sum(len(s) for s in styles) < 1200
    inline = []
    for m in re.finditer(r"<script\b([^>]*)>(.*?)</script>", board, flags=re.I | re.S):
        if re.search(r"\bsrc\s*=", m.group(1), flags=re.I):
            continue
        if m.group(2).strip():
            inline.append(m.group(2))
    assert sum(len(s) for s in inline) < 800
    # shell should be far smaller than pre-breakup ~300k
    assert len(board.encode("utf-8")) < 80_000


def test_extracted_files_exist_with_markers():
    d = wall_ui_root() / "default"
    css = (d / "board.css").read_text(encoding="utf-8")
    boot = (d / "boot.js").read_text(encoding="utf-8")
    assert "WALL_UI_DEFAULT_BOARD_CSS" in css
    assert "WALL_UI_DEFAULT_BOOT" in boot
    assert "wallKeysBind" in boot or "WALL_UI_LIB_KEYS" in boot
    keys = (wall_ui_root() / "lib" / "keys.js").read_text(encoding="utf-8")
    assert "WALL_UI_LIB_KEYS" in keys
    assert "wall-keys:" in keys


