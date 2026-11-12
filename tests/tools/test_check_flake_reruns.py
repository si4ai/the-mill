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


def _runs(*rows: dict) -> list[dict]:
    return list(rows)


def _ci(run_id: int, conclusion: str, attempt: int = 1, sha: str = "a" * 40) -> dict:
    return {
        "conclusion": conclusion,
        "head_sha": sha,
        "id": run_id,
        "run_attempt": attempt,
        "status": "completed",
        "workflow_name": "CI",
    }


def test_pass_then_fail_is_not_a_flake(tmp_path: Path) -> None:
    # success id 999 then failure id 1000 must not be a flake
    data = {"runs": [_ci(999, "success"), _ci(1000, "failure")]}
    path = _write(tmp_path / "runs.json", data)
    assert cfr.main(["--fixtures", str(path), "--strict"]) == 0
    assert cfr.flake_pairs(data["runs"]) == []


def test_fail_then_pass_is_a_flake(tmp_path: Path) -> None:
    # failure 999 then success 1000 is a flake
    data = {"runs": [_ci(999, "failure"), _ci(1000, "success")]}
    path = _write(tmp_path / "runs.json", data)
    assert cfr.main(["--fixtures", str(path), "--strict"]) == 1
    flakes = cfr.flake_pairs(data["runs"])
    assert len(flakes) == 1
    assert flakes[0]["fail_id"] == "999"
    assert flakes[0]["success_id"] == "1000"


def test_earlier_run_success_then_later_run_failure_is_not_a_flake(tmp_path: Path) -> None:
    # run 500 attempt 2 success, then later run 600 attempt 1 failure
    data = {"runs": [_ci(500, "success", attempt=2), _ci(600, "failure", attempt=1)]}
    path = _write(tmp_path / "runs.json", data)
    assert cfr.main(["--fixtures", str(path), "--strict"]) == 0
    assert cfr.flake_pairs(data["runs"]) == []

