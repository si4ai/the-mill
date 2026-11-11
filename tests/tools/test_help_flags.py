"""F41 (help-flags): mill help COMMAND names every flag the parser takes for that command (#301).

A flag added to a subparser without a matching row in docs/protocol/cli-*.md (the
text mill help COMMAND prints) fails here. Hidden commands (help suppressed) and the
flags every command takes (--help, --office, --yes), and --desk on desk commands (documented in the session line, not each command row), are skipped.
"""
from __future__ import annotations

import argparse

import pytest

from agent_coord.__main__ import _build_parser
from agent_coord.install.office import help_text

_EVERY_COMMAND = {"--help", "--office", "--yes", "--desk"}


def _shown_commands() -> dict[str, argparse.ArgumentParser]:
    p = _build_parser()
    sub = next(a for a in p._actions if isinstance(a, argparse._SubParsersAction))
    shown = {ca.dest for ca in sub._choices_actions}
    return {name: sp for name, sp in sub.choices.items() if name in shown}


COMMANDS = _shown_commands()


@pytest.mark.parametrize("command", sorted(COMMANDS))
def test_help_topic_names_every_flag(command: str) -> None:
    text = help_text(command)
    assert not text.startswith("mill help: no such topic"), f"mill help {command}: no topic"
    flags = [
        o
        for a in COMMANDS[command]._actions
        if a.help != argparse.SUPPRESS
        for o in a.option_strings
        if o.startswith("--") and o not in _EVERY_COMMAND
    ]
    missing = [f for f in flags if f not in text]
    assert not missing, f"mill help {command} does not name {missing}; add them to its cli-*.md row"


def test_help_score_shows_record_read_list_target_and_words() -> None:
    text = help_text("score")
    for want in ("mill score <roster> <name> <value>", "mill score <roster> <name> [--limit N]",
                 "mill score <roster>`", "--target T [--better", "improving", "flat", "worse", "met"):
        assert want in text, want
    assert "Set a scorecard value" not in text
