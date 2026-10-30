"""mill add|remove TYPE:ID [WHO] (#265) next to add|remove roster NAME [d1,d2] (0.7.2 batch).

One add/remove parser: a TYPE with a colon is the #265 target form; `roster` is the
membership form. TYPE:ID is always typed, never a bare id.
"""
from __future__ import annotations

import pytest

from agent_coord.__main__ import _build_parser
from agent_coord.client import outbound
from agent_coord.client.language import translate
from agent_coord.helpers.errors import CoordError


@pytest.fixture()
def body(monkeypatch):
    import agent_coord.client.tokens as tokens

    monkeypatch.setattr(tokens, "resolve_desk_owner", lambda x="": "me")
    p = _build_parser()

    def run(argv: list[str]) -> dict:
        return outbound.body_from_args(translate(p.parse_args(argv)))

    return run


def _exit2(argv):
    with pytest.raises(SystemExit) as ei:
        _build_parser().parse_args(argv)
    assert ei.value.code == 2


@pytest.mark.parametrize("raw,want", [
    ("todo:256", ("todo", 256)), ("mail:1866", ("mail", 1866)), ("HOLD:3", ("hold", 3)),
    ("doing:8", ("doing", 8)), ("score:40", ("score", 40)),
])
def test_target_parses(body, raw, want):
    b = body(["add", raw])
    assert (b["verb"], b["type"], b["id"]) == ("add", *want) and "who" not in b
    r = body(["remove", raw, "validator"])
    assert (r["verb"], r["type"], r["id"], r["who"]) == ("remove", *want, "validator")


@pytest.mark.parametrize("raw", ["todo:", ":5", "todo:0", "todo:-1", "todo:x", "tree:5", "name:1", "todo:5:6", "join:7"])
def test_bad_target_is_refused(body, raw):
    for command in ("add", "remove"):
        with pytest.raises(CoordError, match="type:id"):
            body([command, raw])


@pytest.mark.parametrize("raw", ["256", "todo", "desk"])
def test_no_colon_is_the_roster_form(body, raw):
    with pytest.raises(CoordError, match="TYPE is roster"):
        body(["add", raw, "x"])


def test_who_defaults_to_self_and_hint_is_add_only(body):
    a = body(["add", "todo:5", "--hint", "x"])
    assert "who" not in a and a["hint"] == "x"
    _exit2(["remove", "todo:5", "--hint", "x"])
    with pytest.raises(CoordError, match="one WHO"):
        body(["add", "todo:5", "a", "b"])


def test_roster_form_still_maps_to_member_add(body):
    b = body(["add", "roster", "night", "d1"])
    assert b["verb"] == "member-add" and b["group"] == "night"
    with pytest.raises(CoordError, match="NAME required"):
        body(["add", "roster"])


@pytest.mark.parametrize("argv", [
    ["watcher", "todo", "5"],
    ["reply", "1", "--body-file", "b", "--add-to", "x"],
    ["reply", "1", "--body-file", "b", "--remove-to", "x"],
])
def test_old_command_and_flags_are_gone(argv):
    _exit2(argv)


@pytest.mark.parametrize("command", ["watch", "unwatch"])
def test_join_type_is_refused(command):
    """#818: the activity type is doing; join is no TYPE (no alias)."""
    _exit2([command, "join", "3"])
    args = _build_parser().parse_args([command, "doing", "3"])
    assert args.type == "doing"
