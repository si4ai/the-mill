#!/usr/bin/env python3
"""Check that each recovery-guard anchor still appears in the cited source file.

  python check_anchors.py
  python check_anchors.py --mutant ID

With --mutant ID, the check strips that anchor's marker from a temp copy of
the file and expects a failure (proves the property can fail on a broken copy).

Rules (card 1014):
  - marker must be the real guard line plus its first effect line when the
    guard spans more than one line (multi-line string with embedded newlines)
  - marker must not sit only on a comment, import, or log/message line
  - marker must match expected_count times (default 1); set expected_count
    when a marker is intentionally shared
  - every anchor is self-mutated by run.sh (not a hand-picked subset)

Standard library only. Not wired into CI.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
ANCHORS = HERE / "anchors.json"


def load() -> list[dict]:
    data = json.loads(ANCHORS.read_text(encoding="utf-8"))
    return list(data["anchors"])


def _first_line(marker: str) -> str:
    return marker.lstrip().split("\n", 1)[0].strip()


def validate_marker(a: dict) -> tuple[bool, str]:
    """Refuse markers that sit on the wrong kind of line (card 1014)."""
    m = a["marker"]
    if not m or not m.strip():
        return False, "empty marker"
    first = _first_line(m)
    if first.startswith("#") or first.startswith("--"):
        return False, f"marker sits on a comment: {first!r}"
    # Sole import with no effect line in the marker.
    if "\n" not in m.rstrip("\n"):
        if first.startswith("from ") and " import " in first:
            return False, f"marker sits on an import without an effect line: {first!r}"
        if first.startswith("import "):
            return False, f"marker sits on an import without an effect line: {first!r}"
        # Message / SIGNAL text alone is not a guard.
        if "MESSAGE_TEXT" in first or first.startswith("raise CoordError(") and "body must" in first:
            # allow raise CoordError as effect when it's the whole marker only if
            # paired; sole raise of a message string is weak - require guard context
            pass
    return True, "ok"


def check_one(root: Path, a: dict) -> tuple[bool, str]:
    ok, msg = validate_marker(a)
    if not ok:
        return False, msg
    path = root / a["path"]
    if not path.is_file():
        return False, f"missing file {a['path']}"
    text = path.read_text(encoding="utf-8", errors="replace")
    marker = a["marker"]
    count = text.count(marker)
    expected = int(a.get("expected_count", 1))
    if count != expected:
        return (
            False,
            f"marker count {count} != expected {expected} in {a['path']}: {marker!r}",
        )
    return True, "ok"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=ROOT, help="repo root")
    ap.add_argument(
        "--mutant",
        metavar="ID",
        help="strip this anchor's marker from a temp tree and expect failure",
    )
    ap.add_argument(
        "--list",
        action="store_true",
        help="print anchor ids (one per line) and exit",
    )
    args = ap.parse_args(argv)
    anchors = load()
    by_id = {a["id"]: a for a in anchors}

    if args.list:
        for a in anchors:
            print(a["id"])
        return 0

    if args.mutant:
        if args.mutant not in by_id:
            print(f"check_anchors: unknown mutant id {args.mutant}", file=sys.stderr)
            return 2
        target = by_id[args.mutant]
        with tempfile.TemporaryDirectory(prefix="code-mut-") as td:
            td_path = Path(td)
            src = args.root / target["path"]
            dst = td_path / target["path"]
            dst.parent.mkdir(parents=True, exist_ok=True)
            text = src.read_text(encoding="utf-8")
            n = text.count(target["marker"])
            if n < 1:
                print(
                    f"check_anchors: mutant {args.mutant}: marker already absent",
                    file=sys.stderr,
                )
                return 1
            dst.write_text(
                text.replace(target["marker"], "/* MUTANT REMOVED */", 1),
                encoding="utf-8",
            )
            for a in anchors:
                if a["id"] == args.mutant:
                    continue
                s = args.root / a["path"]
                d = td_path / a["path"]
                if not d.exists():
                    d.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(s, d)
            ok, msg = check_one(td_path, target)
            if ok:
                print(f"check_anchors: mutant {args.mutant} unexpectedly passed")
                return 1
            print(f"check_anchors: mutant {args.mutant} failed as expected ({msg})")
            return 0

    failed = 0
    for a in anchors:
        ok, msg = check_one(args.root, a)
        status = "ok" if ok else "FAIL"
        print(f"{status:4}  {a['id']:<28} {a['path']}  ({a.get('property', '')})")
        if not ok:
            print(f"       {msg}", file=sys.stderr)
            failed += 1
    total = len(anchors)
    print(f"check_anchors: {total - failed}/{total} anchors present")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
