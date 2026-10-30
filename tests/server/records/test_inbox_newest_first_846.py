"""Unread inbox lists the newest unread first (card 846).

Before: unread was the oldest `--limit` (100) unread letters, oldest first, so a
desk with a backlog never saw the letter that had just woken it (dogfood letters
2751 and 2754). Now unread is the newest `--limit` unread, newest first, the same
order as `--all`.

Regression row F137 (inbox-newest-first).
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.sql

from agent_coord.server.api.mill import rpc
from agent_coord.server.records import mail as rec_mail
from agent_coord.server.records import opened as rec_opened
from tests.server.records.conftest import seed_names


class _Book:
    def __init__(self, cn):
        self._cn = cn


def test_the_newest_unread_letter_is_on_top_past_the_limit(cn) -> None:
    seed_names(cn, ("nf", "roster"), ("nf_s", "desk"), ("nf_r", "desk"))
    ids = [int(rec_mail.insert(cn, "nf", "nf_s", "nf_r", f"old {i}")[0]["id"]) for i in range(6)]
    rec_opened.insert(cn, ids[0], "nf_r")
    got = [int(m["id"]) for m in rpc._h_inbox(_Book(cn), {"limit": 3}, "nf", "nf_r")]
    assert got == [ids[5], ids[4], ids[3]]
    new = int(rec_mail.insert(cn, "nf", "nf_s", "nf_r", "the one that woke you")[0]["id"])
    assert int(rpc._h_inbox(_Book(cn), {"limit": 3}, "nf", "nf_r")[0]["id"]) == new
    every = [int(m["id"]) for m in rpc._h_inbox(_Book(cn), {}, "nf", "nf_r")]
    assert every == sorted(ids[1:] + [new], reverse=True)
