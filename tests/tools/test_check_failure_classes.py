"""Card 1151: check_failure_classes reports coverage gaps in FAILURE-CLASSES.md.

The command is a fact report: a scan of the repo file exits 0 even when it
finds something (it is not a CI gate). --strict fails on a doctored table
and passes on a clean one. Each defect kind has its own fixture so a mutant
that drops only that kind fails.
"""
from __future__ import annotations

from pathlib import Path

from tools import check_failure_classes as cfc

ROOT = Path(__file__).resolve().parents[2]

HEADER = """# fixture

| Class | Status | Owner | Covering check | Last result (sha, date) | Note |
| :--- | :--- | :--- | :--- | :--- | :--- |
"""

HEALTHY = (
    "| A healthy row | covered | builder | `tools/check_doc_commands.py` "
    "| abcdef1 2026-11-11 | |\n"
)
# N/A with an old date must not become a stale finding (and hyphen / en dash
# are allowed as the owner on an N/A row).
NA_ASCII = (
    "| replicas, sharding, partitioning | N/A | - | one office is one MySQL "
    "| 2020-01-01 | expires with a second book |\n"
)
NA_ENDASH = (
    "| CQRS, event sourcing | N/A | \u2013 | one book | 2020-01-01 | same |\n"
)
NO_OWNER = (
    "| A class with no owner | covered |  | `tools/check_doc_commands.py` "
    "| abcdef1 2026-11-11 | |\n"
)
NO_OWNER_ENDASH = (
    "| A class with en-dash owner | covered | \u2013 | `tools/check_doc_commands.py` "
    "| abcdef1 2026-11-11 | |\n"
)
MISSING_PATH = (
    "| A missing check path | covered | builder | `tools/this_file_does_not_exist.py` "
    "| abcdef1 2026-11-11 | |\n"
)
STALE = (
    "| Stale evidence | covered | builder | `tools/check_doc_commands.py` "
    "| abcdef1 2020-01-01 | |\n"
)

CLEAN = HEADER + HEALTHY + NA_ASCII + NA_ENDASH
AS_OF = "2026-11-11"


def _run(path: Path, extra: list[str] | None = None) -> int:
    args = ["--file", str(path), "--repo", str(ROOT), "--as-of", AS_OF]
    if extra:
        args.extend(extra)
    return cfc.main(args)


def _kinds(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    rows = cfc.parse_table(text)
    from datetime import date

    report = cfc.check_rows(rows, ROOT, as_of=date.fromisoformat(AS_OF), stale_days=14)
    return {f["kind"] for f in report["findings"]}


def test_doctored_table_fails_strict(tmp_path: Path) -> None:
    path = tmp_path / "FAILURE-CLASSES.md"
    path.write_text(HEADER + NO_OWNER + MISSING_PATH + STALE + HEALTHY, encoding="utf-8")
    assert _run(path, ["--strict"]) == 1


def test_clean_table_passes_strict(tmp_path: Path) -> None:
    path = tmp_path / "FAILURE-CLASSES.md"
    path.write_text(CLEAN, encoding="utf-8")
    assert _run(path, ["--strict"]) == 0


def test_no_owner_alone_fails_strict(tmp_path: Path) -> None:
    path = tmp_path / "FAILURE-CLASSES.md"
    path.write_text(HEADER + NO_OWNER + HEALTHY, encoding="utf-8")
    assert _run(path, ["--strict"]) == 1
    assert _kinds(path) == {"no_owner"}


def test_en_dash_owner_counts_as_no_owner(tmp_path: Path) -> None:
    path = tmp_path / "FAILURE-CLASSES.md"
    path.write_text(HEADER + NO_OWNER_ENDASH + HEALTHY, encoding="utf-8")
    assert _run(path, ["--strict"]) == 1
    assert _kinds(path) == {"no_owner"}


def test_missing_path_alone_fails_strict(tmp_path: Path) -> None:
    path = tmp_path / "FAILURE-CLASSES.md"
    path.write_text(HEADER + MISSING_PATH + HEALTHY, encoding="utf-8")
    assert _run(path, ["--strict"]) == 1
    assert _kinds(path) == {"missing_path"}


def test_stale_evidence_alone_fails_strict(tmp_path: Path) -> None:
    path = tmp_path / "FAILURE-CLASSES.md"
    path.write_text(HEADER + STALE + HEALTHY, encoding="utf-8")
    assert _run(path, ["--strict"]) == 1
    assert _kinds(path) == {"stale_evidence"}


def test_na_rows_are_not_stale_checked(tmp_path: Path) -> None:
    path = tmp_path / "FAILURE-CLASSES.md"
    path.write_text(CLEAN, encoding="utf-8")
    # 2020-01-01 is far older than 14 days before 2026-11-11.
    assert _run(path, ["--strict"]) == 0
    assert _kinds(path) == set()


def test_repo_scan_is_a_report_not_a_gate() -> None:
    # Existing findings must not fail the default command (card 1151: checks over blocks).
    assert cfc.main(["--repo", str(ROOT), "--as-of", "2026-11-11"]) == 0
