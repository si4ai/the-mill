"""#630 the room barker map is keyed by DESK alone, a key the spawner knows.

The POST's `roster` follows the seat rule (the desk's one roster other than
Office, else Office), so a desk on several rosters reports Office while its
letters carry another roster. ROSTER/DESK is not predictable; DESK is, because
desk names are unique within an office (one `name` row per type and name)."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KIT = ROOT / "docs/dev/barker-kit.md"
CONNECT = ROOT / "docs/protocol/connect.md"
TABLES = ROOT / "agent_coord/server/sql/tables.sql"


def test_desk_names_are_unique_per_office():
    t = TABLES.read_text(encoding="utf-8")
    m = re.search(r"CREATE TABLE IF NOT EXISTS name \((.*?)\) ENGINE", t, re.S)
    assert m, "name table"
    assert "UNIQUE KEY idx_type (type, name)" in m.group(1)


def test_the_map_is_keyed_by_desk_alone():
    t = KIT.read_text(encoding="utf-8")
    assert "ROSTER/DESK" not in t
    assert "`DESK`, a tab, then that desk's Grok Bot agent id" in t
    assert "Look up `desk` in ~/.config/mill-barker/map.tsv" in t
    assert "desk names are unique within an office" in t
    assert "`roster` is informational" in t


def test_connect_doc_says_desk_is_the_key():
    t = CONNECT.read_text(encoding="utf-8")
    assert "`desk` names the target" in t
    assert "`roster` is informational" in t
    assert t.isascii()
