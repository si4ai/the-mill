"""Beta schema files stay out of the pack and out of the 0.7 SQL stamp (card 868, F160).

Git tree only: no database. The beta DDL is a proposal under docs/requirements/beta/, so the wheel's
server/sql/* glob does not ship it; the glance keeps the reply keys the shipped client reads;
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


# The owner (2026-10-26): the glance is computed live (no glance_cache), and its reply keeps the keys the client
# already reads. open_votes went with the vote table (F176).
GLANCE_KEYS = (
    "id", "at", "refresh_us", "present", "held", "open_n", "claimed_n", "parked_n", "shipped_n", "done_n",
    "letters_1d", "card_moves_1d", "doings_1d", "holds_1d", "points_1d",
)


def test_glance_keys_are_kept_and_no_cache_table():
    from agent_coord.server.beta_client import _CACHE_KEYS

    assert _CACHE_KEYS == GLANCE_KEYS
    ddl = (BETA / "beta_ddl.sql").read_text(encoding="utf-8")
    assert "glance_cache" not in ddl
    src = (ROOT / "agent_coord" / "server" / "beta_client.py").read_text(encoding="utf-8")
    assert "open_votes" not in src


def test_grant_is_outside_the_stamped_migrate_module():
    from agent_coord.install import beta_grant, migrate

    assert not hasattr(migrate, "grant_app_user")
    assert callable(beta_grant.grant_app_user)
    assert "beta" not in (ROOT / "agent_coord" / "install" / "migrate.py").read_text(encoding="utf-8").lower()
