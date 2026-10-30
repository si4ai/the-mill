"""claim, assign and unclaim follow the card states (card 778).

Documented moves (states.md): open -> claimed by claim or assign, claimed ->
open by unclaim, parked -> open only by unpark (which needs a plan parent).
Before: claim and assign took a parked card straight to claimed with no plan
parent, and claim, assign and unclaim moved shipped and done cards too (a done
card went back to claimed or open). Now each refuses a card in a state it does
not move, names the command that does, and changes nothing.

Regression row F131 (claim-status-guards).
"""
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


def _state(cn, need):
    hit = rec_todo.find(cn, "unit", need)
    return str(hit.get("status")), rpc._desk_slug(cn, hit, "volunteer", "assigned")


def _card(book, need, status):
    """A card in STATUS: asker a, volunteer b for claimed and later."""
    rpc._h_open(book, {"need": need, "status": "parked" if status == "parked" else ""}, "unit", "a")
    if status in ("claimed", "shipped", "done"):
        rpc._h_claim(book, {"need": need}, "unit", "b")
    if status in ("shipped", "done"):
        rpc._h_pass(book, {"need": need}, "unit", "b")
    if status == "done":
        rpc._h_pass(book, {"need": need, "step": "done"}, "unit", "a")


@pytest.fixture
def book(cn):
    seed_names(cn, ("unit", "roster"), ("a", "desk"), ("b", "desk"), ("c", "desk"))
    return _Book(cn)


def test_claim_on_parked_names_unpark_with_a_parent(cn, book) -> None:
    _card(book, "c778-park-claim", "parked")
    with pytest.raises(CoordError, match=r"claim: unit/c778-park-claim is parked; "
                       r"mill unpark unit c778-park-claim --parent-type T --parent-id N first"):
        rpc._h_claim(book, {"need": "c778-park-claim"}, "unit", "c")
    assert _state(cn, "c778-park-claim") == ("parked", "")


def test_assign_on_parked_is_refused(cn, book) -> None:
    _card(book, "c778-park-assign", "parked")
    with pytest.raises(CoordError, match=r"assign: unit/c778-park-assign is parked; mill unpark"):
        rpc._h_assign(book, {"need": "c778-park-assign", "desk": "c"}, "unit", "a")
    assert _state(cn, "c778-park-assign") == ("parked", "")


@pytest.mark.parametrize("status", ["shipped", "done"])
@pytest.mark.parametrize("command", ["claim", "assign", "unclaim"])
def test_shipped_and_done_cards_do_not_move(cn, book, status, command) -> None:
    need = f"c778-{command}-{status}"
    _card(book, need, status)
    before = _state(cn, need)
    with pytest.raises(CoordError, match=rf"{command}: unit/{need} is {status}; .*mill pass unit {need} --"):
        if command == "claim":
            rpc._h_claim(book, {"need": need, "take_over": True}, "unit", "c")
        elif command == "assign":
            rpc._h_assign(book, {"need": need, "desk": "c"}, "unit", "a")
        else:
            rpc._h_yield(book, {"need": need}, "unit", "b")
    assert _state(cn, need) == before


def test_the_documented_moves_still_work(cn, book) -> None:
    _card(book, "c778-ok", "open")
    assert rpc._h_claim(book, {"need": "c778-ok"}, "unit", "b")["status"] == "claimed"
    assert rpc._h_claim(book, {"need": "c778-ok", "take_over": True}, "unit", "c")["status"] == "claimed"
    assert rpc._h_yield(book, {"need": "c778-ok"}, "unit", "c")["status"] == "open"
    assert rpc._h_assign(book, {"need": "c778-ok", "desk": "b"}, "unit", "a")["status"] == "claimed"
    assert _state(cn, "c778-ok") == ("claimed", "b")
