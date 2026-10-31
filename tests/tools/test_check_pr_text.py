"""#723 (F94): PR and issue text get the commit-message hygiene rules."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import check_pr_text as pt  # noqa: E402

# Built at runtime so this file stays clean under check_pack.
HOME_PATH = "/ho" + "me/zorbin/notes.txt"
EMAIL = "zorbin" + "@" + "corp-mail.co"
ADDR = "10.1" + ".2.3"
SCRIPT = ROOT / "tools" / "check_pr_text.py"


def _run(tmp_path: Path, name: str, event: dict) -> subprocess.CompletedProcess:
    path = tmp_path / "event.json"
    path.write_text(json.dumps(event), encoding="utf-8")
    env = {"GITHUB_EVENT_NAME": name, "GITHUB_EVENT_PATH": str(path), "PATH": "/usr/bin:/bin"}
    return subprocess.run([sys.executable, str(SCRIPT), "event"], env=env, capture_output=True, text=True)


@pytest.mark.parametrize("bad,kind", [(HOME_PATH, "home path with a login name"),
                                      (EMAIL, "email outside placeholder domains"),
                                      (ADDR, "non-documentation address")])
def test_pr_body_hit_fails_and_names_field_line_kind(tmp_path: Path, bad: str, kind: str) -> None:
    res = _run(tmp_path, "pull_request", {"pull_request": {"number": 87, "title": "#1 Fix", "body": f"ok\nsee {bad}\n"}})
    assert res.returncode == 1
    assert f"PR #87 body:2: {kind}" in res.stderr
    assert "pr-text hygiene FAIL" in res.stderr
    assert bad not in res.stderr + res.stdout and "zorbin" not in res.stderr + res.stdout


def test_pr_title_hit_fails(tmp_path: Path) -> None:
    res = _run(tmp_path, "pull_request", {"pull_request": {"number": 9, "title": f"#1 move {HOME_PATH}", "body": None}})
    assert res.returncode == 1 and "PR #9 title:1: home path" in res.stderr


@pytest.mark.parametrize("name,key", [("issue_comment", "issue"), ("pull_request_review_comment", "pull_request")])
def test_comment_hit_fails(tmp_path: Path, name: str, key: str) -> None:
    res = _run(tmp_path, name, {key: {"number": 5}, "comment": {"id": 77, "body": f"log at {HOME_PATH}"}})
    assert res.returncode == 1 and "#5 " in res.stderr and " 77:1: home path" in res.stderr


def test_clean_text_and_placeholders_pass(tmp_path: Path) -> None:
    body = ("Docs use desk@example.com, 192.0.2.1 and /ho" "me/<user>/x.\n"
            "Signed noreply: 1+desk@users.noreply.github.com\n")
    res = _run(tmp_path, "pull_request", {"pull_request": {"number": 1, "title": "#1 Clean", "body": body}})
    assert res.returncode == 0, res.stderr
    assert "0 hits" in res.stdout


def test_shell_metacharacters_are_plain_text(tmp_path: Path) -> None:
    """The body is data: a command substitution in it is never run."""
    marker = tmp_path / "pwned"
    body = f"$(touch {marker}) `touch {marker}` ${{{{ github.token }}}}"
    res = _run(tmp_path, "pull_request", {"pull_request": {"number": 2, "title": "t", "body": body}})
    assert not marker.exists()
    assert res.returncode == 0, res.stderr
    assert "Traceback" not in res.stderr


def test_unknown_event_or_missing_file_fails_closed(tmp_path: Path) -> None:
    res = _run(tmp_path, "push", {})
    assert res.returncode == 1 and "pr-text ERROR" in res.stderr
    env = {"GITHUB_EVENT_NAME": "pull_request", "GITHUB_EVENT_PATH": str(tmp_path / "nope.json")}
    res = subprocess.run([sys.executable, str(SCRIPT), "event"], env=env, capture_output=True, text=True)
    assert res.returncode == 1 and "failing closed" in res.stderr


def test_sweep_reads_titles_bodies_and_both_comment_kinds(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = {
        "/issues?": [{"number": 3, "title": "t", "body": f"x {EMAIL}", "pull_request": {}},
                     {"number": 4, "title": "t", "body": None}],
        "/issues/comments?": [{"id": 11, "issue_url": "https://h/repos/o/r/issues/4", "body": HOME_PATH}],
        "/pulls/comments?": [{"id": 12, "pull_request_url": "https://h/repos/o/r/pulls/3", "body": "fine"}],
        "/reviews?": [],
    }

    def fake_all(url: str, token: str) -> list:
        return next(v for k, v in pages.items() if k in url)

    monkeypatch.setattr(pt, "_all", fake_all)
    fails = pt.scan(pt.sweep_texts("o/r", ""))
    assert fails == ["PR #3 body:1: email outside placeholder domains", "#4 comment 11:1: home path with a login name"]



def test_sweep_reads_every_pr_review_body(monkeypatch: pytest.MonkeyPatch) -> None:
    """F122 (#823): no workflow runs on a review event, so the sweep reads each
    PR's review bodies (issues are skipped; a review with no body is fine)."""
    seen: list[str] = []

    def fake_all(url: str, token: str) -> list:
        seen.append(url)
        if "/pulls/3/reviews?" in url:
            return [{"id": 21, "body": f"see {HOME_PATH}"}, {"id": 22, "body": None}]
        if "/issues?" in url:
            return [{"number": 3, "title": "t", "body": "", "pull_request": {}},
                    {"number": 4, "title": "t", "body": ""}]
        return []

    monkeypatch.setattr(pt, "_all", fake_all)
    fails = pt.scan(pt.sweep_texts("o/r", ""))
    assert fails == ["PR #3 review 21:1: home path with a login name"]
    assert not [u for u in seen if "/pulls/4/" in u]

def test_file_mode_scans_a_body_before_posting(tmp_path: Path) -> None:
    f = tmp_path / "body.md"
    f.write_text("fine\n", encoding="utf-8")
    assert pt.main(["file", str(f)]) == 0
    f.write_text(f"fine\n{EMAIL}\n", encoding="utf-8")
    assert pt.main(["file", str(f)]) == 1


def test_pr_body_credential_shape_fails(tmp_path: Path) -> None:
    """PR text refuses credential shapes (kills the no-pr_text-hook mutant)."""
    ghp = "ghp_" + "A" * 36
    res = _run(
        tmp_path,
        "pull_request",
        {"pull_request": {"number": 88, "title": "#1 Fix", "body": "seed " + ghp + "\n"}},
    )
    assert res.returncode == 1
    assert "credential shape" in res.stderr
    assert ghp not in res.stderr + res.stdout
