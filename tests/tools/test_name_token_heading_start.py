"""Markdown heading marks are a line-start prefix for the name-token rule.

check_pack treated a capitalized ordinary word after "### " as a person's
name, so a squash message with a heading like "### Help / briefing scan"
failed. One to six "#" marks followed by a space now get the same
line-start rule as a bullet, list number or card number: the word passes
only when its lower-case form is an ordinary word. A heading whose first
word is not in the vocab still fails, a bare "#Name" (no space) still
fails, and the "#N" card-ref form is unchanged.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import check_pack as cp  # noqa: E402

# Invented name-like token, assembled so no literal sits in this file.
NAME = "Qu" + "illonde"
VOCAB = frozenset({"help", "scope", "finding", "briefing", "scan"})

HEADING_PASS = [
    "### Help / briefing scan",
    "# Help at the top",
    "###### Help at six",
    "title\n\n### Help / briefing scan\n",
    "  ## Help indented\n",
]

HEADING_FAIL = [
    "### Legit ran from this worktree",
    f"### {NAME} reviewed it",
    f"# {NAME} at the top",
    "title\n\n### Legit ran from this worktree\n",
]

CARD_REF_PASS = [
    "#338 Scope the hook",
    "#338: Scope the hook",
    "title\n\n#338 Scope the hook\nFinding first.\n",
]

CARD_REF_FAIL = [
    f"#338 {NAME} the hook",
    f"#338: {NAME} the hook",
]


def test_off_vocab_words_are_not_ordinary() -> None:
    for n in (NAME, "Legit"):
        assert n.casefold() not in VOCAB
        assert n.casefold() not in cp.DESK_WORD_ALLOWLIST


@pytest.mark.parametrize("msg", HEADING_PASS)
def test_heading_ordinary_word_passes(msg: str) -> None:
    assert not cp.text_has_personal_name_token(msg, VOCAB), msg


@pytest.mark.parametrize("msg", HEADING_FAIL)
def test_heading_off_vocab_title_word_fails(msg: str) -> None:
    assert cp.text_has_personal_name_token(msg, VOCAB), msg


@pytest.mark.parametrize("msg", CARD_REF_PASS)
def test_card_ref_ordinary_word_still_passes(msg: str) -> None:
    assert not cp.text_has_personal_name_token(msg, VOCAB), msg


@pytest.mark.parametrize("msg", CARD_REF_FAIL)
def test_card_ref_off_vocab_title_word_still_fails(msg: str) -> None:
    assert cp.text_has_personal_name_token(msg, VOCAB), msg


def test_bare_hash_name_without_space_still_fails() -> None:
    # A heading prefix needs a space. "#Name" must not start to pass.
    assert cp.text_has_personal_name_token(f"#{NAME}", VOCAB)
    # An ordinary word after a bare hash is mid-line, not a heading.
    assert cp.text_has_personal_name_token("#Help / briefing scan", VOCAB)


def test_line_without_heading_marks_already_passed() -> None:
    assert not cp.text_has_personal_name_token("Help / briefing scan", VOCAB)


def test_tree_vocab_reads_the_repro_heading_as_ordinary() -> None:
    vocab = cp.ordinary_words(ROOT)
    assert "help" in vocab
    assert "legit" not in vocab
    assert not cp.text_has_personal_name_token("### Help / briefing scan", vocab)
    assert cp.text_has_personal_name_token("### Legit ran from this worktree", vocab)
