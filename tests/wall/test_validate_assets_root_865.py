"""#865: validate_assets hands check.py the folder that holds agent_coord/ as ROOT."""
from __future__ import annotations

from pathlib import Path

import agent_coord
from agent_coord.web.wall_ui import validate_assets

HOLDER = Path(agent_coord.__file__).resolve().parent.parent


def test_load_check_root_is_the_folder_that_holds_agent_coord() -> None:
    mod = validate_assets._load_check()
    assert mod.ROOT == HOLDER
    assert (mod.ROOT / "agent_coord" / "web" / "wall_ui") == mod.WALL_UI
    assert mod.BOARD.is_file()
