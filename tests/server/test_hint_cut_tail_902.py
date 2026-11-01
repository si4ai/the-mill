"""F-hint-cut-tail: visible cut marker on capped mail HINT/lean bodies (card 902).

Tail counts inside the cap. reason=addressed live wakes carry the whole letter
(up to LETTER_CAP); room wakes and replay/default keep BODY_CAP plus the tail.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agent_coord.server import mail_push
from agent_coord.server.mail_push import BODY_CAP, compact_mail, compact_receipt
from agent_coord.server.records.mail import lean_body, public_mail

ROOT = Path(__file__).resolve().parents[2]
ROW = ROOT / "docs" / "security" / "regression" / "F-hint-cut-tail.md"
MATRIX = ROOT / "docs" / "security" / "REGRESSION-MATRIX.md"
DESTS = [{"desk": "d1", "receipt": 0, "opened": None}]


def _letter(body: str, mid: int = 9021) -> dict:
    return {
        "id": mid,
        "created": "2026-10-31 12:00:00",
        "desk": "builder",
        "sender_roster": "Office",
        "body": body,
    }


@pytest.fixture(scope="module")
def letter_cap() -> int:
    cap = getattr(mail_push, "LETTER_CAP", None)
    assert cap is not None and int(cap) >= 4096
    return int(cap)


def test_row_and_matrix():
    assert ROW.is_file()
    text = MATRIX.read_text(encoding="utf-8")
    assert "F-hint-cut-tail" in text


def test_cut_remaining_matches_unread_chars():
    body = "abcdefghij" * 200  # 2000 chars
    item = compact_mail(_letter(body, 44), DESTS, "d1", reason="room")
    assert item["body_trunc"] is True
    assert item["body_chars"] == 2000
    assert item["read"] == "mill mail-thread 44"
    assert len(item["body"]) <= BODY_CAP
    tail_start = item["body"].rfind("... [cut:")
    assert tail_start >= 0
    prefix = item["body"][:tail_start]
    rest = item["body"][tail_start + len("... [cut: ") :]
    n = int(rest.split(" ", 1)[0])
    assert n == len(body) - len(prefix)
    assert body.startswith(prefix)
    assert "mill mail-thread 44]" in item["body"]


def test_exactly_cap_has_no_tail():
    item = compact_mail(_letter("y" * BODY_CAP), DESTS, "d1", reason="room")
    assert item["body"] == "y" * BODY_CAP
    assert "body_trunc" not in item
    assert "[cut:" not in item["body"]


def test_addressed_carries_whole_letter_up_to_letter_cap(letter_cap: int):
    body = "a" * 3000
    item = compact_mail(_letter(body), DESTS, "d1", reason="addressed")
    assert item["body"] == body
    assert "body_trunc" not in item


def test_addressed_cuts_only_past_letter_cap(letter_cap: int):
    body = "b" * (letter_cap + 50)
    item = compact_mail(_letter(body, 7), DESTS, "d1", reason="addressed")
    assert item["body_trunc"] is True
    assert len(item["body"]) <= letter_cap
    assert "... [cut:" in item["body"]
    assert item["read"] == "mill mail-thread 7"


def test_default_reason_keeps_body_cap_with_tail():
    body = "z" * (BODY_CAP + 10)
    item = compact_mail(_letter(body, 3), DESTS, "d1")
    assert item["body_trunc"] is True
    assert len(item["body"]) <= BODY_CAP
    assert "... [cut:" in item["body"]


def test_receipt_cut_has_tail():
    item = compact_receipt({"id": 7, "body": "r" * (BODY_CAP + 1), "desk": "d1"})
    assert item["body_trunc"] is True
    assert "... [cut:" in item["body"]
    assert item["read"] == "mill mail-thread 7"


def test_lean_body_has_visible_tail():
    text = "m" * 400
    clipped, trunc = lean_body(text, 256, mail_id=55)
    assert trunc is True
    assert "... [cut:" in clipped
    assert "mill mail-thread 55]" in clipped
    assert len(clipped) <= 256


def test_public_mail_lean_sets_chars_and_read():
    row = _letter("q" * 500, mid=88)
    out = public_mail(row, DESTS, lean=True, lean_n=256)
    assert out["body_trunc"] is True
    assert out["body_chars"] == 500
    assert out["read"] == "mill mail-thread 88"
    assert "... [cut:" in out["body"]
