"""0.7.0 roster: one roster name type, no role namespace, no old tag word."""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import pytest

from agent_coord.helpers.errors import CoordError

ROOT = Path(__file__).resolve().parents[2]
OLD = "affil" + "iat"
from agent_coord.server.api.mill.rpc import _require_live_project as _REAL_LIVE  # noqa: E402

# name_type.sql is the hand-run pre-0.5 script to the 0.6 shape; 0.7.0 ensure() migrates after it.
ALLOWED = {
    "agent_coord/server/sql/migrate_070_roster.sql",
    "agent_coord/install/migrate.py",
    "agent_coord/server/sql/name_type.sql",
}


def test_grep_gate_no_old_tag_word():
    out = subprocess.run(["git", "grep", "-il", OLD], cwd=ROOT, capture_output=True, text=True)
    hits = set(out.stdout.split()) - ALLOWED
    assert not hits, sorted(hits)


def test_migrate_py_names_old_word_only_in_the_split_string():
    src = (ROOT / "agent_coord/install/migrate.py").read_text(encoding="utf-8")
    lines = [ln for ln in src.splitlines() if OLD in ln.lower()]
    assert len(lines) <= 2, lines


def test_migration_drops_no_column():
    sql = (ROOT / "agent_coord/server/sql/migrate_070_roster.sql").read_text(encoding="utf-8").upper()
    assert "DROP COLUMN" not in sql
    assert "SAME-NAME PROJECT/ROLE" in sql


def _parser():
    from agent_coord.__main__ import _build_parser

    return _build_parser()


def _exit2(argv):
    with pytest.raises(SystemExit) as ei:
        _parser().parse_args(argv)
    assert ei.value.code == 2


def test_cli_roster_command_replaces_group_and_role():
    a = _parser().parse_args(["create", "roster", "east", "--yes"])
    assert (a.cmd, a.object, a.slug, a.yes) == ("create", "roster", "east", True)
    _exit2(["group", "east", "east", "--yes"])
    _exit2(["role", "east", "east", "--yes"])
    _exit2(["roster", "east", "east", "--yes"])


def test_cli_member_has_no_role_flag():
    _exit2(["add", "roster", "Admin", "--role"])
    _exit2(["remove", "roster", "Admin", "--role"])


def test_cli_former_role_works_as_roster():
    s = _parser().parse_args(["send", "--to-desk", "a", "--body-file", "b", "--roster", "validator"])
    assert s.roster == "validator"


def _patch_members(monkeypatch, names):
    from agent_coord.server.records import member as rec_member

    monkeypatch.setattr(rec_member, "select", lambda cn, slot, desk, kind: [{"slot": n} for n in names])


@pytest.mark.parametrize(
    "names, want",
    [
        ([], "Office"),
        (["Office"], "Office"),
        (["validator"], "validator"),  # a former role is the seat roster
        (["Office", "Admin"], "Admin"),  # Admin counts
        (["the-mill", "Admin"], "Office"),  # more than one: Office
        (["the-mill", "validator", "Office"], "Office"),
    ],
)
def test_seat_roster_default_sender(monkeypatch, names, want):
    from agent_coord.server.api.mill.rpc import _seat_roster

    _patch_members(monkeypatch, names)
    assert _seat_roster(object(), "d1") == want


def test_seat_roster_no_desk_is_office():
    from agent_coord.server.api.mill.rpc import _seat_roster

    assert _seat_roster(object(), "") == "Office"


def _patch_live(monkeypatch, live):
    from agent_coord.server.records import name as rec_name

    monkeypatch.setattr(rec_name, "get", lambda cn, n, kind: 7 if (n in live and kind == "roster") else None)
    monkeypatch.setattr(rec_name, "select", lambda cn, *a, **k: [{"type": "roster", "name": n} for n in live])
    # F23: the project check and roster list read rosters directly.
    monkeypatch.setattr(rec_name, "live_roster", lambda cn, n: n if n in live else None)
    monkeypatch.setattr(rec_name, "live_roster_names", lambda cn: sorted(live))


def test_check_roster_any_live_roster(monkeypatch):
    from agent_coord.server.api.mill.rpc import _check_roster

    _patch_live(monkeypatch, {"Office", "validator"})
    _check_roster(object(), "send", "validator")
    _check_roster(object(), "send", "")
    with pytest.raises(CoordError, match="send: no such roster ghost"):
        _check_roster(object(), "send", "ghost")
    with pytest.raises(CoordError, match="no such roster"):
        _check_roster(object(), "send", "x" * 65)


def test_seat_mint_roster(monkeypatch):
    from agent_coord.server.admin.seats import resolve_seat_roster
    from agent_coord.server.api.mill import rpc

    # tests/server/conftest.py stubs the live check; this test needs the real one.
    monkeypatch.setattr(rpc, "_require_live_project", _REAL_LIVE)

    _patch_live(monkeypatch, {"Office", "validator", "the-mill"})
    assert resolve_seat_roster(object(), "d1", "validator") == "validator"
    with pytest.raises(CoordError, match="Office is not a seat roster"):
        resolve_seat_roster(object(), "d1", "Office")
    with pytest.raises(CoordError, match="no such roster ghost"):
        resolve_seat_roster(object(), "d1", "ghost")
    _patch_members(monkeypatch, ["Office"])
    with pytest.raises(CoordError, match="roster required"):
        resolve_seat_roster(object(), "d1", "")


def test_no_session_roles_anywhere():
    out = subprocess.run(["git", "grep", "-l", "SESSION_ROLES", "--", "agent_coord"], cwd=ROOT,
                         capture_output=True, text=True)
    assert out.stdout.strip() == ""
