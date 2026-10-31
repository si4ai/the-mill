# -*- coding: utf-8 -*-
"""#904 diary act label: its own class and grid column, so it never wraps under .n."""
from __future__ import annotations

import re
from pathlib import Path

from tests.wall._wall_src import wall_fn

CSS = Path(__file__).resolve().parents[2] / "agent_coord" / "web" / "wall_ui" / "default" / "board.css"


def test_diary_row_paints_act_in_its_own_span():
    src = wall_fn("paintSessionWire")
    assert '<span class="act"' in src
    assert '<span class="n">' not in src


def test_hist_row_has_a_column_for_act_and_one_for_state():
    css = CSS.read_text(encoding="utf-8")
    m = re.search(r"\.hist-row \{[^}]*grid-template-columns:\s*([^;]+);", css)
    assert m, "hist-row grid missing"
    # when, kind, who, project, act, state
    cols = re.findall(r"minmax\([^)]*\)|[^\s]+", m.group(1))
    assert len(cols) == 6, cols
    rule = re.search(r"\.hist-row \.who, \.hist-row \.prod, \.hist-row \.act \{([^}]*)\}", css)
    assert rule and "nowrap" in rule.group(1) and "ellipsis" in rule.group(1)
