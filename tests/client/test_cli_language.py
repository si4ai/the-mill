"""0.7.x CLI language: `mill <action> <type> <name>` maps onto the wall RPC commands."""
from __future__ import annotations

import pytest

from agent_coord.__main__ import _build_parser
from agent_coord.client import outbound
from agent_coord.client.language import translate
from agent_coord.const import CONST_OFFICE
from agent_coord.helpers.errors import CoordError


@pytest.fixture()
def body(monkeypatch, tmp_path):
    import agent_coord.client.tokens as tokens

    monkeypatch.setattr(tokens, "resolve_desk_owner", lambda x="": "me")
    f = tmp_path / "b.txt"
    f.write_text("hi", encoding="utf-8")
    p = _build_parser()

    def run(cmd: str, ask=None) -> dict:
        args = translate(p.parse_args(cmd.replace("BODY", str(f)).split()), ask=ask)
        out = outbound.body_from_args(args)
        out["_batch"] = list(getattr(args, "batch_desks", None) or [])
        return out

    return run


def test_create_roster_and_label(body):
    assert body("create roster night --yes")["verb"] == "roster"
    assert body("create label urgent --yes")["verb"] == "label"
    assert body("create roster night", ask=lambda q: "y")["confirm"] == "night"


def test_create_without_tty_or_yes_refuses(body):
    with pytest.raises(CoordError, match="--yes"):
        body("create roster night")


def test_add_remove_roster(body):
    b = body("add roster night d1,d2")
    assert b["verb"] == "member-add" and b["group"] == "night" and b["_batch"] == ["d1", "d2"]
    assert body("remove roster night --yes")["verb"] == "member-remove"


def test_label_unlabel_watch_unwatch(body):
    assert body("label todo 4 bug")["verb"] == "label-add"
    assert body("unlabel todo 4 bug")["verb"] == "label-remove"
    w = body("watch todo 3")
    assert (w["verb"], w["type"], w["id"]) == ("add", "todo", 3) and "who" not in w
    u = body("unwatch todo 3")
    assert (u["verb"], u["type"], u["id"]) == ("remove", "todo", 3)


@pytest.mark.parametrize("cmd", ["watch room build-room", "unwatch room build-room", "add room r d1"])
def test_room_membership_is_a_plain_gap(body, cmd):
    with pytest.raises(CoordError, match="not yet"):
        body(cmd)


def test_send_roster_and_desk(body):
    # The word rides along so the wall checks it against the name's type (#274).
    assert body("send roster builders --body-file BODY")["mail_tos"] == [{"deskId": "builders", "kind": "roster"}]
    assert body("send desk d1 roster b --body-file BODY")["mail_tos"] == [
        {"deskId": "d1", "kind": "desk"},
        {"deskId": "b", "kind": "roster"},
    ]
    with pytest.raises(CoordError):
        body("send --body-file BODY")


def test_hold_drop_take_no_roster(body):
    assert body("hold build") == {**body("hold build"), "project": CONST_OFFICE, "resource": "build"}
    assert body("drop build")["project"] == CONST_OFFICE
    assert body("hold --peek").get("peek") is True


def test_rename_retire_retype(body):
    assert body("rename roster a b", ask=lambda q: "b")["new"] == "b"
    with pytest.raises(CoordError, match="did not match"):
        body("retire roster a", ask=lambda q: "x")
    assert body("retire roster a --yes")["confirm"] == "a"


def test_delete_retype(body):
    """Card 879: mill delete roster|label|tree retypes NAME like retire."""
    with pytest.raises(CoordError, match="did not match"):
        body("delete roster a", ask=lambda q: "x")
    assert body("delete roster a --yes")["confirm"] == "a"
    assert body("delete label lab --yes")["confirm"] == "lab"
    assert body("delete tree plan --yes")["confirm"] == "plan"


def test_reset_seat(body):
    assert body("reset seat d1 --yes")["desk"] == "d1"
    with pytest.raises(CoordError):
        body("reset --yes")


def test_join_usage_is_the_link_file(capsys):
    with pytest.raises(SystemExit):
        _build_parser().parse_args(["join", "--help"])
    assert "usage: mill join --link-file PATH" in capsys.readouterr().out


def test_connect_without_roster_uses_office(monkeypatch):
    monkeypatch.setattr("agent_coord.client.tokens.read_session_token", lambda who: "seat-" + who)  # #281
    import agent_coord.__main__ as m
    import agent_coord.client.http as http

    seen = {}
    monkeypatch.setattr(http, "mill_here_over_http", lambda a: seen.setdefault("p", a.project) and 0)
    monkeypatch.setattr(m, "mill_here_over_http", lambda a: seen.setdefault("p", a.project) and 0, raising=False)
    monkeypatch.setattr("agent_coord.client.offices.mill_url", lambda: "https://wall.invalid", raising=False)
    monkeypatch.setattr(m, "mill_url", lambda: "https://wall.invalid", raising=False)
    m.main(["connect", "d1"])
    assert seen.get("p") == CONST_OFFICE
    seen.clear()
    m.main(["connect", "night", "d1"])
    assert seen.get("p") == "night"


def test_connect_wait_is_connect_foreground(monkeypatch):
    monkeypatch.setattr("agent_coord.client.tokens.read_session_token", lambda who: "seat-" + who)  # #281
    import agent_coord.__main__ as m
    import agent_coord.client.http as http

    seen = {}

    def fake(a):
        seen.update(cmd=a.cmd, fg=getattr(a, "foreground", False), p=a.project, d=a.desk)
        return 0

    monkeypatch.setattr(http, "mill_here_over_http", fake)
    monkeypatch.setattr(m, "mill_url", lambda: "https://wall.invalid", raising=False)
    m.main(["connect-wait", "d1"])
    assert seen == {"cmd": "connect", "fg": True, "p": CONST_OFFICE, "d": "d1"}
    with pytest.raises(SystemExit):
        _build_parser().parse_args(["connect", "d1", "--foreground"])


def test_send_room_replaces_name():
    p = _build_parser()
    assert p.parse_args(["send", "desk", "a", "--body-file", "b", "--room", "standup"]).name == "standup"
    with pytest.raises(SystemExit):
        p.parse_args(["send", "desk", "a", "--body-file", "b", "--name", "standup"])


def test_join_without_office_uses_link_host(monkeypatch, tmp_path, capsys):
    import agent_coord.__main__ as m
    import agent_coord.client.offices as off

    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))
    seen = {}

    def fake(link, office, **kw):
        seen["office"] = office
        return {"ok": True, "desk": "d9", "next": "next: old"}

    monkeypatch.setattr(off, "join_office", fake)
    monkeypatch.setattr(off, "write_global_active", lambda name, **kw: seen.setdefault("active", name))
    off.bind_cli_office("")
    lf = tmp_path.parent / "d9.link"
    lf.write_text("https://203.0.113.7/welcome?desk=d9&seat=S&project=cold-test&pem=x\n", encoding="utf-8")
    rc = m.main(["join", "--link-file", str(lf)])
    out = capsys.readouterr().out
    assert rc == 0
    assert seen == {"office": "203.0.113.7", "active": "203.0.113.7"}
    assert "next: bash -c 'mill connect d9 >/dev/null 2>&1 & trap \"kill $!\" EXIT; mill inbox'" in out


def test_alias_from_link():
    from agent_coord.client.offices import alias_from_link

    assert alias_from_link("https://Wall.Example:8443/welcome?desk=a") == "wall.example"
    assert alias_from_link("not a link") == ""


def test_every_command_takes_yes():
    import argparse

    p = _build_parser()
    sp = [a for a in p._actions if isinstance(a, argparse._SubParsersAction)][0]
    missing = []
    for name, child in sp.choices.items():
        subs = [a for a in child._actions if isinstance(a, argparse._SubParsersAction)]
        kids = subs[0].choices.items() if subs else [(None, child)]
        for kname, k in kids:
            if "--yes" not in k._option_string_actions:
                missing.append(f"{name} {kname or ''}".strip())
    assert missing == []


def test_plain_todo_reads_each_of_my_rosters(monkeypatch):
    from types import SimpleNamespace

    import agent_coord.client.http as http

    calls = []

    def fake(b):
        calls.append((b["verb"], b.get("project")))
        if b["verb"] == "member":
            return {"ok": True, "result": [{"slot": "Office"}, {"slot": "cold-test"}]}
        if b["verb"] == "project":
            return {"ok": True, "result": {"projects": ["Office", "cold-test", "the-mill"]}}
        if "rosters" in b:
            return {"ok": True, "result": {"cards": [{"project_id": r, "need_id": "n"} for r in b["rosters"]]}}
        return {"ok": True, "result": [{"project_id": b["project"], "need_id": "n"}]}

    monkeypatch.setattr(http, "mill_http_call", fake)
    a = SimpleNamespace(cmd="todo", project="", need="", all=False)
    got = http._todo_call(a, {"verb": "todo", "project": "the-mill", "owner": "me"})
    assert [r["project_id"] for r in got["result"]] == ["Office", "cold-test"]
    assert "--all" in got["note"]
    a.all = True
    got = http._todo_call(a, {"verb": "todo", "project": "the-mill", "owner": "me"})
    assert [r["project_id"] for r in got["result"]] == ["Office", "cold-test", "the-mill"]
    calls.clear()
    a.all, a.project = False, "the-mill"
    http._todo_call(a, {"verb": "todo", "project": "the-mill", "owner": "me"})
    assert calls == [("todo", "the-mill")]


def test_connect_prints_a_start_line(monkeypatch, capsys):
    monkeypatch.setattr("agent_coord.client.tokens.read_session_token", lambda who: "seat-" + who)  # #281
    import agent_coord.__main__ as m
    import agent_coord.client.http as http

    monkeypatch.setattr(http, "mill_here_over_http", lambda a: 0)
    monkeypatch.setattr(m, "mill_url", lambda: "https://wall.invalid", raising=False)
    m.main(["connect", "d1"])
    assert "mill connect: d1 on roster Office" in capsys.readouterr().err


@pytest.mark.parametrize("cmd", ["watch todo 0", "unwatch score 0", "watch hold 0", "unwatch doing -1"])
def test_watch_id_must_be_positive_number(body, cmd):
    with pytest.raises(CoordError, match="a number above 0"):
        body(cmd)


def test_watch_help_names_id_only():
    p = _build_parser()
    for command in ("watch", "unwatch"):
        usage = p._subparsers._group_actions[0].choices[command].format_usage()
        assert "ID|NAME" not in usage and " ID" in usage


def test_restore_and_purge_retype(body):
    """Card 879: mill restore / mill purge retype NAME like delete."""
    with pytest.raises(CoordError):
        body("restore label a", ask=lambda q: "x")
    assert body("restore label a --yes")["confirm"] == "a"
    assert body("purge tree plan --yes")["confirm"] == "plan"
