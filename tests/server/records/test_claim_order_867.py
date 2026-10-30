"""Claim refuses in main's order (card 867, Validator letter 2944 a and b).

Main ran, in this order: the status refusal (_card_moves: parked, shipped, done),
the msg length cap, the eta parse, the #325 claimed-by refusal (no --take-over),
then the card budget. Card 867 moved the status and claimed-by guards into
cmd_claim, which ran after the eta, msg and budget checks, so a bad eta, a long
msg or a budget overflow hid the status or claimed-by line. The handler now
pre-checks the row it already read in main's order; cmd_claim stays the
authority under the row lock (test_claim_lock_867). Nothing is written on any
refusal here.
"""
from __future__ import annotations

import pytest

from agent_coord.helpers.errors import CoordError
from agent_coord.server.api.mill import rpc
from agent_coord.server.records import member as rec_member
from agent_coord.server.records import todo as rec_todo
from tests.server.records.conftest import seed_names

pytestmark = pytest.mark.sql

R = "ord867"
ASKER, VOL, OTHER, ADMIN = "oa867", "ov867", "oo867", "oadm867"
DESKS = {"asker": ASKER, "vol": VOL, "other": OTHER, "admin": ADMIN, "none": None, "unknown": "ghost867"}
# A detail this long leaves the card about 200 characters of budget.
DETAIL = "d" * 3850
INPUTS = {
    "bad_eta": {"eta": "not-a-time"},
    "long_msg": {"msg": "m" * 4097},
    "budget_msg": {"msg": "b" * 600},
}


class _Book:
    def __init__(self, cn):
        self._cn = cn


@pytest.fixture(scope="module")
def cards(cn):
    """One card per status, all with the long detail: parked, shipped, done, claimed by VOL."""
    seed_names(cn, (R, "roster"), (ASKER, "desk"), (VOL, "desk"), (OTHER, "desk"), (ADMIN, "desk"))
    rec_member.put_admin(cn, ADMIN)
    book = _Book(cn)
    saved = rpc._poke
    rpc._poke = lambda *a, **k: None
    try:
        rpc._h_open(book, {"need": "c-parked", "status": "parked", "detail": DETAIL}, R, ASKER)
        for need in ("c-shipped", "c-done", "c-claimed"):
            rpc._h_open(book, {"need": need, "detail": DETAIL}, R, ASKER)
            rpc._h_claim(book, {"need": need}, R, VOL)
        rpc._h_pass(book, {"need": "c-shipped"}, R, VOL)
        rpc._h_pass(book, {"need": "c-done"}, R, VOL)
        rpc._h_pass(book, {"need": "c-done", "step": "done"}, R, ASKER)
    finally:
        rpc._poke = saved
    return book


def _status_line(st, need):
    form = f"mill pass {R} {need}"
    head = f"claim: {R}/{need} is {st}; "
    if st == "parked":
        return head + f"mill unpark {R} {need} --parent-type T --parent-id N first"
    if st == "shipped":
        return head + f"the asker accepts it with {form} --done, or steps it back with {form} --back"
    return head + f"{form} --back steps it back to shipped; for new work file a new card"


def _claimed_by(need):
    return (
        f"claim: {R}/{need} is claimed by {VOL}; ask {VOL} to mill unclaim {R} {need}, "
        f"or run mill claim {R} {need} --take-over to take it (the card records the prior volunteer)"
    )


def _snapshot(cn, need):
    hit = rec_todo.find(cn, R, need)
    return hit["status"], hit.get("assigned"), hit.get("body")


@pytest.mark.parametrize("trust", ["high", "limited"])
@pytest.mark.parametrize("desk", list(DESKS))
@pytest.mark.parametrize("inp", list(INPUTS))
@pytest.mark.parametrize("st", ["parked", "shipped", "done"])
def test_status_refusal_comes_before_eta_msg_and_budget(cards, cn, monkeypatch, trust, desk, inp, st):
    """Letter 2944 a: the status line, never the eta, msg or budget line."""
    monkeypatch.setenv("AGENT_COORD_TRUST", trust)
    need = f"c-{st}"
    before = _snapshot(cn, need)
    with pytest.raises(CoordError) as e:
        rpc._h_claim(cards, {"need": need, **INPUTS[inp]}, R, DESKS[desk])
    assert str(e.value) == _status_line(st, need)
    assert _snapshot(cn, need) == before


@pytest.mark.parametrize("trust", ["high", "limited"])
@pytest.mark.parametrize("desk", [d for d in DESKS if d != "vol"])
def test_claimed_by_comes_before_the_budget(cards, cn, monkeypatch, trust, desk):
    """Letter 2944 b: another desk's card, no --take-over, a msg past the budget."""
    monkeypatch.setenv("AGENT_COORD_TRUST", trust)
    before = _snapshot(cn, "c-claimed")
    with pytest.raises(CoordError) as e:
        rpc._h_claim(cards, {"need": "c-claimed", **INPUTS["budget_msg"]}, R, DESKS[desk])
    assert str(e.value) == _claimed_by("c-claimed")
    assert _snapshot(cn, "c-claimed") == before


@pytest.mark.parametrize("trust", ["high", "limited"])
@pytest.mark.parametrize("desk", [d for d in DESKS if d != "vol"])
@pytest.mark.parametrize("inp", ["bad_eta", "long_msg"])
def test_msg_cap_and_eta_still_come_before_claimed_by(cards, cn, monkeypatch, trust, desk, inp):
    """Main's order kept: the msg cap and the eta parse ran before the claimed-by check."""
    monkeypatch.setenv("AGENT_COORD_TRUST", trust)
    with pytest.raises(CoordError) as e:
        rpc._h_claim(cards, {"need": "c-claimed", **INPUTS[inp]}, R, DESKS[desk])
    text = str(e.value)
    if inp == "long_msg":
        assert text == "claim: msg would be 4097 chars (max 4096)"
    else:
        assert text.startswith("claim: ") and "claimed by" not in text


@pytest.mark.parametrize("trust", ["high", "limited"])
def test_the_volunteer_over_budget_gets_the_budget_line(cards, cn, monkeypatch, trust):
    monkeypatch.setenv("AGENT_COORD_TRUST", trust)
    with pytest.raises(CoordError, match="claim: refused, nothing written: this note needs"):
        rpc._h_claim(cards, {"need": "c-claimed", **INPUTS["budget_msg"]}, R, VOL)
