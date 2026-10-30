"""#864: wall_ui/lib/check.py loaded on its own finds the Wall it checks."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import agent_coord

CHECK = Path(agent_coord.__file__).resolve().parent / "web" / "wall_ui" / "lib" / "check.py"


def _load_unpatched():
    spec = importlib.util.spec_from_file_location("wall_check_864", CHECK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_root_is_the_folder_that_holds_agent_coord() -> None:
    mod = _load_unpatched()
    assert mod.ROOT == Path(agent_coord.__file__).resolve().parent.parent
    assert (mod.ROOT / "agent_coord").is_dir()
    assert mod.WALL_UI == CHECK.parent.parent
    assert mod.BOARD.is_file()
