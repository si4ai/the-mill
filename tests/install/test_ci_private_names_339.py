"""#339: CI runs the local-name scan from a private list it reads at runtime.

Regression row F50 (ci-private-names). CI has no login folders or office
aliases, so the local-name net used to be skipped there (CI=true). check_pack
now also reads newline-separated names from the MILL_PRIVATE_NAMES environment
variable (a GitHub secret in CI; never a file in the repo) and scans the
artifacts, the tracked tree and every commit message with them. On CI an
empty list fails closed, except on a fork PR (no secrets there), which says it
skipped; the push to main scans again. Reports never print a name.
"""
from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WF = ROOT / ".github" / "workflows"
# Invented hyphenated alias, assembled so no literal sits in this file.
ALIAS = "zq" + "-" + "harborline"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    if shutil.which("git") is None:
        pytest.skip("git not on PATH")
    r = tmp_path / "r"
    (r / "tools").mkdir(parents=True)
    for name in ("check_pack.py", "hygiene_words.txt"):
        shutil.copy(ROOT / "tools" / name, r / "tools" / name)
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "desk@users.noreply.github.com")
    _git(r, "config", "user.name", "desk")
    (r / "base.md").write_text("plain words about the mill\n", encoding="utf-8")
    (r / "agent_coord").mkdir()
    (r / "agent_coord" / "__init__.py").write_text("", encoding="utf-8")
    (r / "README.md").write_text("plain\n", encoding="utf-8")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "--no-verify", "-m", "#339 seed")
    dist = r / "dist"
    dist.mkdir()
    with zipfile.ZipFile(dist / "the_mill-0.0.0-py3-none-any.whl", "w") as zf:
        zf.writestr("agent_coord/__init__.py", "")
        zf.writestr("the_mill-0.0.0.dist-info/METADATA", "Name: the-mill\n")
    with tarfile.open(dist / "the_mill-0.0.0.tar.gz", "w:gz") as tf:
        data = b"plain\n"
        info = tarfile.TarInfo("the_mill-0.0.0/README.md")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    return r


def _check(repo: Path, **env: str) -> subprocess.CompletedProcess:
    base = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    for k in ("CI", "GITLAB_CI", "MILL_PRIVATE_NAMES", "MILL_PRIVATE_NAMES_REQUIRED"):
        base.pop(k, None)
    base["HOME"] = str(repo)  # no office aliases from this machine
    base.update(env)
    return subprocess.run(
        [sys.executable, "tools/check_pack.py", "dist"], cwd=repo, capture_output=True, text=True, env=base
    )


def test_ci_fails_on_a_private_name_in_a_commit_message(repo: Path) -> None:
    _git(repo, "commit", "-q", "--no-verify", "--allow-empty", "-m", f"#339 seen on {ALIAS}")
    res = _check(repo, CI="true", MILL_PRIVATE_NAMES=f"\n{ALIAS}\n")
    assert res.returncode == 1, res.stdout
    assert "local home-user name in git commit" in res.stdout
    assert ALIAS not in res.stdout + res.stderr


def test_ci_fails_on_a_private_name_in_the_tree(repo: Path) -> None:
    (repo / "notes.md").write_text(f"the office {ALIAS.upper()} is down\n", encoding="utf-8")
    _git(repo, "add", "notes.md")
    _git(repo, "commit", "-q", "--no-verify", "-m", "#339 notes")
    res = _check(repo, CI="true", MILL_PRIVATE_NAMES=ALIAS)
    assert res.returncode == 1, res.stdout
    assert "local home-user name in git tip: notes.md" in res.stdout
    assert ALIAS.casefold() not in (res.stdout + res.stderr).casefold()


def test_ci_with_the_list_and_a_clean_history_passes(repo: Path) -> None:
    res = _check(repo, CI="true", MILL_PRIVATE_NAMES=ALIAS)
    assert res.returncode == 0, res.stdout
    assert re.search(r"Private-name scan: 1 name\(s\)", res.stdout), res.stdout


def test_ci_without_the_list_fails_closed(repo: Path) -> None:
    for env in ({"CI": "true"}, {"CI": "true", "MILL_PRIVATE_NAMES": " \n \n"}, {"GITLAB_CI": "1"}):
        res = _check(repo, **env)
        assert res.returncode == 1, env
        assert "MILL_PRIVATE_NAMES" in res.stdout and "fails closed" in res.stdout, res.stdout


def test_fork_pr_without_secrets_says_it_skipped(repo: Path) -> None:
    res = _check(repo, CI="true", MILL_PRIVATE_NAMES_REQUIRED="0")
    assert res.returncode == 0, res.stdout
    assert "Private-name scan: skipped" in res.stdout


def test_off_ci_the_list_is_optional_and_adds_to_the_local_net(repo: Path) -> None:
    assert _check(repo).returncode == 0
    _git(repo, "commit", "-q", "--no-verify", "--allow-empty", "-m", f"#339 seen on {ALIAS}")
    assert _check(repo, MILL_PRIVATE_NAMES=ALIAS).returncode == 1


def _job(text: str, name: str) -> str:
    body = text.split(f"\n  {name}:\n", 1)[1]
    nxt = re.search(r"\n  [a-z_]+:\n", body)
    return body[: nxt.start()] if nxt else body


def test_workflows_hand_the_secret_to_every_check_pack_run() -> None:
    ci = (WF / "ci.yml").read_text(encoding="utf-8")
    rel = (WF / "release.yml").read_text(encoding="utf-8")
    secret = "${{ secrets.MILL_PRIVATE_NAMES }}"
    assert "workflow_call:\n    secrets:\n      MILL_PRIVATE_NAMES:\n        required: true" in ci
    for where, job in (("ci check_pack", _job(ci, "check_pack")), ("release verify", _job(rel, "verify"))):
        step = job.split("python tools/check_pack.py dist", 1)[0].rsplit("\n      - ", 1)[1]
        assert f"MILL_PRIVATE_NAMES: {secret}" in step, where
    assert "head.repo.fork" in _job(ci, "check_pack")
    assert f"MILL_PRIVATE_NAMES: {secret}" in _job(rel, "ci")
    # The list is passed in env only: never echoed, never written to a file.
    for text in (ci, rel):
        for ln in text.splitlines():
            if "MILL_PRIVATE_NAMES" in ln and "run:" in ln:
                pytest.fail(ln)
