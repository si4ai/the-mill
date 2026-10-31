# -*- coding: utf-8 -*-
"""Card 735: a not-found refusal names the command that lists valid names."""
from __future__ import annotations

from agent_coord.helpers.next_cmd import with_next
from agent_coord.helpers.projects import project_refusal


def test_with_next_appends_a_mill_command_once():
    line = with_next("no such need: the-mill/missing", "find it: mill todo --all --find missing")
    assert line == "no such need: the-mill/missing. find it: mill todo --all --find missing"
    assert with_next(line, "find it: mill todo --all --find missing") == line
    assert with_next("already says mill inbox", "mill inbox") == "already says mill inbox"


def test_roster_refusal_names_member():
    text = project_refusal("connect", "missing", ["Office", "the-mill"])
    assert text == (
        "connect: no such roster missing; rosters: Office, the-mill. list them: mill member"
    )
    assert project_refusal("connect", "", ["Office"]) == (
        "connect: no such roster; rosters: Office. list them: mill member"
    )


def test_status_names_the_flag():
    assert with_next(
        "status must be parked or open",
        "use --status parked or --status open",
    ) == "status must be parked or open. use --status parked or --status open"
