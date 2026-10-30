"""Beta schema files stay out of the pack and out of the 0.7 SQL stamp (card 868, F160).

Git tree only: no database. The beta DDL is a proposal under docs/requirements/beta/, so the wheel's
server/sql/* glob does not ship it; its glance_cache columns are the keys the shipped client reads;
the EXECUTE-only grant lives outside migrate.py, whose bytes are part of MILL_SQL_STAMP.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BETA = ROOT / "docs" / "requirements" / "beta"
SQL = ROOT / "agent_coord" / "server" / "sql"


def test_beta_files_live_under_docs_not_the_pack():
    for name in ("beta_ddl.sql", "beta_sp.sql", "BETA-CHANGES.md"):
        assert (BETA / name).is_file(), name
        assert not (SQL / name).exists(), f"{name} under server/sql ships in the wheel"
    order = (SQL / "apply_order.txt").read_text(encoding="utf-8")
    assert "beta" not in order


def _glance_columns() -> list[str]:
    ddl = (BETA / "beta_ddl.sql").read_text(encoding="utf-8")
    m = re.search(r"CREATE TABLE (?:IF NOT EXISTS )?glance_cache \((.*?)\n\)", ddl, re.S)
    assert m, "glance_cache table"
    cols = []
    for part in re.split(r",\s*", m.group(1)):
        w = part.strip().split()
        if w and w[0] not in ("PRIMARY", "CONSTRAINT", "KEY", "UNIQUE"):
            cols.append(w[0].strip("`"))
    return cols


def test_glance_cache_columns_are_the_client_keys():
    from agent_coord.server.beta_client import _CACHE_KEYS

    cols = _glance_columns()
    missing = [k for k in _CACHE_KEYS if k not in cols]
    assert not missing, f"client reads keys the beta glance_cache does not have: {missing}"


def test_grant_is_outside_the_stamped_migrate_module():
    from agent_coord.install import beta_grant, migrate

    assert not hasattr(migrate, "grant_app_user")
    assert callable(beta_grant.grant_app_user)
    assert "beta" not in (ROOT / "agent_coord" / "install" / "migrate.py").read_text(encoding="utf-8").lower()
