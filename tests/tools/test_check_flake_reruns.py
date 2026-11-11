"""Card 1148: check_flake_reruns reports fail-then-success workflow reruns.

The command is a fact report: it exits 0 even when it finds something (it is
not a CI gate). --strict fails on a doctored run list and passes on a clean
one. Pass-then-fail is not a flake. Tests use fixture JSON only.
"""
from __future__ import annotations

import json
from pathlib import Path

from tools import check_flake_reruns as cfr

DOCTORED = {
    "runs": [
        {
            "conclusion": "failure",
            "head_sha": "dddddddddddddddddddddddddddddddddddddddd",
            "id": 10,
            "run_attempt": 1,
            "status": "completed",
            "workflow_name": "CI",
        },
        {
            "conclusion": "success",
            "head_sha": "dddddddddddddddddddddddddddddddddddddddd",
            "id": 11,
            "run_attempt": 2,
            "status": "completed",
            "workflow_name": "CI",
        },
        {
            "conclusion": "success",
            "head_sha": "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
            "id": 12,
            "run_attempt": 1,
            "status": "completed",
            "workflow_name": "check_pack",
        },
    ]
}

CLEAN = {
    "runs": [
        {
            "conclusion": "success",
            "head_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "id": 1,
            "run_attempt": 1,
            "status": "completed",
            "workflow_name": "CI",
        },
        {
            "conclusion": "failure",
            "head_sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            "id": 2,
            "run_attempt": 1,
            "status": "completed",
            "workflow_name": "CI",
        },
        {
            "conclusion": "success",
            "head_sha": "cccccccccccccccccccccccccccccccccccccccc",
            "id": 3,
            "run_attempt": 1,
            "status": "completed",
            "workflow_name": "CI",
        },
        {
            "conclusion": "failure",
            "head_sha": "cccccccccccccccccccccccccccccccccccccccc",
            "id": 4,
            "run_attempt": 2,
            "status": "completed",
            "workflow_name": "CI",
        },
    ]
}


def _write(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_doctored_runs_fail_strict(tmp_path: Path) -> None:
    path = _write(tmp_path / "runs.json", DOCTORED)
    assert cfr.main(["--fixtures", str(path), "--strict"]) == 1


def test_clean_runs_pass_strict(tmp_path: Path) -> None:
    path = _write(tmp_path / "runs.json", CLEAN)
    assert cfr.main(["--fixtures", str(path), "--strict"]) == 0


def test_doctored_runs_are_a_report_not_a_gate(tmp_path: Path) -> None:
    path = _write(tmp_path / "runs.json", DOCTORED)
    assert cfr.main(["--fixtures", str(path)]) == 0
