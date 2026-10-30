"""Card 847 (F139): the record docs say what the schema and the commands do.

Reads tables.sql and the procedure files, then checks records.md, states.md
and commands.md against them, so a renamed table, type or procedure fails here
instead of drifting in prose (PROPOSAL 2.8 D1-D5, D9).
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SQL = ROOT / "agent_coord" / "server" / "sql"
PROTO = ROOT / "docs" / "protocol"

# mill_* words in the docs that are tables or databases, not routines.
NOT_ROUTINES = {"mill_invite", "mill_invite_join", "mill_records_test"}


def _tables_sql():
    return (SQL / "tables.sql").read_text(encoding="utf-8")


def _tables():
    return re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", _tables_sql())


def _enum(table):
    body = _tables_sql().split(f"CREATE TABLE IF NOT EXISTS {table} (", 1)[1]
    m = re.search(r"\n\s+type\s+ENUM\(([^)]*)\)", body)
    return re.findall(r"'(\w+)'", m.group(1))


def _routines():
    out = set()
    for f in SQL.glob("*.sql"):
        out |= set(re.findall(r"CREATE (?:PROCEDURE|FUNCTION)\s+(\w+)", f.read_text(encoding="utf-8")))
    return out


def _doc(name):
    return (PROTO / name).read_text(encoding="utf-8")


def _records_rows():
    rows = {}
    for line in _doc("records.md").splitlines():
        m = re.match(r"\| `(\w+)` \| (.*) \|$", line)
        if m:
            rows[m.group(1)] = m.group(2)
    return rows


def _types_in(text):
    m = re.search(r"Types?: ((?:`\w+`(?:, | and | or |, or |, and )?)+)", text)
    return re.findall(r"`(\w+)`", m.group(1)) if m else []


def test_tables_sql_header_counts_and_names_every_table():
    head = _tables_sql().split("\n\n", 1)[0]
    tables = _tables()
    n = int(re.match(r"-- (\d+) tables\.", head).group(1))
    assert n == len(tables)
    listed = set(re.findall(r"\b(\w+)\b", "\n".join(head.splitlines()[1:4])))
    assert set(tables) <= listed, sorted(set(tables) - listed)


def test_records_table_lists_exactly_the_schema_tables():
    rows = set(_records_rows())
    tables = set(_tables())
    assert rows == tables, {"not in records.md": sorted(tables - rows), "not a table": sorted(rows - tables)}


def test_records_types_match_the_enums():
    rows = _records_rows()
    assert _types_in(rows["activity"]) == _enum("activity")
    assert _types_in(rows["watcher"]) == _enum("watcher")
    assert _types_in(rows["name"]) == _enum("name")


def test_states_activity_types_match_the_enum():
    doc = _doc("states.md")
    para = doc.split("## Activity types", 1)[1].split("\n## ", 1)[0]
    assert re.findall(r"`(\w+)`", para.split("`name` is", 1)[0]) == _enum("activity")
    watch = para.split("A watcher is", 1)[1].split(".", 1)[0]
    assert re.findall(r"`(\w+)`", watch) == _enum("watcher")
    assert f'A["activity {" ".join(_enum("activity"))}"]' in doc
    assert f'N["name {" ".join(_enum("name"))}"]' in doc


def test_every_routine_the_docs_name_exists():
    have = _routines()
    for name in ("records.md", "states.md", "commands.md"):
        named = set(re.findall(r"\b(mill_[a-z0-9_]+)\b", _doc(name))) - NOT_ROUTINES
        assert not named - have, (name, sorted(named - have))


def test_states_todo_diagram_has_every_edge():
    doc = _doc("states.md")
    section = doc.split("Todo lifecycle", 1)[1].split("sequenceDiagram", 1)[0]
    diagram = "\n".join(block.split("```", 1)[0] for block in section.split("```mermaid")[1:])
    edges = set(re.findall(r"(\[\*\]|\w+) --> (\[\*\]|\w+)", diagram))
    want = {
        ("parked", "open"), ("open", "claimed"), ("claimed", "claimed"), ("claimed", "open"),
        ("claimed", "shipped"), ("shipped", "done"), ("done", "shipped"), ("shipped", "claimed"),
        ("live", "retired"), ("retired", "live"),
    }
    assert want <= edges, sorted(want - edges)


def test_records_mail_to_snapshot_names_the_backfill():
    doc = _doc("records.md")
    assert "late joiners miss old mail" not in doc
    assert "mill_mail_to_node_put" in doc


def test_f139_row_points_at_commands_md():
    """M3 pin: F139's evidence path stays on commands.md, not verbs.md."""
    matrix = (ROOT / "docs" / "security" / "REGRESSION-MATRIX.md").read_text(encoding="utf-8")
    row = next(ln for ln in matrix.splitlines() if ln.startswith("| F139 "))
    assert "docs/protocol/commands.md" in row
    assert "verbs.md" not in row


def test_commands_md_table_headers_say_command_not_verb():
    """M4 pin: every command table header is '| command |', never '| verb |'."""
    doc = _doc("commands.md")
    headers = [ln for ln in doc.splitlines() if ln.startswith("| ") and " intent " in ln and " CALL " in ln]
    assert headers, "commands.md has no command/intent/CALL tables"
    assert all(ln.startswith("| command |") for ln in headers), headers
    assert "| verb |" not in doc
