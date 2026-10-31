# -*- coding: utf-8 -*-
"""#899 rule-act-labels: one label table for the 0.8.0 command-name ENUM."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "agent_coord" / "web" / "wall_ui" / "lib" / "data.js"
TABLES = ROOT / "agent_coord" / "server" / "sql" / "tables.sql"

# Final 0.8.0 act list (Builder 2026-10-29). ship, done and back are their own acts, not pass.
ACTS = [
    "create", "send", "reply", "note", "park", "claim", "unclaim", "assign", "unpark",
    "ship", "done", "back", "hold", "drop", "focus", "clear", "finish", "score",
    "retire", "reclaim", "remove", "rename",
]


def _enum_acts():
    src = TABLES.read_text(encoding="utf-8")
    m = re.search(r"act\s+ENUM\(([^)]+)\)\s+NOT NULL DEFAULT 'create'", src)
    if not m:
        return None
    return re.findall(r"'([a-z_]+)'", m.group(1))


def test_label_table_covers_final_act_list():
    src = DATA.read_text(encoding="utf-8")
    for act in ACTS:
        assert re.search(rf"\b{act}\s*:", src), f"missing label for {act}"
    assert not re.search(r"\bpass\s*:", src)
    enum_acts = _enum_acts()
    if enum_acts is None:
        # release/0.8.0 tip may still be pre-lane-B; this PR is stacked on #224.
        pytest.skip("activity.act ENUM not in tables.sql yet (stacked on #224)")
    assert enum_acts == ACTS


def test_unknown_act_shows_raw():
    src = DATA.read_text(encoding="utf-8")
    assert "function wallActLabel" in src
    assert "return a;" in src
