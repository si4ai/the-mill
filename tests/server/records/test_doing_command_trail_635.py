"""#635: doing stays as the desk wrote it; a read command bumps the seat only (F79)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from agent_coord.server.api.mill import rpc
from agent_coord.server.book import Book
from agent_coord.server.records.doing_stack import clean, push, split

TRAIL = "trail | todo | member | mail-thread | trail | todo | purpose line | member | present"


def test_clean_drops_the_command_trail_and_keeps_desk_text() -> None:
    assert split(clean(TRAIL)) == ["purpose line", "present"]


def test_clean_keeps_a_trail_only_seat_present() -> None:
    assert clean("trail | todo | member | present") == "present"


def test_desk_text_replaces_placeholders_and_trail() -> None:
    assert push("todo | member | present", "purpose line") == "purpose line"


def test_repeat_text_moves_to_the_top_once() -> None:
    assert split(push("b | a", "a")) == ["a", "b"]


def test_read_command_does_not_push_its_name() -> None:
    c = MagicMock(spec=Book)
    c._cn = MagicMock()
    with patch("agent_coord.server.records.join.touch") as touch, patch(
        "agent_coord.server.records.doing.put"
    ) as pushed:
        for command in ("todo", "member", "mail-thread", "trail", "session"):
            rpc._note_doing(c, "the-mill", "builder", command)
    assert pushed.call_count == 0
    assert touch.call_count == 5
