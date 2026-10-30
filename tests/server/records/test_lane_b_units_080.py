"""0.8.0 lane B units (no MySQL): FK/CHECK refusal text and the trust-set rollback.

- fk_refusal maps the kind-checked and seat FKs (1452) and CHECKs (3819) to one plain line
  without the book name.
- mill trust set writes config.toml, then re-creates b_trust(); when that fails the file goes
  back, so config and the function never disagree (schema-design.md section 9).
"""
from __future__ import annotations

import pytest

from agent_coord.server.records.db import fk_refusal


class _Err(Exception):
    def __init__(self, errno: int, msg: str) -> None:
        super().__init__(msg)
        self.errno = errno
        self.msg = msg


def _fk(constraint: str) -> _Err:
    return _Err(1452, "Cannot add or update a child row: a foreign key constraint fails "
                f"(`mill_book_x`.`t`, CONSTRAINT `{constraint}` FOREIGN KEY (`c`) REFERENCES `seat` (`desk_id`))")


@pytest.mark.parametrize("constraint, what", [
    ("fk_activity_desk", "that desk has no seat"),
    ("fk_todo_assigned", "that desk has no seat"),
    ("fk_todo_roster", "that id is not a roster"),
    ("fk_member_name", "that id is not a roster"),
    ("fk_label_name", "that id is not a label"),
    ("fk_tree_read_tree", "that id is not a plan"),
    ("fk_hold_res", "that id is not a resource"),
])
def test_fk_refusal_names_what_was_wrong_not_the_book(constraint, what):
    line = fk_refusal(_fk(constraint))
    assert line and what in line and constraint in line
    assert "mill_book_x" not in line and "nothing changed" in line


def test_check_refusal_names_the_check():
    line = fk_refusal(_Err(3819, "Check constraint 'chk_doing_evidence' is violated."))
    assert line == "refused: chk_doing_evidence does not hold; nothing changed"


def test_other_errors_are_not_mapped():
    assert fk_refusal(_Err(1062, "Duplicate entry")) is None
    assert fk_refusal(None) is None


def test_trust_set_puts_the_config_back_when_b_trust_fails(tmp_path, monkeypatch):
    from agent_coord.server.api.mill import rpc
    from agent_coord.server.records import trust_fn

    cfg = tmp_path / "config.toml"
    cfg.write_text('[mill]\ntrust = "high"\n', encoding="utf-8")
    before = cfg.read_bytes()
    monkeypatch.setattr("agent_coord.config.config_path", lambda: cfg)
    monkeypatch.setattr("agent_coord.server.admin.guard.require_admin", lambda cn, desk: None)

    def boom(cn, level=None):
        raise RuntimeError("b_trust: cannot create")

    monkeypatch.setattr(trust_fn, "init_trust_fn", boom)
    book = type("B", (), {"_cn": object()})()
    with pytest.raises(RuntimeError, match="b_trust"):
        rpc._h_trust(book, {"level": "limited"}, "Office", "adm")
    assert cfg.read_bytes() == before


def test_trust_set_calls_init_trust_fn_after_the_config(tmp_path, monkeypatch):
    from agent_coord.server.api.mill import rpc
    from agent_coord.server.records import trust_fn

    cfg = tmp_path / "config.toml"
    cfg.write_text('[mill]\ntrust = "high"\n', encoding="utf-8")
    monkeypatch.setattr("agent_coord.config.config_path", lambda: cfg)
    monkeypatch.setattr("agent_coord.server.admin.guard.require_admin", lambda cn, desk: None)
    seen: list[tuple[str, str]] = []

    def record(cn, level=None):
        seen.append((level, cfg.read_text(encoding="utf-8")))
        return level

    monkeypatch.setattr(trust_fn, "init_trust_fn", record)
    book = type("B", (), {"_cn": object()})()
    assert rpc._h_trust(book, {"level": "limited"}, "Office", "adm") == {"ok": True, "trust": "limited"}
    assert seen and seen[0][0] == "limited" and "limited" in seen[0][1]
