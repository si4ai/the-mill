"""Card 1241: delete empties the name, purge cannot hard-delete it. No database."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SQL = (ROOT / "agent_coord" / "server" / "sql" / "sp_beta_name.sql").read_text(encoding="utf-8")
FN = (ROOT / "agent_coord" / "server" / "sql" / "fn_name.sql").read_text(encoding="utf-8")
RPC = (ROOT / "agent_coord" / "server" / "api" / "mill" / "rpc.py").read_text(encoding="utf-8")


def _proc(text: str, name: str) -> str:
    start = text.index("CREATE PROCEDURE %s" % name)
    end = text.index("END //", start)
    return text[start:end]


def test_trash_empties_relationships_and_keeps_the_938_gate() -> None:
    body = _proc(SQL, "sp_name_trash")
    assert "Card 938" in body
    assert body.index("sole remaining member or Admin") < body.index("DELETE FROM member")
    assert body.index("DELETE FROM member") < body.index("UPDATE name SET trashed")
    assert "DELETE FROM human_member WHERE name_id = v_id" in body
    assert "DELETE FROM label WHERE name_id = v_id" in body
    assert "focus_label_id = NULL" in body
    assert "DELETE FROM tree_read WHERE tree_id = v_id" in body
    assert "DELETE FROM tree WHERE name_id = v_id" in body
    assert "mill retire DESK DESK --yes" in body
    assert "a res name stays" in body
    assert "mill restore NAME" in body
    assert "mill purge" not in body


def test_purge_procedure_signals_and_does_not_delete() -> None:
    body = _proc(SQL, "sp_name_purge")
    assert "purge is removed" in body
    assert "DELETE FROM" not in body
    assert "mill_allow_name_hard_delete" not in body


def test_name_get_refuses_a_trashed_name() -> None:
    start = FN.index("CREATE FUNCTION MILL_NAME_GET")
    body = FN[start:FN.index("END //", start)]
    assert "trashed" in body
    assert "name trashed: mill restore NAME" in body


def test_roster_who_is_refused_on_a_watcher() -> None:
    assert "WHO is a roster; name a desk" in RPC


def test_retire_drops_a_desk_watcher_rows() -> None:
    body = _proc(SQL, "sp_name_retire")
    assert "DELETE FROM watcher WHERE desk_id = v_id" in body
