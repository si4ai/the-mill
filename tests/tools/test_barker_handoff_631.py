"""#631 a Grok Bot routine run has no tool to message another Grok Bot agent,
so the barker routine cannot send the wake itself. It hands each mapped wake
to the barker bot's main chat, which sends the fixed wake text to the mapped
agent; the routine logs result=handoff-parent. The kit states the cost (one
routine run plus one parent turn per wake) and that the barker is a pattern
for cold testers while most bots arm their own webhook."""
from __future__ import annotations

from pathlib import Path

KIT = Path(__file__).resolve().parents[2] / "docs/dev/barker-kit.md"


def _recipe() -> str:
    t = KIT.read_text(encoding="utf-8")
    start = t.index("## barker routing")
    end = t.index("Tradeoffs:", start)
    return t[start : t.index("\n\n", end) if "\n\n" in t[end:] else len(t)]


def test_the_routine_hands_off_to_the_main_chat():
    r = _recipe()
    assert "has no tool to message another Grok Bot agent" in r
    assert "hand the wake to this bot's main chat" in r
    assert "result=handoff-parent" in r
    assert "the main chat sends the mapped agent exactly" in r
    # the routine itself never claims to send the wake
    assert "Otherwise send that agent exactly" not in r


def test_the_cost_and_the_scope_are_stated():
    # cost is in the tradeoffs paragraph (inside _recipe); scope is in the kit intro
    r = _recipe()
    t = KIT.read_text(encoding="utf-8")
    assert "one routine run plus one parent turn" in r
    assert "a pattern for cold testers" in t
    assert "most bots arm their own webhook" in t


def test_the_guide_stays_ascii():
    assert KIT.read_text(encoding="utf-8").isascii()
