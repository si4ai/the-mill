"""Card 1171: wake idx_cause_id is declared and ensure adds it."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_idx_cause_id_in_tables_and_ensure() -> None:
    tables = (ROOT / "agent_coord" / "server" / "sql" / "tables.sql").read_text(encoding="utf-8")
    ddl = (ROOT / "docs" / "requirements" / "beta" / "beta_ddl.sql").read_text(encoding="utf-8")
    mig = (ROOT / "agent_coord" / "install" / "migrate.py").read_text(encoding="utf-8")
    key = "KEY idx_cause_id (cause, cause_id, state)"
    assert key in tables
    assert key in ddl
    assert "ADD KEY idx_cause_id (cause, cause_id, state)" in mig
    assert "_ensure_wake_cause_id_idx(cn)" in mig
    design = (ROOT / "docs" / "requirements" / "schema-design.md").read_text(encoding="utf-8")
    assert "idx_cause_id" in design and "card 1171" in design.lower()


@pytest.mark.sql
def test_ensure_adds_idx_cause_id(cn) -> None:
    from agent_coord.install import migrate

    cur = cn.cursor()
    cur.execute("ALTER TABLE wake DROP INDEX idx_cause_id")
    cn.commit()
    cur.close()
    assert migrate._ensure_wake_cause_id_idx(cn) == ["wake.idx_cause_id"]
    assert migrate._ensure_wake_cause_id_idx(cn) == []
    cur = cn.cursor()
    cur.execute(
        "SELECT 1 FROM information_schema.STATISTICS"
        " WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'wake'"
        " AND INDEX_NAME = 'idx_cause_id' LIMIT 1"
    )
    assert cur.fetchone() is not None
    cur.close()
