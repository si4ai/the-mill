"""DESKS rail: working desks lead and idle/gone desks sit last, even when a score misses."""
from __future__ import annotations

import re
from pathlib import Path

BOOT = Path(__file__).resolve().parents[2] / "agent_coord/web/wall_ui/default/boot.js"


def _rank_map() -> dict[str, int]:
    src = BOOT.read_text(encoding="utf-8")
    m = re.search(r"const ordered = live\.slice\(\)\.sort", src)
    assert m, "here-rail sort not found"
    head = src[max(0, m.start() - 600):m.start()]
    maps = re.findall(r"\{\s*(working:[^}]*)\}", head)
    assert len(maps) == 1, f"expected one fixed rank map before the sort, found {len(maps)}"
    return {k: int(v) for k, v in re.findall(r"(\w+):\s*(\d+)", maps[0])}


def test_working_ranks_before_idle_and_gone() -> None:
    rank = _rank_map()
    assert rank["working"] < rank["waiting"] < rank["idle"]
    assert rank["working"] < rank["here"] < rank["gone"]
    assert rank["idle"] < rank["gone"]


def test_no_score_miss_flip_of_the_order() -> None:
    src = BOOT.read_text(encoding="utf-8")
    assert "idle: 0" not in src
