"""Card 924: each regression row is its own file; REGRESSION-MATRIX.md is generated.

Parallel Builder PRs must not all append the same hand-edited matrix. Rows live
under docs/security/regression/<ID>.md; the index is rendered and checked.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROWS = ROOT / "docs" / "security" / "regression"
MATRIX = ROOT / "docs" / "security" / "REGRESSION-MATRIX.md"

_ID = re.compile(r"^\| ((?:S-\d+|F\d+\w*))\b")


def _ids_in_matrix(text: str) -> list[str]:
    out: list[str] = []
    for line in text.splitlines():
        m = _ID.match(line)
        if m:
            out.append(m.group(1))
    return out


def test_regression_rows_dir_exists_with_one_file_per_matrix_id():
    """Every ID in the matrix has docs/security/regression/<ID>.md and no extras."""
    assert ROWS.is_dir(), f"missing row dir {ROWS} (card 924)"
    ids = _ids_in_matrix(MATRIX.read_text(encoding="utf-8"))
    assert ids, "matrix has no rows"
    stems = sorted(
        p.stem for p in ROWS.glob("*.md") if _ID.match(f"| {p.stem} ")
    )
    assert stems == sorted(ids), (stems, sorted(ids))


def test_generated_index_matches_row_files():
    """REGRESSION-MATRIX.md equals tools.regression_matrix.render() (card 924)."""
    sys.path.insert(0, str(ROOT))
    from tools.regression_matrix import render

    got = MATRIX.read_text(encoding="utf-8")
    want = render(ROOT)
    assert got == want, "run: python tools/regression_matrix.py write"
