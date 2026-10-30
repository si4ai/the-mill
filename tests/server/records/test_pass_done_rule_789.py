"""One pass --done rule: the asker or Admin accepts a shipped card (card 789).

Docs, help and the refusal text all said the asker (or Admin) accepts; the code
also let the volunteer accept their own shipped card when the card had another
asker. Now the volunteer is refused like any other desk, and only when the asker
does not resolve may the volunteer still finish the card (F99 stays). A desk
that filed and claimed its own card is its asker and accepts it.

Regression row F132 (pass-done-rule).
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


def _shipped(cn, need, asker="a789", vol="v789"):
    seed_names(cn, ("unit", "roster"), (asker, "desk"), (vol, "desk"), ("adm789", "desk"))
    book = _Book(cn)
    rpc._h_open(book, {"need": need}, "unit", asker)
    rpc._h_claim(book, {"need": need}, "unit", vol)
    rpc._h_pass(book, {"need": need}, "unit", vol)
    return book


def _status(cn, need):
    return rec_todo.find(cn, "unit", need)["status"]


def test_the_volunteer_cannot_accept_a_card_another_desk_asked_for(cn) -> None:
    book = _shipped(cn, "p789-a")
    with pytest.raises(CoordError) as e:
        rpc._h_pass(book, {"need": "p789-a", "step": "done"}, "unit", "v789")
    assert str(e.value) == "who-may: pass shipped->done is the asker (a789) or Admin"
    assert _status(cn, "p789-a") == "shipped"
    assert rpc._h_pass(book, {"need": "p789-a", "step": "done"}, "unit", "a789")["status"] == "done"


def test_admin_accepts(cn) -> None:
    from agent_coord.server.records import member as rec_member

    book = _shipped(cn, "p789-b")
    rec_member.put_admin(cn, "adm789")  # #867: cmd_pass reads the Admin roster itself
    assert rpc._h_pass(book, {"need": "p789-b", "step": "done"}, "unit", "adm789")["status"] == "done"


def test_a_self_filed_card_is_accepted_by_its_filer(cn) -> None:
    book = _shipped(cn, "p789-c", asker="s789", vol="s789")
    assert rpc._h_pass(book, {"need": "p789-c", "step": "done"}, "unit", "s789")["status"] == "done"


def test_the_volunteer_still_steps_back(cn) -> None:
    book = _shipped(cn, "p789-d")
    assert rpc._h_pass(book, {"need": "p789-d", "step": "back"}, "unit", "v789")["status"] == "claimed"
