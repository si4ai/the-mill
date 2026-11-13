"""#635 / card 1207: a read command bumps the seat and never writes doing (doing is tw runs only)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from agent_coord.server.api.mill import rpc
from agent_coord.server.book import Book


def test_read_command_bumps_the_seat_only() -> None:
    c = MagicMock(spec=Book)
    c._cn = MagicMock()
    with patch("agent_coord.server.records.join.touch") as touch:
        for command in ("todo", "member", "mail-thread", "trail", "session"):
            rpc._note_doing(c, "the-mill", "builder", command)
    assert touch.call_count == 5
