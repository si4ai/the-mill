"""split_script must keep every CREATE FUNCTION/PROCEDURE from DELIMITER files."""
from pathlib import Path
import re
from agent_coord.install.migrate import split_script, sql_dir


def _create_names(blob: str) -> list[str]:
    return re.findall(r"CREATE\s+(?:FUNCTION|PROCEDURE)\s+(\w+)", blob, flags=re.I)


def _split_create_names(blob: str) -> list[str]:
    out = []
    for stmt in split_script(blob):
        m = re.search(r"CREATE\s+(?:FUNCTION|PROCEDURE)\s+(\w+)", stmt, flags=re.I)
        if m:
            out.append(m.group(1))
    return out


def test_split_script_preserves_fn_name_creates():
    blob = (sql_dir() / "fn_name.sql").read_text(encoding="utf-8-sig")
    assert _create_names(blob) == [
        "MILL_NAME_GET",
        "MILL_NAME_PUT",
    ]
    assert _split_create_names(blob) == _create_names(blob)


def test_split_script_preserves_all_sql_creates():
    missing = {}
    for path in sql_dir().glob("*.sql"):
        if path.name in ("wipe.sql", "tables.sql"):
            continue
        blob = path.read_text(encoding="utf-8-sig")
        want = _create_names(blob)
        if not want:
            continue
        got = _split_create_names(blob)
        if got != want:
            missing[path.name] = {"want": want, "got": got}
    assert missing == {}
