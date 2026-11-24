"""Card 1228: the rco report job stays a report, and its metrics stay readable.

rco.yml runs rco diff, affected, drift and the cross-PR notice on pull
requests and rco update on a push to main. It must never become a gate:
no merge_group trigger, not called by release.yml, not in the
test-selection map, nothing in pre-commit. rco is the exact PyPI release
in the hash lock. Each pull request uploads rco-report with
rco-metrics.json, and the job fails if that file is missing.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WF = ROOT / ".github" / "workflows"
RCO = WF / "rco.yml"
LOCK = ROOT / "tools" / "ci-lock"
PINS = ROOT / "pins"
PIN_FILES = ("core.json", "server.json", "client.json")
REPORT_JOBS = ("rco",)

sys.path.insert(0, str(ROOT))
from tools import rco_metrics  # noqa: E402  # imported after sys.path insert so the tree copy of tools is used


def _code(p: Path) -> str:
    return "\n".join(ln for ln in p.read_text(encoding="utf-8").splitlines()
                     if not ln.lstrip().startswith("#"))


def _on(text: str) -> str:
    return text.split("\non:\n", 1)[1].split("\n\n", 1)[0]


def _step(job: str, name: str) -> str:
    body = job.split(f"- name: {name}\n", 1)[1]
    nxt = re.search(r"\n      - ", body)
    return body[: nxt.start()] if nxt else body


def test_triggers_are_pull_request_and_push_to_main_only() -> None:
    on = _on(_code(RCO))
    assert re.search(r"^  pull_request:", on, re.M), on
    assert "  push:\n    branches: [main]" in on, on
    for ev in ("merge_group", "workflow_call", "pull_request_target", "schedule"):
        assert ev not in on, ev


def test_release_and_ci_never_run_the_report() -> None:
    for name in ("release.yml", "ci.yml", "validator.yml", "codeql.yml"):
        text = _code(WF / name)
        assert "rco.yml" not in text and "rco diff" not in text, name


def test_report_job_is_not_selected_or_in_precommit() -> None:
    from ci.test_select import KNOWN_JOBS, load_map

    jobs = {j for _paths, js in load_map(ROOT / "ci" / "test-select.toml") for j in js}
    for job in REPORT_JOBS:
        assert job not in jobs and job not in KNOWN_JOBS, job
    for hook in (ROOT / ".githooks").iterdir():
        assert "rco " not in hook.read_text(encoding="utf-8"), hook.name


def test_rco_is_the_exact_release_from_the_hash_lock() -> None:
    assert "repo-context-optimizer==0.1.6" in (LOCK / "rco.in").read_text(encoding="utf-8")
    lock = (LOCK / "rco.txt").read_text(encoding="utf-8")
    assert re.search(r"(?m)^repo-context-optimizer==0\.1\.6 \\\n\s+--hash=sha256:[0-9a-f]{64}", lock)
    code = _code(RCO)
    assert "python -m pip install --require-hashes -r tools/ci-lock/rco.txt" in code
    assert len(re.findall(r"pip install", code)) == 2, "only the pip bootstrap and the lock"


def test_permissions_are_read_only() -> None:
    code = _code(RCO)
    top = code.split("\njobs:\n", 1)[0]
    assert "permissions:\n  contents: read\n" in top
    job = code.split("\njobs:\n", 1)[1]
    assert "    permissions:\n      contents: read\n      pull-requests: read\n" in job
    assert "write" not in code and "secrets." not in code
    assert "persist-credentials: false" in code and "fetch-depth: 0" in code


def test_pull_request_report_is_advisory() -> None:
    step = _step(_code(RCO), "Contract report")
    assert "if: github.event_name == 'pull_request'" in step
    for cmd in ('rco diff "$base" "$PR_HEAD"', 'rco affected "$base" "$PR_HEAD"',
                'rco drift pins --at "$PR_HEAD"', "python -m rco.notice_report"):
        assert cmd in step, cmd
    assert '-ge 2 ]; then worst=$code' in step and 'exit "$worst"' in step
    assert "GITHUB_STEP_SUMMARY" in step and "GH_TOKEN: ${{ github.token }}" in step


def test_push_updates_the_store_and_passes_on_findings() -> None:
    step = _step(_code(RCO), "Update the store")
    assert "if: github.event_name == 'push'" in step
    assert 'rco update --name "$REF_NAME"' in step
    assert "0|1) exit 0 ;;" in step


def test_metrics_are_measured_checked_and_uploaded() -> None:
    code = _code(RCO)
    assert "python tools/rco_metrics.py measure" in _step(code, "Token metrics")
    assert "python tools/rco_metrics.py check rco-report/rco-metrics.json" in \
        _step(code, "Metrics file present")
    up = code.split("actions/upload-artifact@", 1)[1].split("\n      - ", 1)[0]
    assert "name: rco-report" in up and "path: rco-report/" in up
    assert "if-no-files-found: error" in up


def test_pins_cover_the_most_imported_public_files() -> None:
    names = sorted(p.name for p in PINS.glob("*.json"))
    assert names == sorted(PIN_FILES), names
    for name in PIN_FILES:
        doc = json.loads((PINS / name).read_text(encoding="utf-8"))
        assert doc.get("paths"), name


def test_measure_counts_changed_files_and_one_import_hop() -> None:
    blobs = {"a.py": b"import b\n", "b.py": b"import c\nX = 1\n", "c.py": b"Y = 2\n",
             "README.md": b"# hi\n"}
    graph = {"a.py": ("b.py",), "b.py": ("c.py",)}
    got = rco_metrics.measure(["a.py", "README.md", "gone.py"], graph, blobs, "pack!", len)
    assert got["changed_files"] == 2
    assert got["without_rco"] == {"files": 3, "bytes": 9 + 5 + 15, "tokens": 29}
    assert got["with_rco"] == {"files": 2, "bytes": 5, "tokens": 5}
    assert got["ratio_tokens"] == round(5 / 29, 4)


def test_check_fails_when_the_metrics_file_is_missing_or_short(tmp_path: Path) -> None:
    assert rco_metrics.main(["check", str(tmp_path / "rco-metrics.json")]) == 1
    p = tmp_path / "rco-metrics.json"
    p.write_text(json.dumps({"schema": 1}), encoding="utf-8")
    assert rco_metrics.main(["check", str(p)]) == 1
    side = {"files": 1, "bytes": 2, "tokens": 3}
    p.write_text(json.dumps({"schema": 1, "pr": 1, "base_sha": "a", "head_sha": "b",
                             "rco_version": "0.1.6", "tokenizer": "t", "changed_files": 1,
                             "without_rco": side, "with_rco": side, "ratio_tokens": 1.0}),
                 encoding="utf-8")
    assert rco_metrics.main(["check", str(p)]) == 0
