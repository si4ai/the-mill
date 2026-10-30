"""Wall /api/howto - pointer at docs/. Not a second mill manual."""
from __future__ import annotations

from typing import Any

API_VERSION = "1"


def howto(*, audience: str = "") -> dict[str, Any]:
    del audience
    return {
        "api": API_VERSION,
        "docs": "docs/protocol/commands.md",
        "skill": "docs/protocol/skill.md",
        "host": "docs/install/HOST.md",
        "join": "docs/JOIN.md",
        "usecases": "docs/protocol/usecases.md",
        "print": "mill help | mill briefing usecases|join|host|human",
    }
