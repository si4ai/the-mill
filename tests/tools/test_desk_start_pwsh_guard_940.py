"""Card 940: F221's optional pwsh dry-run must not trip the card-663 guard.

When pwsh is absent, the dry-run execution test skips at collection. The
card-663 checker flags every skipped item in a matrix-cited file, so that
test must live outside any cited path (or the guard fails on every ubuntu
runner without pwsh).
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "docs" / "security" / "REGRESSION-MATRIX.md"
CITED_PS51 = "tests/tools/test_desk_start_ps51_221.py"


def _f221_cell() -> str:
    for line in MATRIX.read_text(encoding="utf-8").splitlines():
        if line.startswith("| F221 ("):
            return line
    raise AssertionError("F221 row missing")


def test_f221_pwsh_dry_run_lives_outside_cited_file() -> None:
    """The skippable pwsh dry-run is not in the matrix-cited ps51 module."""
    cited = CITED_PS51
    src = (ROOT / cited).read_text(encoding="utf-8")
    assert "test_dry_run_execution_emits_json_and_exit_zero" not in src, (
        "move the pwsh dry-run out of the cited file so card-663 stays green"
    )
    cell = _f221_cell()
    assert cited in cell
    assert "test_desk_start_ps51_pwsh_221" not in cell
    pwsh_path = ROOT / "tests/tools/test_desk_start_ps51_pwsh_221.py"
    assert pwsh_path.is_file(), pwsh_path
    body = pwsh_path.read_text(encoding="utf-8")
    assert "test_dry_run_execution_emits_json_and_exit_zero" in body
    assert 'skipif(shutil.which("pwsh") is None' in body or "skipif(shutil.which('pwsh') is None" in body


def test_f221_row_still_cites_static_ps51_cases() -> None:
    cell = _f221_cell()
    assert "test_desk_start_ps51_221" in cell
    assert "all cases" in cell or "test_desk_start_ps51_221.py" in cell
    text = MATRIX.read_text(encoding="utf-8")
    assert "| F230 (" in text
    assert "pwsh-f221-guard" in text or "desk-start-pwsh-guard" in text
