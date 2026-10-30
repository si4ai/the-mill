"""F24 doc row; the WS and HTTP command paths park the score instead of writing it."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_regression_row_f24_documented():
    doc = (ROOT / "docs" / "protocol" / "commands.md").read_text(encoding="utf-8")
    assert "Regression row F24 (reply-first)" in doc


def test_command_paths_enqueue_the_score():
    for rel in ("agent_coord/server/asgi.py", "agent_coord/server/middleware.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert "enqueue_command(" in src, rel
        assert "import note_command" not in src, rel


def test_call_uses_one_statement():
    src = (ROOT / "agent_coord" / "server" / "records" / "db.py").read_text(encoding="utf-8")
    body = src[src.index("def call(") : src.index("\ndef ", src.index("def call(") + 10)]
    assert "_run_proc(" in body and "callproc" not in body
