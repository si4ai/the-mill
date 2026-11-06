"""Card #279: docs teach only the shipped connect, connect-wait and reply forms.

Regression row F27 (grok-foreground-shipped-forms).
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STALE = (
    re.compile(r"--office OFFICE-ALIAS"),
    re.compile(r"connect(?:-wait)? PROJECT (?:YOUR-)?DESK"),
    re.compile(r"\breply (?:MAIL_ID|\d+|<[^>]+>) [\"']"),
)


def _docs():
    return sorted((ROOT / "docs").rglob("*.md"))


def test_no_stale_forms_in_docs():
    hits = []
    for p in _docs():
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if any(rx.search(line) for rx in STALE):
                hits.append(f"{p.relative_to(ROOT)}:{i}")
    assert hits == []


def test_grok_foreground_teaches_the_shipped_forms():
    doc = (ROOT / "docs" / "protocol" / "grok-foreground.md").read_text(encoding="utf-8")
    assert "mill connect-wait YOUR-DESK" in doc
    assert "python -m agent_coord reply" in doc   # doc teaches reply, not connect
    assert "reply MAIL_ID --body-file" in doc
    assert "Regression row F27 (grok-foreground-shipped-forms)" in doc
