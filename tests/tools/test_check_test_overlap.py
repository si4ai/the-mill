"""Card 1152: check_test_overlap reports duplicate tests and uncovered F-rows.

The command is a fact report: it exits 0 even when it finds something (it is
not a CI gate). --strict fails on a doctored tree and passes on a clean one.
Each defect kind has its own fixture so a mutant that drops only that kind
fails.
"""
from __future__ import annotations

from pathlib import Path

from tools import check_test_overlap as cto


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _clean(root: Path) -> None:
    _write(
        root,
        ".github/workflows/ci.yml",
        "name: ci\non: [push]\njobs:\n  test:\n    runs-on: ubuntu-latest\n"
        "    steps:\n      - name: Run tests\n        run: pytest -q\n",
    )
    _write(
        root,
        "docs/security/regression/F100.md",
        "| F100 (one-behaviour) | One behaviour guaranteed. | entry | `tests/test_f100.py::test_ok` |\n",
    )
    _write(
        root,
        "tests/test_f100.py",
        '"""F100 coverage."""\n\ndef test_ok():\n    """F100: one behaviour guaranteed."""\n    assert True\n',
    )
    _write(root, "tools/check_example.py", '#!/usr/bin/env python3\n"""Example pack check (no F-row)."""\nprint("ok")\n')
    _write(root, "verify/spin/run.sh", "#!/bin/bash\n# no overlapping F-row in this clean fixture\n")


def _report(root: Path) -> dict:
    return cto.build_report(root, use_pytest=False)


def test_doctored_tree_fails_strict(tmp_path: Path) -> None:
    _clean(tmp_path)
    _write(
        tmp_path,
        "docs/security/regression/F200.md",
        "| F200 (uncovered) | A behaviour with no test. | entry | |\n",
    )
    _write(
        tmp_path,
        "tests/test_f100_again.py",
        'def test_also():\n    """F100: same assertion again."""\n    assert True\n',
    )
    assert cto.main(["--root", str(tmp_path), "--strict"]) == 1


def test_clean_tree_passes_strict(tmp_path: Path) -> None:
    _clean(tmp_path)
    assert cto.main(["--root", str(tmp_path), "--strict"]) == 0


def test_uncovered_f_row_alone_fails_strict(tmp_path: Path) -> None:
    _clean(tmp_path)
    _write(
        tmp_path,
        "docs/security/regression/F200.md",
        "| F200 (uncovered) | A behaviour with no test. | entry | |\n",
    )
    assert cto.main(["--root", str(tmp_path), "--strict"]) == 1
    report = _report(tmp_path)
    assert report["counts"]["uncovered_f_rows"] == 1
    assert report["counts"]["duplicate_clusters"] == 0


def test_duplicate_f_row_alone_fails_strict(tmp_path: Path) -> None:
    _clean(tmp_path)
    _write(
        tmp_path,
        "tests/test_f100_again.py",
        'def test_also():\n    """F100: same assertion again."""\n    assert True\n',
    )
    assert cto.main(["--root", str(tmp_path), "--strict"]) == 1
    report = _report(tmp_path)
    assert report["counts"]["duplicate_clusters"] == 1
    assert report["counts"]["uncovered_f_rows"] == 0
    assert report["duplicates"][0]["kind"] == "f_row"


def test_duplicate_behaviour_alone_fails_strict(tmp_path: Path) -> None:
    """Two tests with the same name and no F-row form a behaviour cluster."""
    _clean(tmp_path)
    _write(
        tmp_path,
        "tests/test_same_a.py",
        "def test_same():\n    assert True\n",
    )
    _write(
        tmp_path,
        "tests/test_same_b.py",
        "def test_same():\n    assert True\n",
    )
    assert cto.main(["--root", str(tmp_path), "--strict"]) == 1
    report = _report(tmp_path)
    kinds = {c["kind"] for c in report["duplicates"]}
    assert "behaviour" in kinds
    assert report["counts"]["uncovered_f_rows"] == 0


def test_doctored_tree_is_a_report_not_a_gate(tmp_path: Path) -> None:
    _clean(tmp_path)
    _write(
        tmp_path,
        "docs/security/regression/F200.md",
        "| F200 (uncovered) | A behaviour with no test. | entry | |\n",
    )
    assert cto.main(["--root", str(tmp_path)]) == 0
