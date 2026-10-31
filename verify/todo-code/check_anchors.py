#!/usr/bin/env python3
"""Check that each who-may anchor still appears in the cited source file.

  python verify/todo-code/check_anchors.py
  python verify/todo-code/check_anchors.py --mutant T9-done

With --mutant ID, the check strips that anchor's marker from a temp copy of
the file and expects a failure (proves the property can fail on a broken copy).
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


def check_one(root: Path, a: dict) -> tuple[bool, str]:
    path = root / a["path"]
    if not path.is_file():
        return False, f"missing file {a['path']}"
    text = path.read_text(encoding="utf-8", errors="replace")
    if a["marker"] not in text:
        return False, f"marker not found in {a['path']}: {a['marker']!r}"
    return True, "ok"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=ROOT, help="repo root")
    ap.add_argument(
        "--mutant",
        metavar="ID",
        help="strip this anchor's marker from a temp tree and expect failure",
    )
    args = ap.parse_args(argv)
    anchors = load()
    by_id = {a["id"]: a for a in anchors}

    if args.mutant:
        if args.mutant not in by_id:
            print(f"check_anchors: unknown mutant id {args.mutant}", file=sys.stderr)
            return 2
        target = by_id[args.mutant]
        with tempfile.TemporaryDirectory(prefix="todo-code-mut-") as td:
            td_path = Path(td)
            # Copy only the one file we mutate, and point root so relative paths work.
            src = args.root / target["path"]
            dst = td_path / target["path"]
            dst.parent.mkdir(parents=True, exist_ok=True)
            text = src.read_text(encoding="utf-8")
            n = text.count(target["marker"])
            if n < 1:
                print(f"check_anchors: mutant {args.mutant}: marker already absent", file=sys.stderr)
                return 1
            dst.write_text(text.replace(target["marker"], "/* MUTANT REMOVED */"), encoding="utf-8")
            # Also copy every other anchored file so non-target anchors still pass.
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
        mark = "ok" if ok else "FAIL"
        print(f"{mark:4}  {a['id']:20}  {a['path']}  ({a['property']})")
        if not ok:
            print(f"      {msg}", file=sys.stderr)
            failed += 1
    print(f"check_anchors: {len(anchors) - failed}/{len(anchors)} anchors present")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
