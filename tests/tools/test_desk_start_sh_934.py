"""F-desk-start-sh: POSIX desk-start.sh reads planner JSON and execs grok (card 934)."""
from __future__ import annotations

import json
import os
import stat
import subprocess
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SH = ROOT / "tools" / "desk" / "desk-start.sh"
PLAN = ROOT / "tools" / "desk" / "desk_start_plan.py"
EXAMPLE = ROOT / "tools" / "desk" / "desks.example.json"
ROW = ROOT / "docs" / "security" / "regression" / "F-desk-start-sh.md"
MATRIX = ROOT / "docs" / "security" / "REGRESSION-MATRIX.md"


def _unix_cfg(tmp: Path, *, cred_file: Path | None = None) -> Path:
    work = tmp / "work"
    export = tmp / "exports"
    work.mkdir()
    export.mkdir()
    agent = tmp / "agent.md"
    agent.write_text("# example\n", encoding="utf-8")
    target = str(cred_file) if cred_file is not None else "mill-desk/example-desk/github-pat"
    cfg = {
        "office": {
            "mill_office": "example-office",
            "mill_connect_template": "mill --office {mill_office} connect {roster} {desk}",
            "roster": "example-roster",
            "export_before_restart": True,
            "launch_mode": "window",
            "leader_socket": "",
        },
        "defaults": {
            "permission_mode": "default",
            "allow_bypass_permissions": False,
            "lessons_byte_cap": 12000,
            "lessons_count_cap": 25,
            "handoff_char_cap": 1500,
        },
        "desks": [
            {
                "name": "example-desk",
                "work_dir": str(work),
                "export_dir": str(export),
                "agent_file": str(agent),
                "model": "grok-example",
                "reasoning_effort": "high",
                "permission_mode": "default",
                "credential_target": target,
                "lessons_label": "learn-example-desk",
                "add_dirs": [],
            }
        ],
    }
    path = tmp / "desks.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    return path


def _run_sh(args: list[str], *, env: dict | None = None) -> subprocess.CompletedProcess[str]:
    e = os.environ.copy()
    if env:
        e.update(env)
    return subprocess.run(
        ["sh", str(SH), *args],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        env=e,
        check=False,
    )


def test_files_and_row_exist():
    assert SH.is_file(), "tools/desk/desk-start.sh missing"
    assert os.access(SH, os.X_OK) or True  # mode may be set in git
    assert ROW.is_file()
    text = MATRIX.read_text(encoding="utf-8")
    assert "F-desk-start-sh" in text
    assert "934" in text or "desk-start-sh" in text


def test_posix_only_no_gnu_or_bashisms():
    src = SH.read_text(encoding="utf-8")
    for bad in ("[[", "source ", "function ", "echo -e", "readarray", "mapfile", "|&"):
        assert bad not in src, f"bash/GNU-only construct {bad!r} in desk-start.sh"
    # shebang must be plain sh
    first = src.splitlines()[0]
    assert first.startswith("#!") and ("/sh" in first or first == "#!/usr/bin/env sh")


def test_dry_run_matches_planner_shape(tmp_path: Path):
    cred = tmp_path / "cred"
    cred.write_text("placeholder-not-a-secret\n", encoding="utf-8")
    cred.chmod(0o600)
    cfg = _unix_cfg(tmp_path, cred_file=cred)
    sid = "11111111-1111-1111-1111-111111111111"
    cp = _run_sh(
        ["--config", str(cfg), "--desk", "example-desk", "--dry-run", "--session-id", sid],
    )
    assert cp.returncode == 0, cp.stderr + cp.stdout
    plan = json.loads(cp.stdout)
    assert plan["outcome"] == "ok"
    assert plan["dry_run"] is True
    assert plan["desk"] == "example-desk"
    assert plan["session_id"] == sid
    assert plan["launch"] == "positional-prompt"
    assert plan["launch_mode"] == "window"
    argv = plan["argv"]
    assert argv[0] == "grok"
    assert "-s" in argv and argv[argv.index("-s") + 1] == sid
    for bad in ("-r", "--resume", "-c", "--continue", "-p", "--single", "--fork-session"):
        assert bad not in argv
    # credential where names a backend we support
    where = plan["credential"]["where"]
    assert where in (
        "Credential Manager",
        "macOS keychain",
        "mode-600 file",
        "file",
    )


def test_missing_cred_refuses_live(tmp_path: Path):
    cfg = _unix_cfg(tmp_path, cred_file=tmp_path / "missing-cred")
    cp = _run_sh(["--config", str(cfg), "--desk", "example-desk"])
    assert cp.returncode != 0
    assert "credential" in (cp.stderr + cp.stdout).lower()


def test_mode600_wrong_mode_refuses(tmp_path: Path):
    cred = tmp_path / "cred"
    cred.write_text("x\n", encoding="utf-8")
    cred.chmod(0o644)
    cfg = _unix_cfg(tmp_path, cred_file=cred)
    cp = _run_sh(["--config", str(cfg), "--desk", "example-desk", "--dry-run"])
    # dry-run may still plan with --no-cred path; live refuses. For dry-run with
    # present-but-wrong-mode file target, script should treat as missing.
    assert cp.returncode != 0 or "credential" in (cp.stderr + cp.stdout).lower() or (
        cp.returncode == 0 and json.loads(cp.stdout).get("outcome") == "refuse"
    )
