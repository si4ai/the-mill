"""F205 (#757): check_pack refuses symlinks and untracked pack members.

A tracked mode-120000 path under a packaged tree, or a pack member with no
matching tracked regular file at HEAD, must fail check_pack and the pre-commit
hook. setuptools dereferences links before mill_build sees them, so the tip
and provenance scans are the real gate.
"""
from __future__ import annotations

import importlib.util
import io
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _python_with_setuptools() -> str:
    """CI's pytest env has setuptools (ci.txt); local may need another interpreter."""
    import shutil
    import sys
    candidates = [sys.executable]
    for extra in ("/tmp/venv-757-build/bin/python", shutil.which("python3")):
        if extra and extra not in candidates:
            candidates.append(extra)
    for py in candidates:
        got = subprocess.run(
            [py, "-c", "import setuptools"], capture_output=True, check=False
        )
        if got.returncode == 0:
            return py
    pytest.skip("setuptools not installed (needed for the in-tree mill_build backend)")


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def cp():
    return _load("check_pack_757", "tools/check_pack.py")


@pytest.fixture(scope="module")
def hy():
    return _load("precommit_hygiene_757", "tools/precommit_hygiene.py")


def _git(cwd: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd, text=True)


def _init_repo(tmp: Path) -> Path:
    repo = tmp / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "builder@users.noreply.github.com")
    _git(repo, "config", "user.name", "builder")
    (repo / "agent_coord" / "web" / "static").mkdir(parents=True)
    (repo / "agent_coord" / "web" / "static" / "board.html").write_text("ok\n", encoding="utf-8")
    _git(repo, "add", "agent_coord/web/static/board.html")
    _git(repo, "commit", "-qm", "seed")
    return repo


def test_git_tip_refuses_mode_120000_under_packaged_path(tmp_path, cp):
    repo = _init_repo(tmp_path)
    canary = tmp_path / "outside-canary.txt"
    canary.write_text("CANARY-BYTES\n", encoding="utf-8")
    link = repo / "agent_coord" / "web" / "static" / "zz-canary.css"
    link.symlink_to(canary)
    _git(repo, "add", "agent_coord/web/static/zz-canary.css")
    _git(repo, "commit", "-qm", "add symlink")
    modes = cp.git_index_modes(repo)
    assert modes.get("agent_coord/web/static/zz-canary.css") == "120000"
    fails = cp.scan_git_symlinks(modes)
    assert fails, "mode-120000 under agent_coord must fail the tip scan"
    assert any("symlink" in f or "120000" in f for f in fails)


def test_hygiene_staged_refuses_mode_120000(tmp_path, hy, monkeypatch):
    repo = _init_repo(tmp_path)
    canary = tmp_path / "outside-canary.txt"
    canary.write_text("CANARY-BYTES\n", encoding="utf-8")
    link = repo / "agent_coord" / "web" / "static" / "zz-canary.css"
    link.symlink_to(canary)
    _git(repo, "add", "agent_coord/web/static/zz-canary.css")
    monkeypatch.setattr(hy, "ROOT", repo)
    fails = hy.scan_staged_modes()
    assert fails and any("zz-canary.css" in f for f in fails)


def _wheel_with(member: str, data: bytes, path: Path) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(member, data)
        zf.writestr("the_mill-0.0.0.dist-info/METADATA", "Name: the-mill\nVersion: 0.0.0\n")
    return path


def _sdist_with(member: str, data: bytes, path: Path) -> Path:
    # member is repo-relative; nest under the_mill-0.0.0/
    with tarfile.open(path, "w:gz") as tf:
        for name, blob in (
            (f"the_mill-0.0.0/{member}", data),
            ("the_mill-0.0.0/PKG-INFO", b"Name: the-mill\n"),
        ):
            info = tarfile.TarInfo(name)
            info.size = len(blob)
            tf.addfile(info, io.BytesIO(blob))
    return path


def test_pack_member_from_symlink_target_fails_provenance(tmp_path, cp):
    """Simulate setuptools dereferencing a link: pack holds canary bytes at a
    path whose git mode is 120000."""
    modes = {
        "agent_coord/web/static/board.html": "100644",
        "agent_coord/web/static/zz-canary.css": "120000",
    }
    whl = _wheel_with(
        "agent_coord/web/static/zz-canary.css",
        b"CANARY-BYTES\n",
        tmp_path / "t.whl",
    )
    fails = cp.scan_pack_provenance(whl, "wheel", modes)
    assert fails and any("zz-canary.css" in f for f in fails)


def test_untracked_pack_member_fails_provenance(tmp_path, cp):
    modes = {"agent_coord/web/static/board.html": "100644"}
    whl = _wheel_with(
        "agent_coord/web/static/zz-untracked.md",
        b"sneak\n",
        tmp_path / "t.whl",
    )
    sdist = _sdist_with(
        "agent_coord/web/static/zz-untracked.md",
        b"sneak\n",
        tmp_path / "t.tar.gz",
    )
    w_fails = cp.scan_pack_provenance(whl, "wheel", modes)
    s_fails = cp.scan_pack_provenance(sdist, "sdist", modes)
    assert w_fails and any("untracked" in f or "zz-untracked" in f for f in w_fails)
    assert s_fails and any("untracked" in f or "zz-untracked" in f for f in s_fails)


def test_tracked_regular_member_and_dist_info_pass(tmp_path, cp):
    modes = {"agent_coord/web/static/board.html": "100644", "README.md": "100644"}
    whl = tmp_path / "ok.whl"
    with zipfile.ZipFile(whl, "w") as zf:
        zf.writestr("agent_coord/web/static/board.html", b"ok\n")
        zf.writestr("the_mill-0.0.0.dist-info/METADATA", b"Name: the-mill\n")
        zf.writestr("the_mill-0.0.0.data/data/share/the-mill/README.md", b"# mill\n")
    assert cp.scan_pack_provenance(whl, "wheel", modes) == []



def test_main_wires_symlink_and_provenance(cp):
    """Mutants: dropping either call from main() must fail this source check."""
    src = (ROOT / "tools" / "check_pack.py").read_text(encoding="utf-8")
    # Narrow to main() body.
    start = src.index("def main(")
    end = src.index("\nif __name__", start)
    body = src[start:end]
    assert "scan_git_symlinks(tip_modes)" in body
    assert "scan_pack_provenance(path, kind, tip_modes)" in body


def test_hygiene_main_wires_staged_modes(hy):
    """Mutant: dropping scan_staged_modes from the staged path must fail."""
    src = (ROOT / "tools" / "precommit_hygiene.py").read_text(encoding="utf-8")
    start = src.index("def main(")
    body = src[start:]
    assert "scan_staged() + scan_staged_modes()" in body


def test_real_build_symlink_and_untracked_fail_check_pack(tmp_path):
    """One real backend build + check_pack dist for both card cases.

    Uses the in-tree mill_build backend (same as CI `--no-isolation`), so the
    test does not need the PyPI `build` package. Covers the setuptools
    dereference path the unit fakes only approximate.
    """
    import os
    import shutil
    import sys

    if shutil.which("git") is None:
        pytest.skip("git not on PATH")

    def run(cwd: Path, args: list[str], env: dict | None = None) -> subprocess.CompletedProcess:
        base = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        if env:
            base.update(env)
        return subprocess.run(args, cwd=cwd, capture_output=True, text=True, env=base, check=False)

    def seed_clone(dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        subprocess.check_call(
            ["git", "clone", "-q", "--local", str(ROOT), str(dest)],
        )
        _git(dest, "config", "user.email", "builder@users.noreply.github.com")
        _git(dest, "config", "user.name", "builder")
        # Local hooksPath may point at a missing tree after clone; disable.
        _git(dest, "config", "core.hooksPath", "/dev/null")
        return dest

    def build_dist(repo: Path) -> None:
        epoch = _git(repo, "log", "-1", "--format=%ct").strip()
        code = (
            "import os, sys; "
            "sys.path.insert(0, os.path.join(os.getcwd(), 'build_backend')); "
            "import mill_build; "
            "os.makedirs('dist', exist_ok=True); "
            "print(mill_build.build_wheel('dist')); "
            "print(mill_build.build_sdist('dist'))"
        )
        py = _python_with_setuptools()
        got = run(repo, [py, "-c", code], env={"SOURCE_DATE_EPOCH": epoch})
        assert got.returncode == 0, got.stdout + got.stderr

    # --- symlink case ---
    sym = seed_clone(tmp_path / "sym")
    canary = tmp_path / "outside-canary.txt"
    canary.write_text("CANARY-BYTES-SYMLINK\n", encoding="utf-8")
    link = sym / "agent_coord" / "web" / "static" / "zz-canary-757.css"
    link.symlink_to(canary)
    _git(sym, "add", "agent_coord/web/static/zz-canary-757.css")
    _git(sym, "commit", "-q", "--no-verify", "-m", "#757 symlink canary")
    build_dist(sym)
    check = run(sym, [sys.executable, "tools/check_pack.py", "dist"])
    assert check.returncode == 1, check.stdout + check.stderr
    assert ("symlink" in check.stdout) or ("120000" in check.stdout), check.stdout

    # --- untracked case ---
    unt = seed_clone(tmp_path / "unt")
    sneak = unt / "agent_coord" / "web" / "static" / "zz-untracked-757.md"
    sneak.write_text("sneak-untracked\n", encoding="utf-8")
    build_dist(unt)
    check = run(unt, [sys.executable, "tools/check_pack.py", "dist"])
    assert check.returncode == 1, check.stdout + check.stderr
    assert "untracked" in check.stdout, check.stdout
