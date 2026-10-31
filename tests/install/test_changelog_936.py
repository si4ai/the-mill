"""Card 936 / F228: CHANGELOG.md has exactly three sections, newest first."""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CHANGELOG = REPO / "CHANGELOG.md"

SECTIONS = (
    "## TBD (upcoming)",
    "## New changes",
    "## Last changes",
)
DISCLAIMER = (
    "Upcoming changes are our current plan, not a promise; "
    "they can change or move at release time."
)


def test_changelog_has_exactly_three_sections_newest_first():
    text = CHANGELOG.read_text(encoding="utf-8")
    assert text.startswith("# Changelog\n"), "missing H1"
    positions = [text.find(h) for h in SECTIONS]
    assert all(p >= 0 for p in positions), positions
    assert positions == sorted(positions), "sections must be TBD, then New, then Last"
    # no extra ## headings
    heads = [ln for ln in text.splitlines() if ln.startswith("## ")]
    assert heads == list(SECTIONS), heads
    # disclaimer under TBD
    tbd_block = text[positions[0] : positions[1]]
    assert DISCLAIMER in tbd_block
