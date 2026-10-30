"""Shared Wall split-gutter pure helpers (Floor + Score).

SoR: `agent_coord.web.wall_logic.gutter` mirrors clamp/persist rules used by
`wall_ui/components/gutter.js` (ordered cut 4). Packs keep CSS class names;
behavior contracts live here + the JS component.

See wall-contract; wall_logic/gutter.py
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

BOARD_EQUIVALENT_MARKER = "WALL_UI_COMPONENTS_GUTTER"
COMPONENT_JS = "gutter.js"
COMPONENT_CSS = "gutter.css"


def clamp_split_pct(
    pct: float | int | str | None,
    *,
    min_pct: float = 20.0,
    max_pct: float = 80.0,
    default: float = 50.0,
) -> float:
    """Clamp a split percent (pure)."""
    try:
        n = float(pct)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        n = float(default)
    if n != n:  # NaN
        n = float(default)
    if n < min_pct:
        n = float(min_pct)
    if n > max_pct:
        n = float(max_pct)
    return n


def floor_split_contract() -> dict[str, Any]:
    """Floor map|timeline vs detail gutter contract (board call-equivalent)."""
    return {
        "id": "floor",
        "storage_key": "factory-floor-split",
        "default_pct": 58.0,
        "min_main_px": 192,
        "min_detail_px": 224,
        "min_pct": 20.0,
        "max_pct": 78.0,
        "css_var": "--floor-main-w",
        "apply_default_if_empty": True,
        "keyboard": True,
        "detail_gap_px": 8,
        "gutter_id": "floor-gutter",
        "split_id": "floor-split",
        "main_id": "floor-main",
        "detail_id": "floor-detail",
    }


def score_split_contract() -> dict[str, Any]:
    """Scorecards hot vs detail gutter contract (board call-equivalent)."""
    return {
        "id": "score",
        "storage_key": "factory-score-split",
        "default_pct": 42.0,
        "min_main_px": 160,
        "min_detail_px": 200,
        "min_pct": 22.0,
        "max_pct": 72.0,
        "css_var": "--score-hot-w",
        "apply_default_if_empty": False,
        "keyboard": False,
        "detail_gap_px": 0,
        "gutter_id": "score-gutter",
        "split_id": "score-split",
        "main_id": "score-hot",
        "detail_id": "score-detail",
    }


def gutter_component_paths() -> dict[str, Path]:
    root = Path(__file__).resolve().parent.parent / "wall_ui"
    return {
        "components_js": root / "components" / COMPONENT_JS,
        "components_css": root / "components" / COMPONENT_CSS,
        "default_js": root / "default" / COMPONENT_JS,
        "default_css": root / "default" / COMPONENT_CSS,
    }


def gutter_contract() -> dict[str, Any]:
    paths = gutter_component_paths()
    return {
        "marker": BOARD_EQUIVALENT_MARKER,
        "component_js": COMPONENT_JS,
        "component_css": COMPONENT_CSS,
        "paths_exist": {k: v.is_file() for k, v in paths.items()},
        "floor": floor_split_contract(),
        "score": score_split_contract(),
        "shared_handlers": ("applyPct", "onMove", "onUp"),
        "pure": True,
        "path": "A",
        "wired_board": True,
    }
