"""Transition edges and a thin put helper (card 1022).

ALLOWED_EDGES is the one list for model checks (spin). Keep it identical to the
IF chain in mill_transition_put (sp_transition.sql). Later cards (980, 981, 982,
970, 1002) call put(); this card ships the helper only.
"""
from __future__ import annotations

from typing import Any

# (activity_type, from_state, to_state) - from_state '' means create / no prior.
ALLOWED_EDGES: frozenset[tuple[str, str, str]] = frozenset(
    {
        ("wake", "", "queued"),
        ("wake", "queued", "delivered"),
        ("wake", "delivered", "taken"),
        ("wake", "taken", "done"),
        ("wake", "taken", "wasted"),
        ("mail", "", "sent"),
        ("mail", "sent", "read"),
        ("todo", "", "open"),
        ("todo", "open", "claimed"),
        ("todo", "claimed", "shipped"),
        ("todo", "shipped", "done"),
        ("hold", "", "held"),
        ("hold", "held", "free"),
        ("doing", "", "focus"),
        ("doing", "focus", "clear"),
        ("score", "", "published"),
    }
)


class UnknownTransition(ValueError):
    """Emitter refused: pair not in ALLOWED_EDGES."""


def check_edge(activity_type: str, from_state: str, to_state: str) -> None:
    fr = from_state or ""
    to = to_state or ""
    if (activity_type, fr, to) not in ALLOWED_EDGES:
        raise UnknownTransition(
            f"unknown transition edge ({activity_type!r}, {fr!r}, {to!r})"
        )


def put(
    cn,
    *,
    activity_type: str,
    activity_id: int,
    from_state: str,
    to_state: str,
    reason: str,
    desk_id: int | None = 0,
    role: str = "actor",
    join_key: str | None = None,
    meta: Any = None,
) -> None:
    """Insert one transition via mill_transition_put. desk_id None/omitted -> System (0)."""
    import json

    from agent_coord.server.records.db import call

    check_edge(activity_type, from_state, to_state)
    meta_arg = None if meta is None else (meta if isinstance(meta, str) else json.dumps(meta))
    call(
        cn,
        "mill_transition_put",
        [
            activity_type,
            int(activity_id),
            from_state or "",
            to_state,
            reason,
            0 if desk_id is None else int(desk_id),
            role or "actor",
            join_key,
            meta_arg,
        ],
    )
