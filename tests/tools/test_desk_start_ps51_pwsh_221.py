"""Optional pwsh dry-run for F221. Not cited in the matrix (card 940 / F-pwsh-f221-guard).

Lives outside the matrix-cited ps51 module so a missing pwsh skips this
file's case at collection without tripping the card-663 guard.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PS1 = ROOT / "tools" / "desk" / "desk-start.ps1"
EXAMPLE = ROOT / "tools" / "desk" / "desks.example.json"


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="pwsh not on PATH (CI is ubuntu)")
def test_dry_run_execution_emits_json_and_exit_zero(tmp_path):
    """when pwsh is present, dry-run must print one json object and exit 0."""
    cfg = tmp_path / "desks.json"
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    data["office"]["launch_mode"] = "window"
    for d in data["desks"]:
        d["work_dir"] = str(tmp_path / "work")
        d["export_dir"] = str(tmp_path / "exports")
        d["agent_file"] = str(tmp_path / "agent.md")
        d["add_dirs"] = []
    cfg.write_text(json.dumps(data), encoding="utf-8")
    proc = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-File",
            str(PS1),
            "-Config",
            str(cfg),
            "-Desk",
            "example-desk",
            "-DryRun",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    blob = proc.stdout.strip() or proc.stderr.strip()
    m = re.search(r"\{.*\}\s*$", blob, flags=re.S)
    assert m, f"expected JSON plan in output, got: {blob[:500]!r}"
    plan = json.loads(m.group(0))
    assert plan.get("dry_run") is True
    assert isinstance(plan.get("would_launch"), bool)
