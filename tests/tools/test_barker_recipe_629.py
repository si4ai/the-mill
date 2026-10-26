"""#629 the Grok Bot guide carries the room barker recipe with the facts a cold
reader needs: the two barker files, one routine per desk (never both), the map
written by the spawner, the log path, the fixed wake message, and that a
desk that must see room copies arms --wake-on all, with no scheduled check beside the webhook. Plain ASCII, no real URL or key."""
from __future__ import annotations

from pathlib import Path

GUIDE = Path(__file__).resolve().parents[2] / "docs/protocol/models/grok-bot/SKILL.md"


def _text() -> str:
    return GUIDE.read_text(encoding="utf-8")


def test_the_recipe_names_every_fact():
    t = _text()
    for fact in (
        "room barker",
        "~/.config/mill-barker/barker_url",
        "~/.config/mill-barker/barker_key",
        "dir 700, files 600",
        "never both",
        "~/.config/mill-barker/map.tsv",
        "never the desk itself",
        "~/.config/mill-barker/barker.log",
        "`Mill wake for DESK on ROSTER (reason R, room X): connect and check your queue`",
        "--wake-on addressed",
        "one wake method per desk: no scheduled check beside the webhook",
        "in chat, mail or a command line",
        "never reads mail",
    ):
        assert fact in t, fact


def test_the_guide_is_ascii_with_no_real_secret():
    t = _text()
    assert t.isascii()
    assert "https://" not in t and "Bearer " not in t.replace("`Authorization: Bearer ...`", "")
