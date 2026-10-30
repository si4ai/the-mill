"""mill briefing on a pip --user install finds share/the-mill under the user base."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from agent_coord.install import office


def _fake_share(root: Path) -> Path:
    share = root / "share" / "the-mill"
    (share / "docs" / "protocol").mkdir(parents=True)
    (share / "docs" / "protocol" / "commands.md").write_text("# commands\n", encoding="utf-8")
    (share / "docs" / "protocol" / "skill.md").write_text("# skill\n", encoding="utf-8")
    return share


@pytest.fixture
def no_git(monkeypatch, tmp_path):
    """Pretend the package is installed (no checkout docs next to it)."""
    pkg = tmp_path / "site" / "lib" / "python3.x" / "site-packages" / "agent_coord" / "install"
    pkg.mkdir(parents=True)
    monkeypatch.setattr(office, "__file__", str(pkg / "office.py"))
    monkeypatch.setattr(sys, "prefix", str(tmp_path / "venv-empty"))
    monkeypatch.setattr(sys, "base_prefix", str(tmp_path / "base-empty"))
    return tmp_path


def test_user_base_share_found(no_git, monkeypatch):
    user = no_git / "userbase"
    share = _fake_share(user)
    import site
    import sysconfig

    monkeypatch.setattr(site, "getuserbase", lambda: str(user))
    monkeypatch.setattr(sysconfig, "get_path", lambda name, scheme=None: str(user))
    assert office.mill_root() == share
    assert "skill" in office.briefing_text("skill")


def test_prefix_share_still_first(no_git, monkeypatch):
    pref = no_git / "venv"
    share = _fake_share(pref)
    monkeypatch.setattr(sys, "prefix", str(pref))
    assert office.mill_root() == share


def test_package_relative_prefix(no_git, monkeypatch):
    import site
    import sysconfig

    monkeypatch.setattr(site, "getuserbase", lambda: str(no_git / "nouser"))
    monkeypatch.setattr(sysconfig, "get_path", lambda name, scheme=None: str(no_git / "nouser"))
    share = _fake_share(no_git / "site")
    assert office.mill_root() == share


def test_missing_everywhere_raises(no_git, monkeypatch):
    import site
    import sysconfig

    monkeypatch.setattr(site, "getuserbase", lambda: str(no_git / "nouser"))
    monkeypatch.setattr(sysconfig, "get_path", lambda name, scheme=None: str(no_git / "nouser"))
    with pytest.raises(FileNotFoundError):
        office.mill_root()
