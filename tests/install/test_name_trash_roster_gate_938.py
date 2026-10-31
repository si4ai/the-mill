"""Card 938 / F231: sp_name_trash keeps the sole-member-or-Admin roster gate.

The 879 suite stayed green when that gate was dropped from the procedure.
These checks lock the SQL text so a mutant that removes the gate fails
without needing MySQL, and name the behavioral row that kills it in CI.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SQL_FILES = (
    ROOT / "agent_coord" / "server" / "sql" / "sp_beta_name.sql",
    ROOT / "docs" / "requirements" / "beta" / "beta_sp.sql",
)
MATRIX = ROOT / "docs" / "security" / "REGRESSION-MATRIX.md"


def _trash_body(text: str) -> str:
    m = re.search(
        r"CREATE PROCEDURE sp_name_trash\(.*?\nEND //",
        text,
        flags=re.S,
    )
    assert m, "sp_name_trash missing"
    return m.group(0)


def test_sp_name_trash_has_roster_sole_or_admin_gate() -> None:
    """Both shipped SQL copies keep the roster sole-member-or-Admin gate."""
    for path in SQL_FILES:
        body = _trash_body(path.read_text(encoding="utf-8"))
        assert "Card 938" in body, path
        assert "v_type = 'roster'" in body, path
        assert "b_is_admin(v_by)" in body, path
        assert "sole remaining member or Admin" in body, path
        assert "only Admin can trash a roster with no members" in body, path
        # Gate must sit before the UPDATE that stamps trashed.
        assert body.index("sole remaining member or Admin") < body.index(
            "UPDATE name SET trashed"
        ), path


def test_f231_row_and_879_behavioral_test_exist() -> None:
    matrix = MATRIX.read_text(encoding="utf-8")
    assert "| F231 (" in matrix
    assert "name-trash-roster-gate" in matrix or "sp_name_trash" in matrix
    suite = (
        ROOT / "tests" / "server" / "records" / "test_delete_unreferenced_879.py"
    ).read_text(encoding="utf-8")
    assert "test_delete_roster_refuses_non_sole_non_admin" in suite
