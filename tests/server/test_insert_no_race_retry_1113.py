# -*- coding: utf-8 -*-
"""Card 1113 / F-insert-seat-lock-order: the concurrent-insert race runs once, with no retry.

The deadlock card 1011 retried around was a product S-to-X lock upgrade on the filing
desk's seat row. The todo insert now takes that seat first, so a retry would only hide
a regression.
"""
from __future__ import annotations

from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "tests/server/records/test_insert_payload_first_216.py"


def test_concurrent_insert_race_has_no_retry() -> None:
    text = SRC.read_text(encoding="utf-8")
    body = text.split("def test_concurrent_inserts_get_distinct_ids_without_office_lock", 1)[1].split("\ndef ", 1)[0]
    assert "for attempt in" not in body
    assert "1213" not in body
    assert "assert not errs, errs" in body
