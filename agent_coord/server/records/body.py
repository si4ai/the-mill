"""Card 1133: the text of a letter or a card, its replace and its history (sp_body.sql).

replace() is the one write: mill_body_replace keeps the old text in activity_history and refuses with
body:stale unless ``expected`` is the stamp the caller read (body_updated, or created when never edited).
"""

from __future__ import annotations

from typing import Any

from agent_coord.const import CONST_DESK

from .db import call

KINDS = ("mail", "todo")


def replace(cn, kind: str, item_id: int, desk: str, text: str, expected: Any) -> dict[str, Any]:
    """Replace the text; returns history_id, body_updated, body_updater_id, old_updated, op=replaced."""
    from agent_coord.server.records.name import bare

    rows = call(cn, "mill_body_replace", [kind, int(item_id), bare(desk, CONST_DESK), text, expected])
    return rows[0] if rows else {}


def history(cn, kind: str, item_id: int) -> list[dict[str, Any]]:
    """The old texts of one item, oldest first."""
    return call(cn, "mill_body_history", [kind, int(item_id)])
