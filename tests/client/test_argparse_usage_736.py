"""card 736: a bad flag names the subcommand, an unknown command names mill help."""
from __future__ import annotations

import pytest

from agent_coord.__main__ import _build_parser
from agent_coord.client.language import translate
from agent_coord.helpers.errors import CoordError
from agent_coord.install.packver import package_version


def _stderr(argv: list[str], capsys) -> str:
    with pytest.raises(SystemExit) as ei:
        _build_parser().parse_args(argv)
    assert ei.value.code == 2
    return capsys.readouterr().err


def test_unknown_flag_uses_subcommand_usage(capsys) -> None:
    err = _stderr(["todo", "--bogus"], capsys)
    assert "mill todo: error: unrecognized arguments: --bogus" in err
    assert "usage: mill todo" in err
    assert "see: mill help todo" in err
    assert "usage: mill [-h]" not in err
    assert "choose from" not in err


def test_unknown_flag_after_office_still_names_the_subcommand(capsys) -> None:
    err = _stderr(["--office", "local", "todo", "--bogus"], capsys)
    assert "mill todo: error: unrecognized arguments: --bogus" in err
    assert "see: mill help todo" in err


def test_unknown_command_suggests_a_close_match(capsys) -> None:
    err = _stderr(["tod"], capsys)
    assert "unknown command 'tod'" in err
    assert "did you mean todo?" in err
    assert "mill help lists every command" in err
    assert "choose from" not in err


def test_unknown_command_with_no_match_skips_the_choice_list(capsys) -> None:
    err = _stderr(["frobnicate"], capsys)
    assert "unknown command 'frobnicate'" in err
    assert "mill help lists every command" in err
    assert "did you mean" not in err
    assert "choose from" not in err


def test_create_todo_slash_is_roster_and_need() -> None:
    ns = _build_parser().parse_args(["create", "todo", "the-mill/some-need", "--yes"])
    out = translate(ns)
    assert out.project == "the-mill"
    assert out.need == "some-need"


def test_create_todo_two_words_stay() -> None:
    ns = _build_parser().parse_args(["create", "todo", "the-mill", "some-need", "--yes"])
    out = translate(ns)
    assert out.project == "the-mill"
    assert out.need == "some-need"


def test_create_todo_one_word_names_two_words() -> None:
    ns = _build_parser().parse_args(["create", "todo", "the-mill", "--yes"])
    with pytest.raises(CoordError, match="give roster and need as two words"):
        translate(ns)


def test_unknown_flag_on_create_todo_names_create(capsys) -> None:
    err = _stderr(["create", "todo", "the-mill", "some-need", "--bogus"], capsys)
    assert "mill create todo: error: unrecognized arguments: --bogus" in err
    assert "see: mill help create" in err


def test_dispatch_ws_unknown_names_the_mismatch() -> None:
    from agent_coord.server.api.mill.rpc import dispatch_ws

    with pytest.raises(CoordError, match="client 0.0.0 != wall"):
        dispatch_ws(None, "desk", "frobnicate", client_mill="0.0.0")


def test_wall_unknown_command_names_help() -> None:
    from agent_coord.server.api.mill.rpc import unknown_command_message

    assert unknown_command_message("frobnicate") == (
        "unknown command frobnicate; mill help lists every command"
    )


def test_wall_unknown_command_names_a_version_mismatch() -> None:
    from agent_coord.server.api.mill.rpc import unknown_command_message

    wall = package_version()
    same = unknown_command_message("frobnicate", client=wall)
    assert "client" not in same
    diff = unknown_command_message("frobnicate", client="0.0.0")
    assert "mill help lists every command" in diff
    assert "client 0.0.0 != wall " in diff
