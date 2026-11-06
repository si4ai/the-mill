"""Prose-only pytest skips use the whole diff and fail closed."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "docs_only.py"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True,
        env={**os.environ, "MILL_GITHUB_TOKEN_SI4AI": os.environ.get("MILL_GITHUB_TOKEN_SI4AI", "")},
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.name", "builder")
    git(tmp_path, "config", "user.email", "builder@users.noreply.github.com")
    (tmp_path / "README.md").write_text("base\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "seed")
    return tmp_path


def commit(repo: Path, path: str) -> str:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("changed\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "change")
    return git(repo, "rev-parse", "HEAD")


def detect(repo: Path, tmp_path: Path, event: dict, name: str = "pull_request") -> str:
    payload = tmp_path / "event.json"
    payload.write_text(json.dumps(event))
    result = subprocess.run(
        [sys.executable, str(SCRIPT)], cwd=repo, capture_output=True, text=True,
        env={**os.environ, "GITHUB_EVENT_NAME": name, "GITHUB_EVENT_PATH": str(payload)},
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def pr(base: str, head: str) -> dict:
    return {"pull_request": {"base": {"sha": base}, "head": {"sha": head}}}


@pytest.mark.parametrize("path,skip", [
    ("README.md", True), ("CHANGELOG.md", True), ("LICENSE", True),
    ("docs/dev/guide.md", True), (".github/guide.md", True),
    ("docs/space and\ttab\nand newline.md", True),
    ("docs/protocol/route-template.py", False),
    ("docs/protocol/hint-handler/examples/stub_handler.py", False),
    ("docs/protocol/hint-handler/tools/hint_handler/main.py", False),
    ("docs/requirements/beta/beta_ddl.sql", False),
    ("docs/requirements/beta/beta_sp.sql", False),
    ("tests/fixture.md", False), ("tests/nested/fixture.md", False),
    ("docs/LICENSE", False), ("pyproject.toml", False), ("MANIFEST.in", False),
    (".github/workflows/ci.yml", False), ("tools/helper.py", False),
    ("agent_coord/main.py", False),
])
def test_paths(repo: Path, tmp_path: Path, path: str, skip: bool) -> None:
    base = git(repo, "rev-parse", "HEAD")
    head = commit(repo, path)
    assert detect(repo, tmp_path, pr(base, head)) == f"skip_pytest={str(skip).lower()}"


def test_whole_pr_not_just_last_commit(repo: Path, tmp_path: Path) -> None:
    base = git(repo, "rev-parse", "HEAD")
    commit(repo, "docs/code.py")
    head = commit(repo, "guide.md")
    assert detect(repo, tmp_path, pr(base, head)) == "skip_pytest=false"


@pytest.mark.parametrize("old,new,skip", [
    ("old.md", "new.md", True), ("old.py", "new.md", False),
    ("old.md", "new.py", False), ("tests/old.md", "new.md", False),
])
def test_rename_both_paths(repo: Path, tmp_path: Path, old: str, new: str, skip: bool) -> None:
    base = commit(repo, old)
    (repo / old).rename(repo / new)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "rename")
    head = git(repo, "rev-parse", "HEAD")
    assert detect(repo, tmp_path, pr(base, head)) == f"skip_pytest={str(skip).lower()}"


def test_merge_group_uses_queue_base(repo: Path, tmp_path: Path) -> None:
    commit(repo, "already-landed.py")
    base = git(repo, "rev-parse", "HEAD")
    head = commit(repo, "guide.md")
    event = {"merge_group": {"base_sha": base, "head_sha": head}}
    assert detect(repo, tmp_path, event, "merge_group") == "skip_pytest=true"


@pytest.mark.parametrize("event,name", [
    ({}, "pull_request"), ({}, "merge_group"), ({}, "push"),
    ({}, "workflow_call"), ({}, "workflow_dispatch"),
    (pr("0" * 40, "1" * 40), "pull_request"),
    (pr("--bad-option", "1" * 40), "pull_request"),
])
def test_fail_closed(repo: Path, tmp_path: Path, event: dict, name: str) -> None:
    assert detect(repo, tmp_path, event, name) == "skip_pytest=false"


def test_empty_diff_runs_pytest(repo: Path, tmp_path: Path) -> None:
    sha = git(repo, "rev-parse", "HEAD")
    assert detect(repo, tmp_path, pr(sha, sha)) == "skip_pytest=false"


def test_missing_event_file_runs_pytest(repo: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT)], cwd=repo, capture_output=True, text=True,
        env={**os.environ, "GITHUB_EVENT_NAME": "pull_request", "GITHUB_EVENT_PATH": "missing"},
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "skip_pytest=false"


def test_pr_uses_merge_base_not_unrelated_base_changes(repo: Path, tmp_path: Path) -> None:
    base_branch = git(repo, "branch", "--show-current")
    git(repo, "switch", "-qc", "prose")
    head = commit(repo, "guide.md")
    git(repo, "switch", "-q", base_branch)
    base = commit(repo, "unrelated.py")
    assert detect(repo, tmp_path, pr(base, head)) == "skip_pytest=true"


def test_deleted_code_prevents_skip(repo: Path, tmp_path: Path) -> None:
    base = commit(repo, "remove.py")
    (repo / "remove.py").unlink()
    head = commit(repo, "guide.md")
    assert detect(repo, tmp_path, pr(base, head)) == "skip_pytest=false"


def test_markdown_and_license_together_skip(repo: Path, tmp_path: Path) -> None:
    base = git(repo, "rev-parse", "HEAD")
    commit(repo, "LICENSE")
    head = commit(repo, "docs/protocol/guide.md")
    assert detect(repo, tmp_path, pr(base, head)) == "skip_pytest=true"


def test_no_repository_runs_pytest(tmp_path: Path) -> None:
    event = pr("0" * 40, "1" * 40)
    assert detect(tmp_path, tmp_path, event) == "skip_pytest=false"
