"""Roster send skips retired member desks (card 963).

Before: mill send roster NAME expands every member, including a retired desk
still on the member table (M4 keeps those rows). mill_mail_insert then calls
MILL_NAME_GET on that desk and the whole send fails with
`1644 (45000): name retired: mill reclaim NAME NAME --yes (mill host only)`.

After: roster expansion keeps only live desks; skipped names are listed; the
retired desk gets no letter. An explicit send desk to a retired name still
refuses.

Regression row F-roster-send-skips-retired.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.sql

from agent_coord.server.api.mill import rpc
from agent_coord.server.records import mail as rec_mail
from agent_coord.server.records import member as rec_member
from agent_coord.server.records import name as rec_name
from tests.server.records.conftest import admin_desk, seed_names


class _Book:
    def __init__(self, cn):
        self._cn = cn


def _setup(cn, *, roster: str, sender: str, live: str, gone: str) -> None:
    seed_names(
        cn,
        (roster, "roster"),
        (sender, "desk"),
        (live, "desk"),
        (gone, "desk"),
    )
    rec_member.put(cn, roster, sender)
    rec_member.put(cn, roster, live)
    rec_member.put(cn, roster, gone)
    rec_name.retire(cn, gone, "desk", by=admin_desk(cn))
    # M4: member rows stay after retire.
    rows = rec_member.select(cn, group=roster)
    desks = {str(r.get("desk") or "") for r in rows}
    assert desks >= {sender, live, gone}


def test_roster_send_skips_retired_member_and_delivers_to_live(cn) -> None:
    roster, sender, live, gone = "team963a", "rs-a-sender", "rs-a-live", "rs-a-gone"
    _setup(cn, roster=roster, sender=sender, live=live, gone=gone)
    book = _Book(cn)
    out = rpc._h_send(
        book,
        {
            "src": sender,
            "mail_tos": [{"deskId": roster, "kind": "roster"}],
            "body": "hello team",
        },
        roster,
        sender,
    )
    mid = int(out["id"])
    dests = {str(r.get("desk") or "") for r in rec_mail.to_list(cn, mid)}
    assert live in dests
    assert gone not in dests
    assert sender not in dests  # sender excluded on roster send
    skipped = list(out.get("skipped") or [])
    assert gone in skipped
    note = str(out.get("note") or "")
    assert gone in note or gone in skipped


def test_desk_send_to_retired_name_still_refuses(cn) -> None:
    roster, sender, live, gone = "team963b", "rs-b-sender", "rs-b-live", "rs-b-gone"
    _setup(cn, roster=roster, sender=sender, live=live, gone=gone)
    book = _Book(cn)
    with pytest.raises(Exception) as err:
        rpc._h_send(
            book,
            {
                "src": sender,
                "mail_tos": [{"deskId": gone, "kind": "desk"}],
                "body": "direct",
            },
            roster,
            sender,
        )
    text = str(err.value).lower()
    assert "retired" in text or "no desk" in text or "not in the name table" in text, text
