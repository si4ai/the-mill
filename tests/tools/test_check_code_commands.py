"""F229 (code-hint-commands): tools/check_code_commands.py holds agent_coord strings to the CLI parser.

Every backticked or taught `mill ...` form in agent_coord/ strings and docstrings
must parse with the real CLI (card 734). Complements F90 (docs).
"""
from __future__ import annotations

import pytest

from tools import check_code_commands as ccc
from tools import check_doc_commands as cdc

COMMANDS = cdc.load_commands()


def kinds_from_text(text: str) -> list[str]:
    found = []
    for _line, form in ccc.taught_forms(text, COMMANDS):
        wrapped = f"`{form}`"
        found.extend(f.kind for f in cdc.check_text(wrapped, COMMANDS, "t"))
        found.extend(f.kind for f in cdc.retired(wrapped, "t"))
    return found


def test_agent_coord_strings_match_the_cli(capsys):
    assert ccc.main([]) == 0, capsys.readouterr().out


@pytest.mark.parametrize(
    "text, kind",
    [
        ("`mill join --desk DESK --websocket`", "unknown-flag"),
        ("mill join failed: --ca is not a CA PEM.", "unknown-flag"),
        (
            "mill join --url https://office.example/?invite=X --desk d1",
            "unknown-flag",
        ),
        ("`mill leftover`", "retired-word"),
    ],
)
def test_drift_fails(text, kind):
    assert kind in kinds_from_text(text)


@pytest.mark.parametrize(
    "text, kind",
    [
        # Unknown command at the start of a line (not only known/gone names).
        ("mill roster NAME NAME --yes", "unknown-command"),
        ("mill spend --source grok --tokens N", "unknown-command"),
        # Bare unknown verbs (no --flags): line-start and after Next: / run:.
        ("mill plumrot", "unknown-command"),
        (
            "join failed: bad CA. Next: mill snorfle",
            "unknown-command",
        ),
        (
            "book SQL is not this pack's; run: mill wibble",
            "unknown-command",
        ),
        # Mid-string hints after Next: / run: must be extracted and checked.
        (
            "join failed: bad CA. Next: mill roster NAME NAME --yes",
            "unknown-command",
        ),
        (
            "book SQL is not this pack's; run: mill leftover",
            "retired-word",
        ),
    ],
)
def test_start_line_unknown_and_next_run_hints(text, kind):
    assert kind in kinds_from_text(text)


@pytest.mark.parametrize(
    "text",
    [
        "`mill join --link-file PATH --webhook-url URL --webhook-key-file PATH`",
        "`mill join DESK --websocket`",
        'note = "join failed: the --ca file is not a CA PEM. Next: mill join --link-file PATH"',
        'next_cmd = "mill join --link-file PATH"',
        '"next": ["mill invite --door invite", "mill install server --apply --public"]',
        "print('route add: key required')",
        "mill connect: ready; it blocks this shell.",
        "mill here mints the token (like creating a PAT).",
    ],
)
def test_documented_forms_pass(text):
    assert kinds_from_text(text) == []
