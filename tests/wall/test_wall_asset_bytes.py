# -*- coding: utf-8 -*-
"""Every Wall asset has a recorded byte baseline (card #871, wall-contract rule-asset-bytes #874).

tests/wall/asset_bytes.json holds the size of each asset the browser loads
(.js, .css, .html, .svg under agent_coord/web/wall_ui). An asset that grows
past its baseline fails, and so does an asset missing from the file, unless
the same PR raises the baseline and says why in the PR text. It is a
baseline, not a target: a PR that shrinks an asset may lower its line, and
should, so the next growth is measured from there.

Sizes count LF line ends, so a CRLF checkout of board.html measures the same.

Refresh the file: python tests/wall/test_wall_asset_bytes.py --update
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ROOT = REPO / "agent_coord" / "web" / "wall_ui"
BASELINE = Path(__file__).resolve().parent / "asset_bytes.json"
ASSET = {".js", ".css", ".html", ".svg"}


def measure() -> dict[str, int]:
    """Bytes per Wall asset, keyed by path under wall_ui, LF line ends."""
    out = {}
    for path in sorted(ROOT.rglob("*")):
        if path.is_file() and path.suffix in ASSET and "node_modules" not in path.parts:
            out[path.relative_to(ROOT).as_posix()] = len(path.read_bytes().replace(b"\r\n", b"\n"))
    return out


def baseline() -> dict[str, int]:
    return json.loads(BASELINE.read_text(encoding="utf-8"))["bytes"]


def over(now: dict[str, int], base: dict[str, int]) -> list[str]:
    """Assets bigger than their baseline, or with no baseline."""
    out = []
    for name, size in now.items():
        if name not in base:
            out.append(f"{name}: {size} B, no baseline")
        elif size > base[name]:
            out.append(f"{name}: {size} B > baseline {base[name]} B (+{size - base[name]})")
    return out


def test_no_wall_asset_grows_past_its_baseline():
    bad = over(measure(), baseline())
    assert not bad, (
        "Wall asset grew. Shrink it, or raise its line in tests/wall/asset_bytes.json "
        "in this PR (python tests/wall/test_wall_asset_bytes.py --update) and say why:\n"
        + "\n".join(bad)
    )


def test_baseline_names_only_live_assets():
    gone = sorted(set(baseline()) - set(measure()))
    assert not gone, "baseline names assets that no longer exist; refresh it: " + ", ".join(gone)


def test_over_flags_growth_and_new_assets():
    assert over({"a.js": 10}, {"a.js": 10}) == []
    assert over({"a.js": 9}, {"a.js": 10}) == []
    assert over({"a.js": 11}, {"a.js": 10}) == ["a.js: 11 B > baseline 10 B (+1)"]
    assert over({"b.css": 5}, {}) == ["b.css: 5 B, no baseline"]


def _update() -> None:
    now = measure()
    doc = {
        "note": "Wall asset bytes (LF). Card 871; wall-contract rule-asset-bytes (874). "
        "Raise a line only with a reason in the PR text.",
        "total": sum(now.values()),
        "bytes": now,
    }
    BASELINE.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"{len(now)} assets, {doc['total']} B -> {BASELINE.relative_to(REPO)}")


if __name__ == "__main__":
    if sys.argv[1:] == ["--update"]:
        _update()
    else:
        sys.exit("usage: python tests/wall/test_wall_asset_bytes.py --update")
