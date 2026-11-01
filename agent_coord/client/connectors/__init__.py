"""Vendor poke after mill-wall fan-out. Spawn map first; vendor is leftover."""
from __future__ import annotations

from typing import Any, Callable

from . import antigravity, claude, grok_bot, grok_build, kimi, openai_agents
from .spawn import skip_ping, spawn_hint

CONNECTORS = {
    grok_build.VENDOR: grok_build.poke,
    grok_bot.VENDOR: grok_bot.poke,
    antigravity.VENDOR: antigravity.poke,
    claude.VENDOR: claude.poke,
    kimi.VENDOR: kimi.poke,
    openai_agents.VENDOR: openai_agents.poke,
}


def poke(vendor: str, hint: dict[str, Any]) -> bool:
    """Run the vendor poke. True when a chat-wake path ran; False when not (card 985)."""
    if skip_ping(hint):
        return False
    if spawn_hint(hint):
        return True
    fn: Callable[[dict[str, Any]], Any] | None = CONNECTORS.get((vendor or "").strip().lower())
    if fn is None:
        raise NotImplementedError(f"no mill connector for vendor={vendor!r}")
    rang = fn(hint)
    # Connectors that still return None did some volunteer print; treat as no chat wake.
    return bool(rang)
