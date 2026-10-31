"""Regression matrix: one file per row, generated index (card 924).

Row files: docs/security/regression/<ID>.md - one markdown table row each.
Index: docs/security/REGRESSION-MATRIX.md - rendered; do not hand-edit rows.

  python tools/regression_matrix.py write   # rewrite the index from row files
  python tools/regression_matrix.py check   # exit 1 if index is stale
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROWS_DIR = Path("docs/security/regression")
MATRIX = Path("docs/security/REGRESSION-MATRIX.md")

_ID = re.compile(r"^\| ((?:S-\d+|F\d+\w*|F-[a-z0-9]+(?:-[a-z0-9]+)*))(?= )")
_HEADER = (
    "# Security regression matrix\n"
    "\n"
    "Each row ties a hardened behavior to the behavior test(s) that lock it in.\n"
    "Add a row when a security fix lands; keep rows free of exploit detail beyond\n"
    "what the linked test needs.\n"
    "\n"
    "Rows live in `docs/security/regression/<ID>.md` (one file per row). This\n"
    "file is generated - run `python tools/regression_matrix.py write` after\n"
    "adding or editing a row file. Do not append rows here by hand (card 924).\n"
    "\n"
    "| ID  | Behavior guaranteed | Entry path | Regression test(s) |\n"
    "|-----|---------------------|-----------|--------------------|\n"
)
_FUNC_HEADER = (
    "\n"
    "## Function rows\n"
    "\n"
    "Rows for command behavior that cold desks and testers depend on. Same shape as\n"
    "above; IDs are `F-<slug>`.\n"
    "\n"
    "| ID  | Behavior guaranteed | Entry path | Regression test(s) |\n"
    "|-----|---------------------|-----------|--------------------|\n"
)


def _sort_key(stem: str) -> tuple:
    if stem.startswith("S-"):
        return (0, int(stem[2:]), "")
    m = re.match(r"^F(\d+)(.*)$", stem)
    if m:
        return (1, int(m.group(1)), m.group(2) or "")
    return (2, 0, stem)


def row_files(root: Path) -> list[Path]:
    d = root / ROWS_DIR
    if not d.is_dir():
        return []
    out = [p for p in d.glob("*.md") if _ID.match(f"| {p.stem} ")]
    return sorted(out, key=lambda p: _sort_key(p.stem))


def load_row_line(path: Path) -> str:
    """Return the single table-row line from a row file (first | ID | line)."""
    for line in path.read_text(encoding="utf-8").splitlines():
        if _ID.match(line):
            return line.rstrip() + "\n"
    raise ValueError(f"{path}: no table row line starting with | ID")


def render(root: Path | None = None) -> str:
    root = root or ROOT
    s_rows: list[str] = []
    f_rows: list[str] = []
    for path in row_files(root):
        line = load_row_line(path)
        if path.stem.startswith("S-"):
            s_rows.append(line)
        else:
            f_rows.append(line)
    return _HEADER + "".join(s_rows) + _FUNC_HEADER + "".join(f_rows)


def matrix_text(root: Path | None = None) -> str:
    """Text consumers should parse: prefer row files via render(); fall back to index."""
    root = root or ROOT
    if (root / ROWS_DIR).is_dir() and any((root / ROWS_DIR).glob("*.md")):
        return render(root)
    return (root / MATRIX).read_text(encoding="utf-8")


def write(root: Path | None = None) -> Path:
    root = root or ROOT
    path = root / MATRIX
    path.write_text(render(root), encoding="utf-8")
    return path


def check(root: Path | None = None) -> int:
    root = root or ROOT
    got = (root / MATRIX).read_text(encoding="utf-8")
    want = render(root)
    if got != want:
        sys.stderr.write(
            "REGRESSION-MATRIX.md is stale; run: python tools/regression_matrix.py write\n"
        )
        return 1
    return 0


def migrate_from_index(root: Path | None = None) -> int:
    """Split the current index into row files (idempotent overwrite)."""
    root = root or ROOT
    text = (root / MATRIX).read_text(encoding="utf-8")
    dest = root / ROWS_DIR
    dest.mkdir(parents=True, exist_ok=True)
    n = 0
    for line in text.splitlines():
        m = _ID.match(line)
        if not m:
            continue
        rid = m.group(1)
        (dest / f"{rid}.md").write_text(line.rstrip() + "\n", encoding="utf-8")
        n += 1
    return n


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("cmd", choices=("write", "check", "migrate", "render"))
    args = p.parse_args(argv)
    if args.cmd == "migrate":
        n = migrate_from_index()
        write()
        print(f"migrated {n} rows; wrote {MATRIX}")
        return 0
    if args.cmd == "write":
        write()
        print(f"wrote {MATRIX}")
        return 0
    if args.cmd == "render":
        sys.stdout.write(render())
        return 0
    return check()


if __name__ == "__main__":
    raise SystemExit(main())
