"""Card 960 / F-gate-fastpath: equal trees take the fast path; a one-byte diff takes the full path."""
from __future__ import annotations

import hashlib
import importlib.util
import os
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load():
    import sys
    name = "release_gate_960"
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / "release_gate.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def rg():
    path = ROOT / "tools" / "release_gate.py"
    if not path.is_file():
        pytest.fail("tools/release_gate.py missing")
    return _load()


def _git(cwd: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()


def _repo_with_two_trees(tmp_path: Path) -> tuple[Path, str, str, str]:
    """Return (repo, passed_sha, equal_merge_sha, differing_sha).

    equal_merge_sha has the same tree as passed_sha (merge with empty change).
    differing_sha changes one byte.
    """
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.name", "builder")
    _git(repo, "config", "user.email", "344578673+pyginapithon@users.noreply.github.com")
    (repo / "pyproject.toml").write_text('version = "1.2.3"\n', encoding="utf-8")
    (repo / "a.txt").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "base")
    passed = _git(repo, "rev-parse", "HEAD")
    # orphan commit with same tree (simulates merge commit whose tree equals passed)
    _git(repo, "checkout", "-q", "--orphan", "merge-eq")
    _git(repo, "commit", "-q", "-m", "merge equal tree", "--allow-empty")
    # force the tree to match passed
    tree = _git(repo, "rev-parse", f"{passed}^{{tree}}")
    equal = _git(repo, "commit-tree", tree, "-m", "merge equal", "-p", passed)
    # differing commit: one-byte change
    _git(repo, "checkout", "-q", "-B", "diff", passed)
    (repo / "a.txt").write_text("hello!\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-q", "-m", "one byte")
    differ = _git(repo, "rev-parse", "HEAD")
    return repo, passed, equal, differ


def test_trees_equal_reports_match(rg, tmp_path):
    repo, passed, equal, _ = _repo_with_two_trees(tmp_path)
    assert rg.trees_equal(repo, passed, equal) is True


def test_trees_differ_reports_mismatch(rg, tmp_path):
    repo, passed, _, differ = _repo_with_two_trees(tmp_path)
    assert rg.trees_equal(repo, passed, differ) is False


def test_equal_tree_takes_fast_path(rg, tmp_path, monkeypatch):
    repo, passed, equal, _ = _repo_with_two_trees(tmp_path)
    calls = []

    def fake_full(*_a, **_k):
        calls.append("full")
        return 1, ["full"]

    def fake_fast(*_a, **_k):
        calls.append("fast")
        return 0, ["fast"]

    monkeypatch.setattr(rg, "run_full_gate", fake_full)
    monkeypatch.setattr(rg, "run_fast_gate", fake_fast)
    code = rg.gate(repo, passed_sha=passed, head_sha=equal, dist=None)
    assert code == 0
    assert calls == ["fast"]


def test_one_byte_diff_takes_full_path(rg, tmp_path, monkeypatch):
    repo, passed, _, differ = _repo_with_two_trees(tmp_path)
    calls = []

    def fake_full(*_a, **_k):
        calls.append("full")
        return 0, ["full"]

    def fake_fast(*_a, **_k):
        calls.append("fast")
        return 0, ["fast"]

    monkeypatch.setattr(rg, "run_full_gate", fake_full)
    monkeypatch.setattr(rg, "run_fast_gate", fake_fast)
    code = rg.gate(repo, passed_sha=passed, head_sha=differ, dist=None)
    assert code == 0
    assert calls == ["full"]


def test_fast_gate_byte_compares_dist(rg, tmp_path):
    """Fast path builds once and refuses when dist bytes differ from the gate build."""
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.name", "builder")
    _git(repo, "config", "user.email", "344578673+pyginapithon@users.noreply.github.com")
    (repo / "pyproject.toml").write_text(
        textwrap.dedent(
            """\
            [project]
            name = "the-mill"
            version = "9.9.9"
            """
        ),
        encoding="utf-8",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "v")
    sha = _git(repo, "rev-parse", "HEAD")
    dist = tmp_path / "dist"
    dist.mkdir()
    # placeholder artifacts with known bytes
    whl = dist / "the_mill-9.9.9-py3-none-any.whl"
    sdist = dist / "the_mill-9.9.9.tar.gz"
    whl.write_bytes(b"WHEEL")
    sdist.write_bytes(b"SDIST")
    # build_once returns different bytes -> fail
    def build_once(_repo, _sha, out: Path):
        out.mkdir(parents=True, exist_ok=True)
        (out / "the_mill-9.9.9-py3-none-any.whl").write_bytes(b"OTHER")
        (out / "the_mill-9.9.9.tar.gz").write_bytes(b"SDIST")
        return "9.9.9"

    code, lines = rg.run_fast_gate(repo, sha, dist, build_once=build_once)
    assert code != 0
    assert any("byte-compare" in ln or "bytes" in ln for ln in lines), lines


def test_terse_ok_line(rg):
    assert rg.ok_line("deadbeef", "fast") == "gate OK fast deadbeef"
