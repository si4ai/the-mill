# -*- coding: utf-8 -*-
"""#900 rule-timeline-count: minute buckets use items; never activity.n."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "agent_coord" / "web" / "wall_ui"
FLOOR = ROOT / "default" / "floor" / "floor-paint.js"
BOOT = ROOT / "default" / "boot.js"


def test_minute_bucket_reads_items_not_n():
    floor = FLOOR.read_text(encoding="utf-8")
    assert "e.items" in floor
    assert not re.search(r"e\.n\s*!=\s*null\s*\?\s*e\.n", floor)
    boot = BOOT.read_text(encoding="utf-8")
    assert "items: r.items" in boot
    assert "n: r.n" not in boot.split("function presenceRowsForUi", 1)[1].split("function evidenceHour", 1)[0]
