"""No printed output carries a minted secret unless --print-link (#607). Regression row F64 (secret-out).

#359 stripped a fixed list of key names, so the seat reply's join_argv
(mill join <welcome link>) still printed the seat secret. The printed reply
now withholds the secret wherever it sits; the link goes to the owner-only
file, or to stdout once with --print-link. mill init and mill install server
mint an invite key and a host seat; their links go only to the owner-only file.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_coord.__main__ import _build_parser, _invite_cmd, main

WALL = "https://203.0.113.10"
SECRET = "".join(("Zq7", "SeatSecret", "Value607"))  # assembled so tip stays clean under F206
KEY = "".join(("Kx9", "InviteKey", "Value607"))
URL = f"{WALL}/welcome?desk=bot3&seat={SECRET}&project=ops&pem=LS0t"


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


def _seat_reply():
    # The 0.7.8 wall's seat reply: the secret also rides in join_argv.
    return {"id": "r", "ok": True, "mill": "t", "sync": [], "result": {
        "ok": True, "desk": "bot3", "seat": SECRET, "status": "ready", "project": "ops",
        "invite_url": URL, "ca": "-----BEGIN CERTIFICATE-----\nx\n-----END CERTIFICATE-----\n",
        "join_argv": ["mill", "join", URL],
        "later_field": {"cmd": f"mill join '{URL}'"}}}


def _json_block(out: str) -> dict:
    return json.loads(out[: out.rindex("}") + 1])


def test_seat_reply_prints_no_secret_in_any_field(monkeypatch, capsys):
    _wall(monkeypatch, _seat_reply())
    assert _invite_cmd(_args(seat="bot3")) == 0
    cap = capsys.readouterr()
    assert SECRET not in cap.out and SECRET not in cap.err
    res = _json_block(cap.out)["result"]
    assert res["desk"] == "bot3" and res["link_file"]
    assert Path(os.path.expanduser(res["link_file"])).read_text(encoding="utf-8").strip() == URL


def test_print_link_prints_the_secret_once_on_its_own_line(monkeypatch, capsys):
    _wall(monkeypatch, _seat_reply())
    assert _invite_cmd(_args(seat="bot3", print_link=True)) == 0
    out = capsys.readouterr().out
    assert out.count(SECRET) == 1
    assert out.strip().splitlines()[-1] == URL


def test_mint_reply_with_the_key_in_a_new_field(monkeypatch, capsys):
    _wall(monkeypatch, {"id": "r", "ok": True, "result": {
        "ok": True, "key_id": "k607", "token": KEY, "invite_path": "/?invite=" + KEY,
        "note": f"share {WALL}/?invite={KEY}"}})
    assert _invite_cmd(_args(mint=True)) == 0
    out = capsys.readouterr().out
    assert KEY not in out and "mill invite --enable k607" in out


def _install_result():
    return {
        "ok": True,
        "invite": {"ok": True, "key_id": "k1", "token": KEY, "invite_path": "/?invite=" + KEY},
        "invite_link": f"{WALL}/?invite={KEY}",
        "seat_welcome": {"ok": True, "desk": "host", "seat": SECRET, "invite_url": URL,
                         "join_argv": ["mill", "join", URL]},
        "next": [f"Human Wall door: {WALL}/?invite={KEY}", f"Host desk welcome link: mill join --office <alias> {URL}"],
    }


def _run_init(monkeypatch, capsys, extra):
    monkeypatch.setattr("agent_coord.install.office.gather", lambda **kw: {})
    monkeypatch.setattr("agent_coord.install.office.init_office", lambda data, path=None: _install_result())
    rc = main(["init", "--yes", *extra])
    return rc, capsys.readouterr()


def test_init_prints_no_secret_and_writes_the_links(monkeypatch, capsys):
    rc, cap = _run_init(monkeypatch, capsys, [])
    assert rc == 0
    assert SECRET not in cap.out and KEY not in cap.out and SECRET not in cap.err
    row = _json_block(cap.out)
    text = Path(os.path.expanduser(row["link_file"])).read_text(encoding="utf-8")
    assert URL in text and f"{WALL}/?invite={KEY}" in text


def test_init_has_no_print_link(monkeypatch, capsys):
    # The host links stay in the owner-only file; there is no stdout form.
    with pytest.raises(SystemExit):
        _run_init(monkeypatch, capsys, ["--print-link"])
    assert SECRET not in capsys.readouterr().out


def test_install_server_prints_no_secret(monkeypatch, capsys):
    monkeypatch.setattr("agent_coord.install.write_role", lambda *a, **k: _install_result())
    rc = main(["install", "server"])
    cap = capsys.readouterr()
    assert rc == 0
    assert SECRET not in cap.out and KEY not in cap.out
    assert _json_block(cap.out)["link_file"]


def test_init_and_install_take_the_link_flags():
    p = _build_parser()
    for argv in (["init", "--link-file", "x.link"], ["install", "server", "--link-file", "x.link"]):
        assert p.parse_args(argv).link_file == "x.link"


@pytest.mark.parametrize("reply", [
    {"ok": True, "result": {"ok": True, "keys": [{"key_id": "k1", "status": "active"}]}},
    {"ok": False, "error": "invite-seat: trust too low"},
])
def test_nothing_minted_writes_no_file(monkeypatch, capsys, reply):
    _wall(monkeypatch, reply)
    _invite_cmd(_args(invite_list=True))
    capsys.readouterr()
    assert not (Path(os.environ["AGENT_COORD_MILL_HOME"]) / "invites").exists()
