"""Doctrine docs: a fetch does not mark (reply marks the parent; mark marks the rest),
and activity is the timeline, not a parent.

Fails if inbox / mail-thread help or the protocol docs say a fetch marks read.
"""
from __future__ import annotations

import pathlib
import re

import pytest

import io
import sys


def _help(argv: list[str]) -> str:
    import agent_coord.__main__ as m

    buf = io.StringIO()
    old = sys.stdout, sys.stderr, sys.argv
    try:
        sys.stdout = sys.stderr = buf
        sys.argv = argv
        try:
            m.main()
        except SystemExit as e:
            assert e.code in (0, None)
        return buf.getvalue()
    finally:
        sys.stdout, sys.stderr, sys.argv = old

ROOT = pathlib.Path(__file__).resolve().parents[2]
BAD = re.compile(
    r"marks? (the returned letters |letters |it )?read( by default)?"
    r"|unless --no-mark|without marking|inbox marks|catch-up without mark",
    re.IGNORECASE,
)
DOCS = [
    "docs/protocol/hints.md",
    "docs/protocol/howto-ai.md",
    "docs/protocol/sync.md",
    "docs/protocol/commands.md",
    "docs/protocol/usecases.md",
    "docs/protocol/skill.md",
    "docs/protocol/grok-foreground.md",
]


@pytest.mark.parametrize("command", ["inbox", "mail-thread"])
def test_help_does_not_say_fetch_marks(command):
    text = _help(["mill", command, "--help"])
    assert not BAD.search(text), BAD.search(text).group(0)
    assert "--no-mark" not in text


def test_inbox_help_says_flags_do_nothing():
    text = " ".join(_help(["mill", "inbox", "--help"]).split())
    assert "accepted and do nothing" in text or "does not mark" in text


@pytest.mark.parametrize("rel", DOCS)
def test_docs_do_not_say_fetch_marks(rel):
    p = ROOT / rel
    if not p.exists():
        pytest.skip(rel)
    hit = BAD.search(p.read_text(encoding="utf-8"))
    assert hit is None, "%s: %s" % (rel, hit.group(0))


# Doctrine 2: activity is the timeline, not a parent (#216). No payload table has
# a foreign key to activity; only label and tree keep one.
ACT_BAD = re.compile(
    r"superclass|subclass|inherits? (from )?activity|--\|> *activity"
    r"|refused while the (matching|detail)",
    re.IGNORECASE,
)
ACT_DOCS = [
    "README.md",
    "docs/protocol/records.md",
    "docs/protocol/commands.md",
    "docs/requirements/activity.md",
    "docs/protocol/skill.md",
]


@pytest.mark.parametrize("rel", ACT_DOCS)
def test_docs_do_not_teach_activity_as_parent(rel):
    p = ROOT / rel
    if not p.exists():
        pytest.skip(rel)
    hit = ACT_BAD.search(p.read_text(encoding="utf-8"))
    assert hit is None, "%s: %s" % (rel, hit.group(0))


def test_records_doc_says_activity_is_timeline():
    text = " ".join((ROOT / "docs/protocol/records.md").read_text(encoding="utf-8").split())
    assert "Activity is the timeline, not a parent" in text
    assert "No payload table has a foreign key to `activity`" in text


def test_tables_sql_has_no_payload_fk_to_activity():
    sql = (ROOT / "agent_coord/server/sql/tables.sql").read_text(encoding="utf-8")
    for t in ("mail", "todo", "join", "hold", "score"):
        assert "fk_%s_activity" % t not in sql
