# -*- coding: utf-8 -*-
"""Local stall, resume, and pattern notices. The pattern text stays here."""
from __future__ import annotations


class Notices:
    def __init__(self, pattern: str | None, quiet_s: float) -> None:
        self.pattern = pattern or ""
        self.quiet_s = quiet_s if quiet_s and quiet_s > 0 else 0.0
        self.matched = False
        self.stalled = False
        self.tail = ""
        self.last_total = 0
        self.last_change = 0.0
        self.started = False

    def start(self, now: float) -> None:
        self.started = True
        self.last_change = now

    def feed(self, text: str, total: int, now: float) -> list[tuple[str, str]]:
        """Return (kind, cause) pairs. Cause is a class word, not the pattern."""
        if not self.started:
            self.start(now)
        out: list[tuple[str, str]] = []
        if text and self.pattern and not self.matched:
            self.tail = (self.tail + text)[-4096:]
            if self.pattern in self.tail:
                self.matched = True
                out.append(("match", "pattern"))
        if total != self.last_total:
            self.last_total = total
            self.last_change = now
            if self.stalled:
                self.stalled = False
                out.append(("resume", "output"))
        elif (
            self.quiet_s
            and not self.stalled
            and (now - self.last_change) >= self.quiet_s
        ):
            self.stalled = True
            out.append(("stall", "quiet"))
        return out
