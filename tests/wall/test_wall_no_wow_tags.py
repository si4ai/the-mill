# -*- coding: utf-8 -*-
"""No private ship-counter tags in Wall code or Wall tests (card #870).

A comment that needs a reference cites a card (#NNN) or a wall-contract
rule, which anyone can read with mill todo. The old counter tags pointed at
nothing. Cache pins (?v=... in board.html, lib/lazy.js and the pin tables in
test_wall_surface.py) are a separate scheme owned by card #799 and are allowed
here until that card replaces them. File names are not scanned.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ROOTS = (REPO / "agent_coord" / "web" / "wall_ui", REPO / "tests" / "wall")
TEXT = {".js", ".css", ".html", ".py", ".json", ".md", ".svg"}
TAG = re.compile("w" + r"ow\d+")
PIN = re.compile(r"""(\?v=|["'])$""")


def tag_hits(text: str) -> list[int]:
    """1-based line numbers holding a counter tag that is not a cache pin."""
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        for m in TAG.finditer(line):
            if not PIN.search(line[: m.start()]):
                out.append(n)
                break
    return out


def test_no_counter_tags_in_wall():
    hits = []
    for root in ROOTS:
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.suffix in TEXT and "node_modules" not in path.parts:
                for n in tag_hits(path.read_text(encoding="utf-8")):
                    hits.append(f"{path.relative_to(REPO)}:{n}")
    assert not hits, "cite a card (#NNN) instead of a counter tag:\n" + "\n".join(hits)


def test_check_flags_a_tag_and_keeps_pins():
    tag = "w" + "ow123"
    assert tag_hits(f"/* {tag}: fix */\n") == [1]
    assert tag_hits(f'<script src="/boot.js?v={tag}"></script>\n') == []
    assert tag_hits(f'    "boot.js": "{tag}",\n') == []
