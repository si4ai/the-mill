"""Flag cleanup (#254): removed flags exit 2, folds and renames parse.

One row per removed or changed param. Alpha: no aliases.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_coord.__main__ import _build_parser, main
from agent_coord.client import outbound
from agent_coord.helpers.errors import CoordError


def _exit2(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as ei:
        _build_parser().parse_args(argv)
    assert int(ei.value.code or 0) == 2


@pytest.mark.parametrize(
    "argv",
    [
        ["connect", "the-mill", "builder", "--host", "192.0.2.5"],
        ["connect", "the-mill", "builder", "--spawn", "echo"],
        ["send", "--to-desk", "a", "--body-file", "b", "--human-required"],
        ["send", "--to-desk", "a", "--body-file", "b", "--parent-type", "todo"],
        ["send", "--to-desk", "a", "--body-file", "b", "--parent-id", "3"],
        ["reply", "1", "--body-file", "b", "--human-required"],
        ["todo", "the-mill", "n", "--n", "3"],
        ["todo", "the-mill", "n", "--of", "9"],
        ["todo", "the-mill", "n", "--pct", "50"],
        ["inbox", "--after", "5"],
        ["dashboard"],
        ["status", "the-mill"],
        ["member", "the-mill"],
        ["member-add", "g"],
        ["member-remove", "g"],
        ["add", "roster", "g", "--role"],
        ["remove", "roster", "g", "--role"],
        ["connect", "d1", "--foreground"],
        ["wait"],
        ["hold", "the-mill", "build"],
        ["send", "--to-desk", "a", "--body-file", "b", "--affil" "iation", "x"],
        ["reply", "1", "--body-file", "b", "--affil" "iation", "x"],
        ["label-add", "todo", "1", "lbl"],
        ["label", "todo", "1", "lbl", "the-mill"],
        ["unlabel", "todo", "1", "lbl", "the-mill"],
        ["watcher", "todo", "1"],
        ["watch", "todo", "1", "the-mill"],
    ],
    ids=lambda a: " ".join(a)[:60],
)
def test_254_removed_params_exit_2(argv: list[str]) -> None:
    _exit2(argv)


def test_254_kept_and_renamed_parse() -> None:
    p = _build_parser()
    # 0.7.0: one roster namespace; member-add/remove have no --role.
    assert "role" not in vars(p.parse_args(["add", "roster", "Admin"]))
    assert "role" not in vars(p.parse_args(["remove", "roster", "g"]))
    assert p.parse_args(["connect-wait", "d1"]).cmd == "connect-wait"
    peek = p.parse_args(["hold", "--peek"])
    assert peek.peek is True and peek.resource == ""
    assert p.parse_args(["hold", "a.md"]).resource == "a.md"
    # create todo and unpark keep --parent-type / --parent-id.
    ct = p.parse_args(["create", "todo", "p", "n", "--parent-type", "todo", "--parent-id", "4"])
    assert ct.parent_type == "todo" and ct.parent_id == 4
    # Card 1125: todo ROSTER NEED takes --eta and --started for the card's own fields.
    n = p.parse_args(["todo", "p", "n", "--eta", "2h", "--started"])
    assert n.eta == "2h" and n.started is True
    # todo --fixtures stays for tools, hidden from help.
    assert p.parse_args(["todo", "p", "--fixtures"]).fixtures is True


def test_254_fixtures_hidden_from_help(capsys) -> None:
    with pytest.raises(SystemExit):
        main(["todo", "-h"])
    assert "--fixtures" not in capsys.readouterr().out


def _hold_args(**kw):
    base = dict(cmd="hold", project="the-mill", resource="", peek=False, doing="")
    base.update(kw)
    return SimpleNamespace(**base)


def test_254_hold_without_resource_is_the_list() -> None:
    # #326: bare hold lists every lock, like --peek alone.
    outbound._guard_args("hold", "hold", _hold_args())
    outbound._guard_args("hold", "hold", _hold_args(resource="   "))
    with pytest.raises(CoordError, match="--doing needs a resource"):
        outbound._guard_args("hold", "hold", _hold_args(doing="x"))
    with pytest.raises(CoordError, match="--doing needs a resource"):
        outbound._guard_args("hold", "hold", _hold_args(peek=True, doing="x"))
    outbound._guard_args("hold", "hold", _hold_args(peek=True))
    outbound._guard_args("hold", "hold", _hold_args(resource="a.md"))


def test_254_status_is_not_a_command() -> None:
    from agent_coord.server.api.mill.rpc import HANDLERS

    assert "status" not in outbound.COMMANDS
    assert "status" not in outbound.WALL
    assert "status" not in HANDLERS
    assert "status" not in outbound._PROJECT_GUARD


def test_254_body_carries_no_removed_keys(monkeypatch) -> None:
    monkeypatch.setattr("agent_coord.client.tokens.resolve_desk_owner", lambda _x: "builder")
    assert "kind" not in outbound._STR
    assert "roster" in outbound._STR
    args = SimpleNamespace(cmd="todo", project="p", need="n", eta="2h", started=False, done_when=None)
    body = outbound.body_from_args(args)
    assert body["eta"] == "2h"
    for key in ("n", "of", "pct"):
        assert key not in body


@pytest.mark.parametrize("word", ["192.0.2.5", "wall.example.com", "192.0.2.1:8443"])
def test_254_connect_refuses_host_shaped_word(word, capsys) -> None:
    from agent_coord.client.offices import looks_like_host

    if not looks_like_host(word):
        pytest.skip("not host-shaped by the shared rule")
    assert main(["connect", word, "builder"]) == 2
    assert "--office" in capsys.readouterr().err
    assert main(["connect", "the-mill", word]) == 2


def test_254_roster_kept_on_send_and_reply() -> None:
    p = _build_parser()
    s = p.parse_args(["send", "--to-desk", "a", "--body-file", "b", "--roster", "builder"])
    assert s.roster == "builder" and "human_required" not in vars(s)
    r = p.parse_args(["reply", "1", "--body-file", "b", "--roster", "the-mill"])
    assert r.roster == "the-mill" and "human_required" not in vars(r)
    assert p.parse_args(["send", "--to-desk", "a", "--body-file", "b"]).roster == ""
    _exit2(["send", "--to-desk", "a", "--body-file", "b", "--roster"])


def test_254_roster_rides_the_body(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("agent_coord.client.tokens.resolve_desk_owner", lambda _x: "builder")
    f = tmp_path / "b.txt"
    f.write_text("hi", encoding="utf-8")
    args = SimpleNamespace(cmd="reply", mail_id=3, body_file=str(f), roster="builder",
                           to_desk=None, add_to=[], remove_to=[], human_required=True)
    body = outbound.body_from_args(args)
    assert body["roster"] == "builder"
    assert "human_required" not in body
