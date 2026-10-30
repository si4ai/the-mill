"""wall-js-lib Path A: lib modules, theme.css, pre-www CSS/JS gate."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from agent_coord.web.wall_logic.js_lib import (
    js_lib_contract,
    lib_dir,
    lib_paths,
    sanitize_css_vars,
    theme_contract,
)
from agent_coord.web.wall_logic.packs import default_board_path, wall_ui_root

ROOT = Path(__file__).resolve().parents[2]


def test_lib_files_and_markers():
    c = js_lib_contract()
    assert c["path"] == "A"
    assert c["cut6_schema_migrated"] is False
    assert all(c["files_exist"].values()), c["files_exist"]
    assert all(c["markers_ok"].values()), c["markers_ok"]
    assert (lib_dir() / "theme.css").is_file()


def test_theme_vars_and_sanitize():
    t = theme_contract()
    assert t["file_exists"]
    assert t["schema_migrated"] is False
    assert all(t["vars_present"].values()), t["vars_present"]
    assert sanitize_css_vars({"accent": "x"}) == {}
    assert sanitize_css_vars({"--a": "1;{hack}"}) == {"--a": "1hack"}


def test_board_wires_lib_and_theme():
    board = default_board_path().read_text(encoding="utf-8")
    assert "lib/theme.css" in board or "href=\"lib/theme.css\"" in board
    for name in ("popup.js", "data.js", "tabs.js", "table.js", "graph.js", "theme.js", "keys.js"):
        assert f"lib/{name}" in board
    assert "WALL_UI_LIB" in board or "wallMountHelpBox" in board
    assert "wallPaintApiDown" in board or "WALL_UI_LIB_DATA" in board


def test_pre_www_css_js_gate_passes():
    # Product package-data path (OOTB pip) - preferred
    r = subprocess.run(
        [sys.executable, "-m", "agent_coord.web.wall_ui.validate_assets", "--json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stdout + "\n" + r.stderr
    import json
    report = json.loads(r.stdout)
    assert report["ok"] is True
    assert report.get("theme_css")
    assert any("theme.css" in f for f in report["files"])
    assert (ROOT / "agent_coord" / "web" / "wall_ui" / "lib" / "check.py").is_file()


def test_pack_inventory_mentions_lib():
    # soft: lib dir exists under wall_ui
    assert (wall_ui_root() / "lib").is_dir()
    assert lib_paths()["theme.css"].is_file()
