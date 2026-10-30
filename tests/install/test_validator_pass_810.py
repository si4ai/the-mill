"""#810 (F110): the merge queue keeps only PRs Validator passed on their head sha.

The API is a fake; every value is invented.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPO = "example-org/the-mill"
BASE = "b" * 40
QHEAD = "c" * 40
SHA = {150: "1" * 40, 151: "2" * 40}
BOT = "si4ai-validator[bot]"


def _mod():
    spec = importlib.util.spec_from_file_location("check_validator_pass", ROOT / "tools" / "check_validator_pass.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _fake(states: dict[str, list[tuple[str, str]]], subjects: list[str]):
    seen: list[str] = []

    def fetch(path: str):
        seen.append(path)
        if path == f"/repos/{REPO}/compare/{BASE}...{QHEAD}":
            return {"commits": [{"commit": {"message": s + "\n\nbody (#999)"}} for s in subjects]}
        for n, sha in SHA.items():
            if path == f"/repos/{REPO}/pulls/{n}":
                return {"number": n, "head": {"sha": sha}}
            if path == f"/repos/{REPO}/commits/{sha}/statuses?per_page=100&page=1":
                # newest first, posted by the Validator app (#811)
                return [{"context": c, "state": st, "creator": {"login": BOT, "type": "Bot"}} for c, st in states.get(sha, [])]
        raise AssertionError(path)

    return fetch, seen


def _mg(pr: int = 151) -> dict:
    return {"merge_group": {"head_ref": f"refs/heads/gh-readonly-queue/main/pr-{pr}-{BASE}",
                            "base_sha": BASE, "head_sha": QHEAD}}


def _run(event_name, event, fetch):
    lines: list[str] = []
    rc = _mod().run(event_name, event, REPO, fetch, out=lines.append)
    return rc, lines


def test_queue_entry_passes_when_every_pr_head_has_validator_success() -> None:
    fetch, _ = _fake({SHA[150]: [("validator", "success")], SHA[151]: [("other", "failure"), ("validator", "success")]},
                     ["#1 first (#150)", "#2 second (#151)"])
    rc, lines = _run("merge_group", _mg(), fetch)
    assert rc == 0, lines
    assert [ln.split(":")[0] for ln in lines] == ["OK", "OK"], lines


def test_queue_entry_fails_when_one_pr_lacks_a_pass() -> None:
    fetch, _ = _fake({SHA[150]: [("validator", "success")], SHA[151]: [("validator", "pending")]},
                     ["#1 first (#150)", "#2 second (#151)"])
    rc, lines = _run("merge_group", _mg(), fetch)
    assert rc == 1
    assert any("PR #151" in ln and "pending" in ln and ln.startswith("FAIL") for ln in lines), lines


def test_latest_validator_status_wins() -> None:
    # the status list is newest first
    fetch, _ = _fake({SHA[151]: [("validator", "failure"), ("validator", "success")]}, ["#2 second (#151)"])
    rc, lines = _run("merge_group", _mg(), fetch)
    assert rc == 1, lines


def test_missing_status_and_no_pr_fail_closed() -> None:
    fetch, _ = _fake({}, ["#2 second (#151)"])
    assert _run("merge_group", _mg(), fetch)[0] == 1
    fetch, _ = _fake({}, ["no number here"])
    rc, lines = _run("merge_group", {"merge_group": {"head_ref": "refs/heads/elsewhere",
                                                    "base_sha": BASE, "head_sha": QHEAD}}, fetch)
    assert rc == 1 and "no PR found" in lines[0], lines


def test_body_numbers_do_not_count_only_subjects_and_queue_ref() -> None:
    fetch, seen = _fake({SHA[151]: [("validator", "success")]}, ["#2 second (#151)"])
    rc, _lines = _run("merge_group", _mg(), fetch)
    assert rc == 0
    assert f"/repos/{REPO}/pulls/999" not in seen


def test_pull_request_reports_state_and_passes() -> None:
    fetch, _ = _fake({SHA[150]: [("validator", "pending")]}, [])
    ev = {"pull_request": {"number": 150, "head": {"sha": SHA[150]}}}
    rc, lines = _run("pull_request", ev, fetch)
    assert rc == 0
    assert lines[0].startswith("WAITING:") and SHA[150] in lines[0] and "is pending" in lines[0], lines
    assert "report only; merge queue enforces" in lines[0], lines
