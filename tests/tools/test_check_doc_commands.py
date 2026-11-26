"""F90 (doc-commands): tools/check_doc_commands.py holds every doc's mill commands and flags to the CLI parser.

The repo docs pass clean; each kind of drift (a command that is gone, a flag a command
does not take, a missing positional, a retired word, a stale placeholder, a
choice outside the list, a command or flag `mill -h` lists that no doc names) fails.
"""
from __future__ import annotations

import pytest

from tools import check_doc_commands as cdc

COMMANDS = cdc.load_commands()


def kinds(text: str) -> list[str]:
    return [f.kind for f in cdc.check_text(text, COMMANDS, "t.md")] + [f.kind for f in cdc.retired(text, "t.md")]


def test_repo_docs_match_the_cli(capsys):
    assert cdc.main([]) == 0, capsys.readouterr().out


@pytest.mark.parametrize(
    "text, kind",
    [
        ("Read it with `mill mail 12`.", "unknown-command"),
        ("```\nmill mcp\n```", "unknown-command"),
        ("`mill todo the-mill --bogus`", "unknown-flag"),
        ("`mill connect --owner desk-a`", "unknown-flag"),
        ("`mill invite --seat d1 --project p`", "unknown-flag"),
        ("```\nmill reply\n```", "missing-arg"),
        ("```\nbash -c 'mill connect d1 & mill reply'\n```", "missing-arg"),
        ("`mill route chain`", "unknown-sub"),
        ("`mill install nowhere`", "bad-choice"),
        ("`mill claim <project> fix-x`", "stale-placeholder"),
        ("`mill reset <project> <desk>`", "stale-placeholder"),
        ("Idle with mill_wait.", "retired-word"),
        ("The desk uses `mill leftover` when idle.", "retired-word"),
    ],
)
def test_drift_fails(text, kind):
    assert kind in kinds(text)


@pytest.mark.parametrize(
    "text",
    [
        "```\nmill connected the-mill --limit 5\n```",
        "```\nmill connected --history --who builder --page 2\n```",
        "`mill send --to-desk gardener --body-file PATH`",
        "`mill inbox [--full | --page N]`",
        "`mill mail-thread <mail_id|room> [--room | --subtree | --full] [--after ID] [--page N]`",
        "`mill --raw todo --all --done --full`",
        "`mill todo the-mill --office alias`",
        "`mill create todo <roster> <need> --status parked`",
        "`mill route add KEY -- argv`",
        "`mill reset seat <desk> --yes`",
        "`mill wall-check [--base URL] [--filter PROJECT]`",
        "No `mill sync` command.",
        "There is no `mill use`.",
        "HINT poke (not mill_wait).",
        "mill leftover command: retired.",
        "`mill install cloud --ssh <user>@<host>` (planned, not in this pack)",
        "```mermaid\nflowchart TD\n  X[no connect: mill holds data]\n  P[mill pass]\n```",
        "Join with `mill join --link-file LINKFILE`; then `mill connect <desk>`.",
        "<!-- doc-commands: skip -->\n`mill mail 12`",
    ],
)
def test_documented_forms_pass(text):
    assert kinds(text) == []


def test_help_text_is_checked_too():
    found = list(cdc.check_text("see mill todo --nope", COMMANDS, "help[x]", prose=True))
    assert [f.kind for f in found] == ["unknown-flag"]


def test_a_command_no_doc_names_fails(tmp_path):
    (tmp_path / "README.md").write_text("`mill send --to-desk d --body-file P`\n", encoding="utf-8")
    found = cdc.run(tmp_path)
    undocumented = {f.text for f in found if f.kind == "undocumented-command"}
    assert "mill todo" in undocumented and "mill send" not in undocumented
    # Hidden commands (help suppressed) are not owed a doc.
    assert "mill drain" not in undocumented
    flags = {f.text for f in found if f.kind == "undocumented-flag"}
    assert "mill todo --mine" in flags and "mill send --to-desk" not in flags


def sessions(text: str) -> list[str]:
    return [f.kind for f in cdc.session_findings(text, "t.md")]


def test_the_cli_session_rule_is_read_from_the_code():
    """Both contexts the docs describe: a sitting connect refuses --desk, no connect refuses its absence."""
    assert "--desk is not necessary" in cdc.session_refusal(asked=True, sitting=True)
    assert "no sitting mill connect" in cdc.session_refusal(asked=False, sitting=False)
    assert cdc.session_refusal(asked=False, sitting=True) == ""
    assert cdc.session_refusal(asked=True, sitting=False) == ""


def test_a_desk_flag_in_a_session_example_fails():
    # the 0.8.18 line (card 1310): a desk reads it inside its sitting connect
    line = "In your weekly review, read `mill score Office doing.task.end_reason --desk DESK` and act."
    assert sessions(line) == ["desk-in-session"]
    assert sessions("```\nmill score Office doing.task.end_reason --desk DESK\n```") == ["desk-in-session"]
    assert sessions("```\nmill todo --mine --desk=builder\n```") == ["desk-in-session"]


@pytest.mark.parametrize(
    "text",
    [
        "In your weekly review, read `mill score Office doing.task.end_reason` and act.",
        "With no sitting connect, run `mill todo --mine --desk DESK` for one command.",
        "Fallback: `mill reply 12 --body-file P --desk DESK`.",
        "Then `mill reply ... --desk DESK` borrows the seat with no leftover connect.",
        "With no connect sitting:\n```\nmill todo --mine --desk DESK\n```",
        "`--desk` alone is the seat borrow.",
        "<!-- doc-commands: skip -->\n`mill todo --desk DESK`",
    ],
)
def test_a_desk_flag_in_the_no_connect_form_passes(text):
    assert sessions(text) == []
