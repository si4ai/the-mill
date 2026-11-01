# -*- coding: utf-8 -*-
"""Card 1011 / F-insert-deadlock-retry: deadlock race retries twice (attempt < 2).

Validator: the retry loop must be attempt < 2 (or equivalent), not attempt == 0.
Seed 181202869 failed after a single retry under InnoDB 1213.
"""
from __future__ import annotations

from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "tests/server/records/test_insert_payload_first_216.py"


def test_concurrent_insert_deadlock_retries_twice() -> None:
    text = SRC.read_text(encoding="utf-8")
    assert "attempt < 2" in text, "retry bound must be attempt < 2 (card 1011; seed 181202869)"
    assert "attempt == 0" not in text, "attempt == 0 only retries once"
    assert "for attempt in range(3)" in text
