"""F21: the inbox page is cut in SQL from mail_to (desk_id, opened, id)."""
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


def _legacy(cn, desk: str, unread_only: bool, lim: int) -> list[int]:
    """The 0.7.3 rule: whole mailbox, drop opened, sort, slice (the reference)."""
    rows = rec_mail.select(cn, desk)
    kept = [r for r in rows if not (unread_only and r.get("opened") is not None)]
    kept.sort(key=lambda r: int(r["id"]), reverse=True)  # newest first, both (card 846)
    return [int(r["id"]) for r in kept[: max(1, lim or 100)]]


@pytest.fixture(scope="module")
def box(cn):
    seed_names(cn, ("ib", "roster"), ("ib_s", "desk"), ("ib_r", "desk"), ("ib_o", "desk"), ("ib_none", "desk"))
    ids = []
    for i in range(12):
        ids.append(int(rec_mail.insert(cn, "ib", "ib_s", "ib_r", f"letter {i}")[0]["id"]))
        if i % 3 == 0:
            rec_mail.to_put(cn, ids[-1], "ib", "ib_o", dst_kind="desk")
    for mid in ids[:5]:
        rec_opened.insert(cn, mid, "ib_r")
    return ids


@pytest.mark.parametrize("unread_only", [True, False])
@pytest.mark.parametrize("lim", [1, 3, 7, 100, 0, -4])
@pytest.mark.parametrize("desk", ["ib_r", "ib_o", "ib_none"])
def test_page_matches_the_legacy_rule(cn, box, desk, unread_only, lim):
    body = {} if unread_only else {"all": True}
    if lim:
        body["limit"] = lim
    got = [int(m["id"]) for m in rpc._h_inbox(_Book(cn), body, "ib", desk)]
    assert got == _legacy(cn, desk, unread_only, lim)


def test_unread_is_newest_first_and_moves_after_a_mark(cn, box):
    first = [int(m["id"]) for m in rpc._h_inbox(_Book(cn), {"limit": 2}, "ib", "ib_r")]
    assert first == [box[11], box[10]]
    rec_opened.insert(cn, box[11], "ib_r")
    nxt = [int(m["id"]) for m in rpc._h_inbox(_Book(cn), {"limit": 2}, "ib", "ib_r")]
    assert nxt == [box[10], box[9]]


def test_all_is_newest_first_and_keeps_opened(cn, box):
    got = [int(m["id"]) for m in rpc._h_inbox(_Book(cn), {"all": True, "limit": 4}, "ib", "ib_r")]
    assert got == sorted(box, reverse=True)[:4]
    every = [int(m["id"]) for m in rpc._h_inbox(_Book(cn), {"all": True}, "ib", "ib_r")]
    assert set(box[:5]) <= set(every)


def test_opened_is_per_desk(cn, box):
    # ib_o was never marked: box[0] (opened by ib_r) is still unread for ib_o.
    got = [int(m["id"]) for m in rpc._h_inbox(_Book(cn), {}, "ib", "ib_o")]
    assert box[0] in got


def test_rows_carry_body_and_sender(cn, box):
    m = rpc._h_inbox(_Book(cn), {"limit": 1}, "ib", "ib_o")[0]
    assert m["body"].startswith("letter ") and m["sender"]["deskId"] == "ib_s"
    assert {"deskId": "ib_o", "receipt": 0} in [{k: t[k] for k in ("deskId", "receipt")} for t in m["mail_tos"]]


def test_unread_page_drives_from_the_index(cn, box):
    cur = cn.cursor(dictionary=True)
    try:
        cur.execute("SELECT id FROM name WHERE type='desk' AND name='ib_r'")
        did = cur.fetchone()["id"]
        cur.execute(
            "EXPLAIN SELECT id FROM mail_to WHERE type='mail' AND desk_id=%s AND opened IS NULL ORDER BY id DESC LIMIT 100",
            (did,),
        )
        row = cur.fetchall()[0]
    finally:
        cur.close()
    assert row["key"] == "idx_desk_unread"
    assert "filesort" not in str(row.get("Extra") or "")
