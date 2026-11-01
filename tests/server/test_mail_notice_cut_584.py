"""A MAIL push says when its body was cut and how to read the rest (#584). Regression row F63 (mail-notice-cut).

The live push and the connect sync line carry the same item. A letter that
fits arrives whole; a longer one keeps the list marker (body_trunc, as in
inbox and mail-thread rows) plus body_chars and the exact read command.
"""
from __future__ import annotations

from agent_coord.server import mail_push
from agent_coord.server.mail_push import BODY_CAP, compact_mail, compact_receipt

DESTS = [{"desk": "d1", "receipt": 0, "opened": None}]


def _letter(body: str) -> dict:
    return {"id": 2085, "created": "2026-10-21 06:11:11", "desk": "builder", "sender_roster": "fb-s1", "body": body}


def test_a_typical_lead_letter_arrives_whole():
    body = ("Read all of it before you act on any card. " * 7) + "Card 531 is a decoy: do not work it."
    assert 300 < len(body) <= BODY_CAP
    item = compact_mail(_letter(body), DESTS, "d1")
    assert item["body"] == body
    assert "body_trunc" not in item and "read" not in item


def test_the_cap_keeps_typical_letters_whole():
    assert BODY_CAP >= 1024


def test_a_cut_body_says_so_and_names_the_read():
    body = "x" * (BODY_CAP + 77)
    item = compact_mail(_letter(body), DESTS, "d1")
    assert item["body_trunc"] is True
    assert item["body_chars"] == BODY_CAP + 77
    assert item["read"] == "mill mail-thread 2085"
    assert len(item["body"]) <= BODY_CAP
    assert "... [cut:" in item["body"]
    assert item["body"].endswith("mill mail-thread 2085]")


def test_exactly_the_cap_is_whole():
    item = compact_mail(_letter("y" * BODY_CAP), DESTS, "d1")
    assert len(item["body"]) == BODY_CAP and "body_trunc" not in item


def test_a_receipt_marks_its_cut_too():
    long = compact_receipt({"id": 7, "body": "r" * (BODY_CAP + 1), "desk": "d1"})
    assert long["body_trunc"] is True and long["read"] == "mill mail-thread 7"
    short = compact_receipt({"id": 7, "body": "hi", "desk": "d1"})
    assert short["body"] == "hi" and "body_trunc" not in short


def test_the_stored_sync_row_is_the_marked_item(monkeypatch):
    seen = []
    monkeypatch.setattr(mail_push.rec_mail, "letter_row", lambda cn, mid: _letter("z" * (BODY_CAP + 5)))
    monkeypatch.setattr(mail_push.rec_mail, "to_list", lambda cn, mid: DESTS)
    monkeypatch.setattr("agent_coord.server.push.emit", lambda cn, desk, kind, payload, **kw: seen.append(payload))
    # room member => BODY_CAP preview with visible tail (card 902)
    mail_push.push_mail(None, 2085, room_only={"d1"})
    assert seen and seen[0]["body_trunc"] is True and seen[0]["read"] == "mill mail-thread 2085"
    assert "... [cut:" in seen[0]["body"]
