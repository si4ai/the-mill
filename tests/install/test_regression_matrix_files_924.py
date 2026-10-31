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

_ID = re.compile(r"^\| ((?:S-\d+|F\d+\w*|F-[a-z0-9]+(?:-[a-z0-9]+)*))(?= )")


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


def test_every_row_file_is_rendered():
    """A row file (any .md but README.md) is never silently ignored: each renders
    as exactly one index row with its file name as ID (F-<slug> included)."""
    sys.path.insert(0, str(ROOT))
    from tools.regression_matrix import render

    ids = _ids_in_matrix(render(ROOT))
    stems = sorted(p.stem for p in ROWS.glob("*.md") if p.name != "README.md")
    assert sorted(ids) == stems, (set(stems) ^ set(ids))
    assert len(ids) == len(set(ids)), "duplicate row IDs"


def test_function_slug_rows_kept():
    """The F-<slug> rows that 0.8.0 cites by name (commands.md, connect.md,
    test_wake_trailing_669.py) stay in the generated index."""
    text = MATRIX.read_text(encoding="utf-8")
    ids = set(_ids_in_matrix(text))
    for rid in (
        "F-claim-takeover", "F-hold-bare-list", "F-hold-peek-unknown-hint",
        "F-note-detail", "F-replay-quiet", "F-sync-hint-fold",
        "F-wake-trailing", "F-watch-hold-name",
    ):
        assert rid in ids, rid
        assert (ROWS / f"{rid}.md").is_file(), rid
