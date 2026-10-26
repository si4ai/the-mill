"""PR rule (card 868, F160): a diff touching tables.sql or beta_ddl.sql updates BETA-CHANGES.md or schema-design.md.

Git only: no database, no server. Skips when no base branch can be found.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# ---------- PR rule: a schema diff carries its explanation ----------
SCHEMA = ("agent_coord/server/sql/tables.sql", "docs/requirements/beta/beta_ddl.sql")
EXPLAIN = ("docs/requirements/beta/BETA-CHANGES.md", "docs/requirements/schema-design.md")


def _changed_files() -> list[str] | None:
    base_ref = os.environ.get("GITHUB_BASE_REF") or os.environ.get("MILL_SCHEMA_BASE") or "main"
    for ref in (f"origin/{base_ref}", base_ref):
        try:
            base = subprocess.run(["git", "merge-base", "HEAD", ref], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
            out = subprocess.run(["git", "diff", "--name-only", base, "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
            return [x.strip() for x in out.splitlines() if x.strip()]
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
    return None


def test_schema_diff_updates_beta_changes_or_design():
    files = _changed_files()
    if files is None:
        pytest.skip("no git base to diff against (set GITHUB_BASE_REF or MILL_SCHEMA_BASE)")
    if any(f in SCHEMA for f in files):
        assert any(f in EXPLAIN for f in files), (
            "a diff touching tables.sql or beta_ddl.sql must update BETA-CHANGES.md (a departure) "
            "or docs/requirements/schema-design.md (a design change)")
