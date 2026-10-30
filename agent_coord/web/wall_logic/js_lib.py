"""Wall shared JS lib inventory + theme contract (Path A pure SoR).

Mirrors `wall_ui/lib/*` for unit tests. DB css_vars migrate stays Cut 6.
SoR: wall-contract; tests/wall
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

BOARD_EQUIVALENT_MARKER = "WALL_UI_LIB"
LIB_MODULES = ("popup", "data", "tabs", "table", "graph", "theme", "keys")
LIB_JS_FILES = (
    "popup.js",
    "data.js",
    "tabs.js",
    "table.js",
    "graph.js",
    "theme.js",
    "keys.js",
)
THEME_CSS = "theme.css"

THEME_VARS = (
    "--font-family",
    "--font-size",
    "--font-sm",
    "--h1-size",
    "--h2-size",
    "--h3-size",
    "--row-pad",
    "--pane-gap",
    "--ink",
    "--bg",
)


def wall_ui_root() -> Path:
    return Path(__file__).resolve().parent.parent / "wall_ui"


def lib_dir() -> Path:
    return wall_ui_root() / "lib"


def lib_paths() -> dict[str, Path]:
    d = lib_dir()
    out = {name: d / name for name in LIB_JS_FILES}
    out["theme.css"] = d / THEME_CSS
    return out


def sanitize_css_var_value(v: Any) -> str:
    return str(v if v is not None else "").replace(";", "").replace("{", "").replace("}", "").strip()


def sanitize_css_vars(vars_map: dict[str, Any] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    if not vars_map:
        return out
    for k, v in vars_map.items():
        key = str(k).strip()
        if not key.startswith("--"):
            continue
        val = sanitize_css_var_value(v)
        if val:
            out[key] = val
    return out


def theme_contract() -> dict[str, Any]:
    paths = lib_paths()
    theme = paths["theme.css"]
    text = theme.read_text(encoding="utf-8") if theme.is_file() else ""
    return {
        "marker": "WALL_UI_LIB_THEME",
        "stylesheet": "lib/theme.css",
        "path": "A",
        "schema_migrated": False,
        "sanitize": "--* only; strip ;{}",
        "required_vars": list(THEME_VARS),
        "vars_present": {v: v in text for v in THEME_VARS},
        "file_exists": theme.is_file(),
    }


def js_lib_contract() -> dict[str, Any]:
    paths = lib_paths()
    exists = {k: p.is_file() for k, p in paths.items()}
    markers = {}
    for name, marker in (
        ("popup.js", "WALL_UI_LIB_POPUP"),
        ("data.js", "WALL_UI_LIB_DATA"),
        ("tabs.js", "WALL_UI_LIB_TABS"),
        ("table.js", "WALL_UI_LIB_TABLE"),
        ("graph.js", "WALL_UI_LIB_GRAPH"),
        ("theme.js", "WALL_UI_LIB_THEME_JS"),
        ("keys.js", "WALL_UI_LIB_KEYS"),
        ("theme.css", "WALL_UI_LIB_THEME"),
    ):
        p = paths[name]
        markers[name] = marker in p.read_text(encoding="utf-8") if p.is_file() else False
    return {
        "marker": BOARD_EQUIVALENT_MARKER,
        "path": "A",
        "lib_dir": str(lib_dir()),
        "modules": list(LIB_MODULES),
        "files_exist": exists,
        "markers_ok": markers,
        "theme": theme_contract(),
        "validator_script": "python -m agent_coord.web.wall_ui.validate_assets",
        "validator_package": "agent_coord/wall_ui/lib/check.py",
        "cut6_schema_migrated": False,
    }
