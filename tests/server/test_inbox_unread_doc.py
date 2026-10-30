"""F21 doc row; the handler no longer reads the whole mailbox."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_regression_row_f21_documented():
    doc = (ROOT / "docs" / "protocol" / "commands.md").read_text(encoding="utf-8")
    assert "Regression row F21 (inbox-unread-page)" in doc


def test_inbox_handler_uses_the_page_procedure():
    src = (ROOT / "agent_coord" / "server" / "api" / "mill" / "rpc.py").read_text(encoding="utf-8")
    start = src.index("def _h_inbox(")
    body = src[start : src.index("\ndef ", start + 10)]
    assert "rec_mail.inbox(" in body
    assert "rec_mail.select(" not in body and "letters_by_id(" not in body


def test_index_in_tables_and_ensure():
    tables = (ROOT / "agent_coord" / "server" / "sql" / "tables.sql").read_text(encoding="utf-8")
    assert "KEY idx_desk_unread (desk_id, opened, id)" in tables
    mig = (ROOT / "agent_coord" / "install" / "migrate.py").read_text(encoding="utf-8")
    assert "ADD KEY idx_desk_unread (desk_id, opened, id)" in mig and "_ensure_mail_to_unread(cn)" in mig


def test_inbox_page_is_a_read_for_the_pane_cache():
    from agent_coord.server import table_ver

    assert table_ver.tables_for_proc("mill_mail_inbox") == ()
    assert table_ver.tables_for_proc("mill_mail_insert") != ()
