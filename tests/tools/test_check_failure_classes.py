"""Card 1151: check_failure_classes reports coverage gaps in FAILURE-CLASSES.md.

The command is a fact report: a scan of the repo file exits 0 even when it
finds something (it is not a CI gate). --strict fails on a doctored table
and passes on a clean one.
"""
from __future__ import annotations

from pathlib import Path

from tools import check_failure_classes as cfc

ROOT = Path(__file__).resolve().parents[2]

CLEAN = """# fixture

| Class | Status | Owner | Covering check | Last result (sha, date) | Note |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Docs naming dead commands | covered | builder | `tools/check_doc_commands.py` in CI | abcdef1 2026-11-11 | |
| replicas, sharding, partitioning | N/A | - | one office is one MySQL | 2026-11-11 | expires with a second book |
"""

DOCTORED = """# fixture

| Class | Status | Owner | Covering check | Last result (sha, date) | Note |
| :--- | :--- | :--- | :--- | :--- | :--- |
| A class with no owner | covered |  | `tools/check_doc_commands.py` | abcdef1 2026-11-11 | |
| A missing check path | covered | builder | `tools/this_file_does_not_exist.py` | abcdef1 2026-11-11 | |
| Stale evidence | covered | builder | `tools/check_doc_commands.py` | abcdef1 2020-01-01 | |
| A healthy row | covered | builder | `tools/check_doc_commands.py` | abcdef1 2026-11-11 | |
"""


def test_doctored_table_fails_strict(tmp_path: Path) -> None:
    path = tmp_path / "FAILURE-CLASSES.md"
    path.write_text(DOCTORED, encoding="utf-8")
    assert (
        cfc.main(
            [
                "--file",
                str(path),
                "--repo",
                str(ROOT),
                "--as-of",
                "2026-11-11",
                "--strict",
            ]
        )
        == 1
    )


def test_clean_table_passes_strict(tmp_path: Path) -> None:
    path = tmp_path / "FAILURE-CLASSES.md"
    path.write_text(CLEAN, encoding="utf-8")
    assert (
        cfc.main(
            [
                "--file",
                str(path),
                "--repo",
                str(ROOT),
                "--as-of",
                "2026-11-11",
                "--strict",
            ]
        )
        == 0
    )


def test_repo_scan_is_a_report_not_a_gate() -> None:
    # Existing findings must not fail the default command (card 1151: checks over blocks).
    assert cfc.main(["--repo", str(ROOT), "--as-of", "2026-11-11"]) == 0
