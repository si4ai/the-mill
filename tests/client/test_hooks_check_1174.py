"""Card 1174: mill connect reports a the-mill checkout with commit hooks off."""
from __future__ import annotations

import subprocess
from pathlib import Path

from agent_coord.client import ws as ws_cli
from agent_coord.client.hooks_check import HOOKS_OFF_LINE, hooks_off_line


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _checkout(tmp_path: Path) -> Path:
    root = tmp_path / "mill"
    (root / ".githooks").mkdir(parents=True)
    (root / ".githooks" / "pre-commit").write_text("#!/bin/sh\n", encoding="ascii")
    (root / "tools").mkdir()
    (root / "tools" / "precommit_hygiene.py").write_text("", encoding="ascii")
    (root / "sub").mkdir()
    _git(root, "init", "-q")
    return root


def test_hooks_off_is_reported_from_any_subdir(tmp_path) -> None:
    root = _checkout(tmp_path)
    assert hooks_off_line(root) == HOOKS_OFF_LINE
    assert hooks_off_line(root / "sub") == HOOKS_OFF_LINE


def test_hooks_on_relative_or_absolute_is_quiet(tmp_path) -> None:
    root = _checkout(tmp_path)
    _git(root, "config", "core.hooksPath", ".githooks")
    assert hooks_off_line(root / "sub") == ""
    _git(root, "config", "core.hooksPath", str(root / ".githooks"))
    assert hooks_off_line(root) == ""


def test_hooks_path_elsewhere_is_reported(tmp_path) -> None:
    root = _checkout(tmp_path)
    _git(root, "config", "core.hooksPath", ".git/hooks")
    assert hooks_off_line(root) == HOOKS_OFF_LINE


def test_other_repo_or_no_repo_is_quiet(tmp_path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    assert hooks_off_line(other) == ""
    _git(other, "init", "-q")
    assert hooks_off_line(other) == ""


def test_ready_prints_hooks_line_on_stderr_only(tmp_path, monkeypatch, capsys) -> None:
    root = _checkout(tmp_path)
    monkeypatch.chdir(root)
    ws_cli._READY_DESKS.clear()
    ws_cli.note_bridge_ready("alice")
    out, err = capsys.readouterr()
    assert HOOKS_OFF_LINE not in out
    assert HOOKS_OFF_LINE in err.splitlines()
    _git(root, "config", "core.hooksPath", ".githooks")
    ws_cli._READY_DESKS.clear()
    ws_cli.note_bridge_ready("alice")
    assert HOOKS_OFF_LINE not in capsys.readouterr().err
