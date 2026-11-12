"""note --supersedes on a real book (#333)."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.sql

from agent_coord.helpers.errors import CoordError
from agent_coord.server.api.mill import rpc
from agent_coord.server.records import todo as rec_todo
from tests.server.records.conftest import seed_names


class _Book:
    def __init__(self, cn):
        self._cn = cn


def _detail(cn) -> str:
    hit = rec_todo.find(cn, "unit", "c333-card")
    return str(rec_todo.unpack(hit.get("body") or "", hit.get("id"))["detail"])


def test_note_text_and_supersedes_leave_the_detail(cn) -> None:
    seed_names(cn, ("unit", "roster"), ("c333-asker", "desk"), ("c333-other", "desk"))
    book = _Book(cn)
    rpc._h_open(book, {"need": "c333-card", "detail": "1. connect old-pilot\n2. read"}, "unit", "c333-asker")
    original = "1. connect old-pilot\n2. read"
    for body in (
        {"need": "c333-card", "note": "later"},
        {"need": "c333-card", "supersedes": "1. connect old-pilot", "note": "1. connect github-pilot"},
    ):
        with pytest.raises(CoordError, match="mill replace-body"):
            rpc._h_note(book, body, "unit", "c333-asker")
        assert _detail(cn) == original
