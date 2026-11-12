"""Card 962: the post-ship script is one ok line, or one line per miss."""
from __future__ import annotations

import json
from pathlib import Path

from tools.post_ship_check import run_checks

SHA = "abc123"
OTHER = "def456"
WHEEL = "the_mill-0.8.2-py3-none-any.whl"
SDIST = "the_mill-0.8.2.tar.gz"


def _git_ok(args: list[str]) -> tuple[int, str]:
    assert args[0] == "rev-parse"
    return 0, SHA


def _fetch_ok(url: str, redirects: bool) -> tuple[int, dict[str, str], bytes]:
    if url.endswith("/json"):
        body = json.dumps(
            {"urls": [{"filename": WHEEL, "url": "https://files.example/wheel"}, {"filename": SDIST, "url": "https://files.example/sdist"}]}
        ).encode()
        return 200, {}, body
    if url.endswith("/wheel"):
        return 200, {}, b"wheel-bytes"
    if url.endswith("/sdist"):
        return 200, {}, b"sdist-bytes"
    assert url == "https://office.example/health"
    assert redirects is False
    return 200, {"X-Mill-Version": "0.8.2"}, b'{"ok":true}'


def _gate(tmp: Path) -> Path:
    gate = tmp / "dist"
    gate.mkdir()
    (gate / WHEEL).write_bytes(b"wheel-bytes")
    (gate / SDIST).write_bytes(b"sdist-bytes")
    return gate


def _run(tmp: Path, *, git=_git_ok, fetch=_fetch_ok, offices=None, sha=SHA.upper(), skills=None):
    return run_checks(
        tag="v0.8.2",
        sha=sha,
        version="0.8.2",
        gate=_gate(tmp),
        offices=["https://office.example/ignored"] if offices is None else offices,
        fetch=fetch,
        git=git,
        skills=skills,
    )


def test_all_three_checks_pass(tmp_path: Path):
    assert _run(tmp_path) == []


def test_tag_points_elsewhere(tmp_path: Path):
    def git(args: list[str]) -> tuple[int, str]:
        return 0, OTHER

    assert _run(tmp_path, git=git) == [f"tag v0.8.2 points at {OTHER}, not {SHA}"]


def test_tag_missing(tmp_path: Path):
    def git(args: list[str]) -> tuple[int, str]:
        return 1, ""

    assert _run(tmp_path, git=git) == ["tag v0.8.2 does not resolve"]


def test_pack_bytes_differ(tmp_path: Path):
    def fetch(url: str, redirects: bool):
        status, headers, body = _fetch_ok(url, redirects)
        if url.endswith("/wheel"):
            return 200, {}, b"other-bytes"
        return status, headers, body

    assert _run(tmp_path, fetch=fetch) == [f"pypi {WHEEL} differs from the gate build"]


def test_pypi_missing_and_extra(tmp_path: Path):
    def fetch(url: str, redirects: bool):
        if url.endswith("/json"):
            body = json.dumps(
                {"urls": [{"filename": "extra.whl", "url": "https://files.example/extra"}]}
            ).encode()
            return 200, {}, body
        return 200, {}, b"extra"
    misses = _run(tmp_path, fetch=fetch)
    assert f"pypi has no {WHEEL}" in misses
    assert f"pypi has no {SDIST}" in misses
    assert "pypi has extra extra.whl" in misses


def test_health_version_and_status(tmp_path: Path):
    def fetch(url: str, redirects: bool):
        if url == "https://good.example/health":
            return 200, {"x-mill-version": "0.8.2"}, b'{"ok": true, "db_driver": "pure"}'
        if url == "https://old.example/health":
            return 200, {"X-Mill-Version": "0.8.1"}, b'{"ok":true}'
        if url == "http://down.example/health":
            return 503, {"X-Mill-Version": "0.8.2"}, b'{"ok":false}'
        return _fetch_ok(url, redirects)

    misses = _run(
        tmp_path,
        fetch=fetch,
        offices=[
            "https://good.example/wall",
            "https://old.example",
            "http://down.example/health",
        ],
    )
    assert misses == [
        "health old.example version 0.8.1 != 0.8.2",
        "health down.example status 503",
    ]


def test_empty_gate_and_no_office(tmp_path: Path):
    misses = run_checks(
        tag="v0.8.2",
        sha=SHA,
        version="0.8.2",
        gate=tmp_path,
        offices=[],
        fetch=_fetch_ok,
        git=_git_ok,
    )
    assert misses == ["gate build has no pack files", "no office given"]


# Card 998: installed desk skill copies against the released skill.md.

SKILL = "---\nname: mill-desk\n---\nbody line\n"


def _git_skill(args: list[str]) -> tuple[int, str]:
    if args[0] == "show":
        assert args[1] == "v0.8.2:docs/protocol/skill.md"
        return 0, SKILL.strip()
    return _git_ok(args)


def test_skill_copy_matches_release_card_998(tmp_path: Path):
    from tools.post_ship_check import check_skills, skill_sha

    copy = tmp_path / "SKILL.md"
    copy.write_bytes(SKILL.replace("\n", "\r\n").encode())
    assert _run(tmp_path, git=_git_skill, skills=[copy]) == []
    lines, misses = check_skills("v0.8.2", [copy], _git_skill)
    sha = skill_sha(SKILL)
    assert lines == [f"skill {copy} installed {sha} released {sha}"] and misses == []


def test_stale_or_missing_skill_copy_is_a_miss_card_998(tmp_path: Path):
    from tools.post_ship_check import skill_sha

    stale = tmp_path / "SKILL.md"
    stale.write_text("---\nname: mill-desk\n---\nold body\n", encoding="utf-8")
    gone = tmp_path / "gone.md"
    misses = _run(tmp_path, git=_git_skill, skills=[stale, gone])
    assert misses == [
        f"skill {stale} installed {skill_sha(stale.read_text())} released {skill_sha(SKILL)} (copy the pack skill.md over it)",
        f"skill {gone} is not readable; released {skill_sha(SKILL)}",
    ]


def test_skill_source_missing_at_tag_card_998(tmp_path: Path):
    def git(args: list[str]) -> tuple[int, str]:
        return (128, "") if args[0] == "show" else _git_ok(args)

    copy = tmp_path / "SKILL.md"
    copy.write_text(SKILL, encoding="utf-8")
    assert _run(tmp_path, git=git, skills=[copy]) == ["skill docs/protocol/skill.md is not readable at v0.8.2"]
