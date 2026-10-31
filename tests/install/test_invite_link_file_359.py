"""mill invite writes a minted link to an owner-only file, never stdout by default (#359).

Regression row F54 (invite-link-file).
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_coord.__main__ import _build_parser, _invite_cmd, main

WALL = "https://203.0.113.10"
SECRET = "".join(("Zq7", "SeatSecret", "Value42"))  # assembled so tip stays clean under F206


def _args(**kw):
    base = dict(owner="", door="", rotate=False, mint=False, enable="", invite_list=False, revoke="",
                ttl="", ttl_for="", label="", seat="", join="", party="human", party_id="", lan_only=None,
                cmd="invite", seat_roster="", link_file="", print_link=False)
    base.update(kw)
    return SimpleNamespace(**base)


def _wall(monkeypatch, reply):
    monkeypatch.setattr("agent_coord.client.http.mill_http_call", lambda body: json.loads(json.dumps(reply)))
    monkeypatch.setattr("agent_coord.client.http.mill_url", lambda: WALL)
    monkeypatch.setattr("agent_coord.client.tokens.resolve_desk_owner", lambda _i="": "DESK_admin")


def _mint_envelope():
    # The shape the wall answers today: the secret sits under result.
    return {"id": "r1", "ok": True, "mill": "t", "sync": [], "result": {
        "ok": True, "key_id": "000cd353", "token": SECRET, "label": "repro",
        "ttl_seconds": 3600, "invite_path": "/?invite=" + SECRET, "status": "pending"}}


def _seat_envelope():
    return {"id": "r2", "ok": True, "mill": "t", "sync": [], "result": {
        "ok": True, "desk": "bot3", "seat": SECRET, "status": "ready",
        "invite_url": f"{WALL}/welcome?desk=bot3&seat={SECRET}"}}


def _json_block(out: str) -> dict:
    return json.loads(out[: out.rindex("}") + 1])


def _file_of(row: dict) -> Path:
    return Path(os.path.expanduser(row["result"]["link_file"]))


def test_mint_envelope_keeps_the_token_off_stdout(monkeypatch, capsys):
    _wall(monkeypatch, _mint_envelope())
    rc = _invite_cmd(_args(mint=True, label="repro"))
    out = capsys.readouterr().out
    assert rc == 0
    assert SECRET not in out and "invite=" not in out
    row = _json_block(out)
    assert "token" not in row["result"] and "invite_path" not in row["result"]
    assert "mill invite --enable 000cd353" in out  # was "--enable None"
    f = _file_of(row)
    assert f.read_text(encoding="utf-8").strip() == f"{WALL}/?invite={SECRET}"
    if os.name != "nt":
        assert stat.S_IMODE(f.stat().st_mode) == 0o600
        assert stat.S_IMODE(f.parent.stat().st_mode) == 0o700


def test_seat_envelope_writes_the_welcome_link(monkeypatch, capsys):
    _wall(monkeypatch, _seat_envelope())
    rc = _invite_cmd(_args(seat="bot3"))
    out = capsys.readouterr().out
    assert rc == 0 and SECRET not in out
    row = _json_block(out)
    assert row["result"]["desk"] == "bot3" and "seat" not in row["result"]
    f = _file_of(row)
    assert f.name.startswith("bot3-") and f.suffix == ".link"
    assert f.read_text(encoding="utf-8").strip() == f"{WALL}/welcome?desk=bot3&seat={SECRET}"


def test_print_link_is_the_explicit_stdout_form(monkeypatch, capsys, tmp_path):
    _wall(monkeypatch, _seat_envelope())
    rc = _invite_cmd(_args(seat="bot3", print_link=True))
    out = capsys.readouterr().out
    assert rc == 0
    assert out.strip().splitlines()[-1] == f"{WALL}/welcome?desk=bot3&seat={SECRET}"
    row = _json_block(out)
    assert "link_file" not in row["result"] and "seat" not in row["result"]
    assert not (Path(os.environ["AGENT_COORD_MILL_HOME"]) / "invites").exists()


def test_link_file_path_is_used_and_never_overwritten(monkeypatch, capsys, tmp_path):
    target = tmp_path / "bot3.link"
    _wall(monkeypatch, _seat_envelope())
    assert _invite_cmd(_args(seat="bot3", link_file=str(target))) == 0
    capsys.readouterr()
    assert target.read_text(encoding="utf-8").strip().endswith(SECRET)
    if os.name != "nt":
        assert stat.S_IMODE(target.stat().st_mode) == 0o600
    target.write_text("keep me\n", encoding="utf-8")
    rc = _invite_cmd(_args(seat="bot3", link_file=str(target)))
    cap = capsys.readouterr()
    assert rc == 1
    assert SECRET not in cap.out and SECRET not in cap.err
    assert "--print-link" in cap.err and "--link-file" in cap.err
    assert target.read_text(encoding="utf-8") == "keep me\n"


def test_flat_row_from_an_older_wall_is_handled(monkeypatch, capsys):
    _wall(monkeypatch, {"ok": True, "key_id": "abc123", "token": SECRET,
                        "invite_path": "/?invite=" + SECRET, "status": "pending"})
    assert _invite_cmd(_args(mint=True)) == 0
    out = capsys.readouterr().out
    assert SECRET not in out and "mill invite --enable abc123" in out
    row = _json_block(out)
    assert Path(os.path.expanduser(row["link_file"])).read_text(encoding="utf-8").strip().endswith(SECRET)


def test_a_list_writes_no_file(monkeypatch, capsys):
    _wall(monkeypatch, {"id": "r3", "ok": True, "result": {"ok": True, "keys": [{"key_id": "k1", "status": "revoked"}]}})
    assert _invite_cmd(_args(invite_list=True)) == 0
    out = capsys.readouterr().out
    assert _json_block(out)["result"]["keys"][0]["key_id"] == "k1"
    assert not (Path(os.environ["AGENT_COORD_MILL_HOME"]) / "invites").exists()


def test_a_refusal_writes_no_file_and_exits_1(monkeypatch, capsys):
    _wall(monkeypatch, {"id": "r4", "ok": False, "error": "invite-seat: trust too low"})
    assert _invite_cmd(_args(seat="bot3")) == 1
    assert not (Path(os.environ["AGENT_COORD_MILL_HOME"]) / "invites").exists()


def test_parser_and_help(capsys):
    a = _build_parser().parse_args(["invite", "--seat", "bot3", "--link-file", "x.link", "--print-link"])
    assert a.link_file == "x.link" and a.print_link is True
    with pytest.raises(SystemExit):
        main(["invite", "--help"])
    out = capsys.readouterr().out
    assert "--link-file" in out and "--print-link" in out
