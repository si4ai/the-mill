"""DESKS rail: working desks lead and idle/gone desks sit last, even when a score misses."""
from __future__ import annotations

import re
from pathlib import Path

BOOT = Path(__file__).resolve().parents[2] / "agent_coord/web/wall_ui/default/boot.js"
# The DESKS tab rows own the desk-list order now (boot.js paints #here through desksModel).
ROWS = Path(__file__).resolve().parents[2] / "agent_coord/web/wall_ui/default/session/desks-rows.js"


def _rank_map() -> dict[str, int]:
    src = ROWS.read_text(encoding="utf-8")
    maps = re.findall(r"STATE_RANK = \{\s*(working:[^}]*)\}", src)
    assert len(maps) == 1, f"expected one fixed STATE_RANK map, found {len(maps)}"
    return {k: int(v) for k, v in re.findall(r"(\w+):\s*(\d+)", maps[0])}


def test_working_ranks_before_idle_and_gone() -> None:
    rank = _rank_map()
    assert rank["working"] < rank["waiting"] < rank["idle"]
    assert rank["working"] < rank["here"] < rank["gone"]
    assert rank["idle"] < rank["gone"]


def test_no_score_miss_flip_of_the_order() -> None:
    for path in (BOOT, ROWS):
        assert "idle: 0" not in path.read_text(encoding="utf-8")
