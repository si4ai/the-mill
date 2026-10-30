"""Supersedes and done-when keep each other intact (card 876). Row F156."""
from __future__ import annotations

import pytest

from agent_coord.helpers.errors import CoordError
from agent_coord.server.api.mill import rpc
from agent_coord.server.records import todo as rec_todo
from tests.server.records.conftest import seed_names

pytestmark = pytest.mark.sql


class _Book:
    def __init__(self, cn):
        self._cn = cn


def _card(cn, need):
    got = rpc._h_todo(_Book(cn), {"need": need}, "unit", "a876")
    return got[0] if isinstance(got, list) else got


def _detail(cn, need) -> str:
    hit = rec_todo.find(cn, "unit", need)
    return str(rec_todo.unpack(hit.get("body") or "", hit.get("id"))["detail"])


def test_supersedes_and_done_when_keep_each_other(cn):
    seed_names(cn, ("unit", "roster"), ("a876", "desk"))
    book = _Book(cn)
    rpc._h_open(
        book, {"need": "b876-keep", "detail": "old line", "done_when": "first"}, "unit", "a876"
    )
    rpc._h_note(
        book,
        {"need": "b876-keep", "supersedes": "old line", "note": "new line"},
        "unit",
        "a876",
    )
    card = _card(cn, "b876-keep")
    assert card["done_when"] == "first"
    assert _detail(cn, "b876-keep") == "[superseded] old line\nnew line"
    rpc._h_note(book, {"need": "b876-keep", "done_when": "second"}, "unit", "a876")
    card = _card(cn, "b876-keep")
    assert card["done_when"] == "second"
    assert _detail(cn, "b876-keep") == "[superseded] old line\nnew line"


def test_one_call_mix_is_refused_and_changes_nothing(cn):
    seed_names(cn, ("unit", "roster"), ("a876", "desk"))
    book = _Book(cn)
    rpc._h_open(
        book, {"need": "b876-mix", "detail": "old line", "done_when": "first"}, "unit", "a876"
    )
    before = (_detail(cn, "b876-mix"), _card(cn, "b876-mix")["done_when"])
    with pytest.raises(CoordError, match="--done-when goes alone"):
        rpc._h_note(
            book,
            {"need": "b876-mix", "supersedes": "old line", "note": "new line", "done_when": "second"},
            "unit",
            "a876",
        )
    assert (_detail(cn, "b876-mix"), _card(cn, "b876-mix")["done_when"]) == before
