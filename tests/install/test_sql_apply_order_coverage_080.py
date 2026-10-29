"""Every agent_coord/server/sql/*.sql is in apply_order.txt or on a named skip list (F191)."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SQL = ROOT / "agent_coord" / "server" / "sql"

# Existing-book-only migrations and one-shot shape upgrades. Fresh installs use tables.sql.
# Do not put a live SP (sp_*.sql / fn_*.sql) here - those belong in apply_order.txt.
SKIP = frozenset(
    {
        "migrate_070_roster.sql",
        "migrate_080.sql",
        "migrate_818_doing.sql",
        "name_type.sql",
    }
)


def _order_names() -> set[str]:
    names: set[str] = set()
    for line in (SQL / "apply_order.txt").read_text(encoding="utf-8-sig").splitlines():
        name = line.strip()
        if name and not name.startswith("#"):
            names.add(name)
    return names


def test_every_sql_file_is_in_apply_order_or_on_the_skip_list() -> None:
    order = _order_names()
    files = {p.name for p in SQL.glob("*.sql")}
    missing = sorted(files - order - SKIP)
    assert missing == [], (
        "sql files not in apply_order.txt and not on SKIP "
        f"(existing-book migrations only): {missing}"
    )
    # Skip entries must exist on disk (no stale names).
    assert SKIP <= files, f"SKIP names missing from sql/: {sorted(SKIP - files)}"
    # apply_order names must exist.
    assert order <= files, f"apply_order names missing from sql/: {sorted(order - files)}"
