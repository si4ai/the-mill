"""F23 doc row; the callers no longer scan the hold table, catalog or seat list."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RPC = ROOT / "agent_coord" / "server" / "api" / "mill" / "rpc.py"


def _body(src: str, name: str) -> str:
    start = src.index("def %s(" % name)
    end = src.find("\ndef ", start + 10)
    return src[start:] if end < 0 else src[start:end]


def test_regression_row_f23_documented():
    doc = (ROOT / "docs" / "protocol" / "commands.md").read_text(encoding="utf-8")
    assert "Regression row F23 (direct-lookups)" in doc


def test_callers_use_the_narrow_reads():
    src = RPC.read_text(encoding="utf-8")
    assert "rec_join.select(" not in _body(src, "_offline_dests")
    assert "rec_join.seen(" in _body(src, "_offline_dests")
    assert "rec_name.select(" not in _body(src, "_live_projects")
    assert "rec_name.live_roster(" in _body(src, "_require_live_project")
    assert "rec_hold.find(" in _body(src, "_hold_list")
    hold = (ROOT / "agent_coord" / "server" / "records" / "hold.py").read_text(encoding="utf-8")
    for fn in ("own", "peek", "drop"):
        assert "select(cn" not in _body(hold, fn), fn
