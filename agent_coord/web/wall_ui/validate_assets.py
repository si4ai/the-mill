"""OOTB pre-www Wall CSS/JS gate (product package-data under wall_ui).

Run before www sync:
  python -m agent_coord.web.wall_ui.validate_assets
  python -m agent_coord.web.wall_ui.validate_assets --json

SoR: docs/acceptance/ACCEPTANCE-WALL-JS-LIB.md (pre-www CSS/JS validator amend).
Prefer mill. Fail non-zero so bad assets never land in ~/.mill/www.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_check():
    check_path = Path(__file__).resolve().parent / "lib" / "check.py"
    if not check_path.is_file():
        raise FileNotFoundError(f"missing package gate: {check_path}")
    spec = importlib.util.spec_from_file_location("agent_coord_wall_ui_lib_check", check_path)
    if spec is None or spec.loader is None:
        raise ImportError("cannot load wall_ui/lib/check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # check.py sets ROOT itself: the folder that holds agent_coord/.
    # When editable/pip, wall_ui lives under agent_coord - point WALL_UI at package
    mod.WALL_UI = Path(__file__).resolve().parent
    mod.LIB = mod.WALL_UI / "lib"
    mod.DEFAULT = mod.WALL_UI / "default"
    mod.BOARD = mod.DEFAULT / "board.html"
    return mod


def run_gate(root=None):
    mod = _load_check()
    if root is not None:
        mod.ROOT = Path(root)
        mod.WALL_UI = mod.ROOT / "agent_coord" / "web" / "wall_ui"
        if not mod.WALL_UI.is_dir():
            mod.WALL_UI = Path(__file__).resolve().parent
        mod.LIB = mod.WALL_UI / "lib"
        mod.DEFAULT = mod.WALL_UI / "default"
        mod.BOARD = mod.DEFAULT / "board.html"
    return mod.run_gate(mod.ROOT if root is None else Path(root))


def main(argv: list[str] | None = None) -> int:
    mod = _load_check()
    return int(mod.main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
