# -*- coding: utf-8 -*-
"""#896 rule-no-activity-weight: the Wall never reads activity.n or activity.weight."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "agent_coord" / "web" / "wall_ui"
SCORE = ROOT / "default" / "score" / "score-paint.js"
BOOT = ROOT / "default" / "boot.js"
WALL_JS = sorted((ROOT / "default").rglob("*.js")) + sorted((ROOT / "lib").glob("*.js"))


def test_no_presence_spend_fallback_and_unavailable():
    score = SCORE.read_text(encoding="utf-8")
    assert "presenceSpendLines" not in score
    assert "Number(e.n || 0) * Number(e.weight" not in score
    assert "unavailable" in score
    assert re.search(r"function millSpend\(", score)


def test_wall_js_never_reads_event_weight_field():
    for path in WALL_JS:
        src = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT)
        for m in re.finditer(r"(?<![a-zA-Z])e\.weight\b|(?<![a-zA-Z])r\.weight\b|event\.weight\b", src):
            full = src[max(0, m.start() - 60) : m.start() + 40]
            raise AssertionError(f"{rel}: activity weight read: {full!r}")


def test_boot_comment_does_not_teach_n_weight_spend():
    boot = BOOT.read_text(encoding="utf-8")
    assert "presence.n*weight" not in boot
