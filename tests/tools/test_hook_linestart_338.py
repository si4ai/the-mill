"""#338: sentence case at a commit-message line start, and the hook from any cwd.

Regression row F49 (hook-linestart). A capitalized word at the start of a
commit-message line (after an optional bullet, number or card number) is
prose when its lower-case form is an ordinary word in the tree or in
tools/hygiene_words.txt. A name-like token there still fails, and the
mid-line rule is unchanged. The commit-msg hook and check_pack agree. The
hook finds its repo from its own path, so it gives a verdict from any cwd,
and a git failure inside the scan fails closed with a message.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import precommit_hygiene as ph  # noqa: E402

# Invented name-like token, assembled so no literal sits in this file.
NAME = "Qu" + "illonde"


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=check)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    if shutil.which("git") is None:
        pytest.skip("git not on PATH")
    r = tmp_path / "r"
    (r / "tools").mkdir(parents=True)
    for name in ("check_pack.py", "precommit_hygiene.py", "hygiene_words.txt"):
        shutil.copy(ROOT / "tools" / name, r / "tools" / name)
    shutil.copytree(ROOT / ".githooks", r / ".githooks")
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "desk@users.noreply.github.com")
    _git(r, "config", "user.name", "desk")
    (r / "base.md").write_text(
        "the scope is main. a finding, the history, a live check and the behavior.\n",
        encoding="utf-8",
    )
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "#338 seed the repo")
    _git(r, "config", "core.hooksPath", ".githooks")
    ph._VOCAB = None
    return r


def _hook(repo: Path, msg: str, cwd: Path) -> subprocess.CompletedProcess:
    f = cwd / "msg.txt"
    f.write_text(msg, encoding="utf-8")
    return subprocess.run(
        [str(repo / ".githooks" / "commit-msg"), str(f)], cwd=cwd, capture_output=True, text=True
    )


def _commit(repo: Path, msg: str) -> subprocess.CompletedProcess:
    (repo / "f.txt").write_text(msg, encoding="utf-8")
    _git(repo, "add", "f.txt")
    return _git(repo, "commit", "-q", "--no-verify", "-m", msg, check=False)


def _pack_scan(repo: Path) -> list[str]:
    code = "import sys; sys.path.insert(0, 'tools'); import check_pack as cp; print(repr(cp.scan_git_messages()))"
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    out = subprocess.run([sys.executable, "-c", code], cwd=repo, capture_output=True, text=True, env=env, check=True)
    return eval(out.stdout)  # noqa: S307 - our own repr of a list of str


PASS = [
    "title\n\nScope is main.\n",
    "#338 Scope the hook\n\nFinding: the hook read the word as a name.\nLive check done.\n",
    "title\n\n1273 Scope the hook\nFinding first.\n",
    "title\n\n- Behavior stays the same\n* Scope is main\n1. Finding first\n2) History second\n",
]
FAIL = [
    f"title\n\n{NAME} is main.\n",
    f"title\n\n- {NAME} asked for it\n",
    f"title\n\n1. {NAME} asked for it\n",
    "title\n\nkeep the Scope of it\n",  # mid-line: the allow-list rule is unchanged
]


def test_name_token_is_not_ordinary(repo: Path) -> None:
    assert NAME.casefold() not in ph.tree_vocab()


@pytest.mark.parametrize("msg", PASS)
def test_sentence_start_ordinary_word_passes(repo: Path, msg: str) -> None:
    res = _hook(repo, msg, repo)
    assert res.returncode == 0, res.stderr


@pytest.mark.parametrize("msg", FAIL)
def test_name_like_or_mid_line_token_still_fails(repo: Path, msg: str) -> None:
    res = _hook(repo, msg, repo)
    assert res.returncode == 1
    assert "personal name token (#229 rule)" in res.stderr
    assert NAME not in res.stderr


def test_check_pack_commit_scan_agrees_with_the_hook(repo: Path) -> None:
    for msg in PASS:
        assert _commit(repo, msg).returncode == 0
    assert _pack_scan(repo) == []
    assert _hook(repo, FAIL[1], repo).returncode == 1
    _commit(repo, FAIL[1])
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    assert _pack_scan(repo) == [f"personal name token in git commit {head[:12]}"]


def test_hook_gives_a_verdict_from_a_non_git_cwd(repo: Path, tmp_path: Path) -> None:
    out = tmp_path / "outside"
    out.mkdir()
    ok = _hook(repo, PASS[0], out)
    assert ok.returncode == 0, ok.stderr
    bad = _hook(repo, FAIL[0], out)
    assert bad.returncode == 1
    assert "personal name token (#229 rule)" in bad.stderr


def test_tree_scan_runs_from_a_non_git_cwd(repo: Path, tmp_path: Path) -> None:
    out = tmp_path / "outside"
    out.mkdir()
    cmd = [sys.executable, str(repo / "tools" / "precommit_hygiene.py"), "tree"]
    inside = subprocess.run(cmd, cwd=repo, capture_output=True, text=True)
    outside = subprocess.run(cmd, cwd=out, capture_output=True, text=True)
    assert "Traceback" not in outside.stderr
    assert (outside.returncode, outside.stderr) == (inside.returncode, inside.stderr)


def test_git_failure_fails_closed_with_a_message(monkeypatch, capsys) -> None:
    def boom(*args: str) -> bytes:
        raise subprocess.CalledProcessError(128, ["git", *args])

    monkeypatch.setattr(ph, "_git", boom)
    for mode in ("staged", "tree"):
        assert ph.main([mode]) == 1
        err = capsys.readouterr().err
        assert "hygiene ERROR" in err and "failing closed" in err


def test_hook_without_its_tools_fails_closed(tmp_path: Path) -> None:
    hooks = tmp_path / "loose" / ".githooks"
    shutil.copytree(ROOT / ".githooks", hooks)
    msg = tmp_path / "m.txt"
    msg.write_text("title\n", encoding="utf-8")
    res = subprocess.run([str(hooks / "commit-msg"), str(msg)], cwd=tmp_path, capture_output=True, text=True)
    assert res.returncode != 0
    assert "commit-msg:" in res.stderr
