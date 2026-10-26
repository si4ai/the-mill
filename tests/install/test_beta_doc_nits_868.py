"""Beta schema text checks (card 868, F166). Git tree only: no database.

name_event is gone (the owner: no name history), so neither beta file uses it beyond a DROP IF EXISTS. The header's table count is
the DDL's CREATE TABLE count. A procedure the shipped beta client calls is defined in a book or listed in
BETA-CHANGES.md as not in any book yet, so the doc does not promise a read that no book installs.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BETA = ROOT / "docs" / "requirements" / "beta"
BOOK_SQL = sorted((ROOT / "agent_coord" / "server" / "sql").glob("*.sql")) + [BETA / "beta_sp.sql"]


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_beta_files_have_no_name_event():
    # Only a DROP ... IF EXISTS may name it, so an older book loses it on the next apply.
    for name in ("beta_ddl.sql", "beta_sp.sql"):
        bad = [ln for ln in _read(BETA / name).splitlines() if "name_event" in ln and not ln.startswith("DROP ")]
        assert not bad, f"{name} still uses name_event: {bad[:3]}"


def test_header_table_counts_match_the_ddl():
    ddl = _read(BETA / "beta_ddl.sql")
    n = len(re.findall(r"^CREATE TABLE ", ddl, re.M))
    head = [ln for ln in ddl.splitlines()[:5] if ln.startswith("--")]
    said = [int(m) for ln in head for m in re.findall(r"\b(\d+) tables\b", ln)]
    assert said, "the header names the table count"
    assert set(said) == {n}, f"header says {said} tables, the DDL creates {n}"


def test_client_procedures_are_defined_or_listed_as_pending():
    client = _read(ROOT / "agent_coord" / "server" / "beta_client.py")
    called = set(re.findall(r'CALL (\w+)\(', client))
    assert called, "the beta client calls a procedure"
    books = "\n".join(_read(p) for p in BOOK_SQL)
    changes = _read(BETA / "BETA-CHANGES.md")
    pending = re.search(r"^## Not in any book yet\n(.*?)(?=^## |\Z)", changes, re.M | re.S)
    listed = set(re.findall(r"`(\w+)`", pending.group(1))) if pending else set()
    bad = [p for p in sorted(called)
           if not re.search(rf"CREATE PROCEDURE (?:IF NOT EXISTS )?`?{p}`?\s*\(", books) and p not in listed]
    assert not bad, f"client calls procedures no book defines and BETA-CHANGES.md does not list as pending: {bad}"
