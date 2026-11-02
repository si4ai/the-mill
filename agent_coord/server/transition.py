"""Transition helper (card 1022). Enums and edges live in transition_enums."""
from __future__ import annotations

from agent_coord.server.transition_enums import (
    ALLOWED_TRANSITIONS,
    AMBIGUOUS_MAP_NOTES,
    ActivityType,
    Reason,
    State,
    UnknownTransition,
    WakeCause,
    check_edge,
    put,
)

# Back-compat alias used by early 1022 drafts.
ALLOWED_EDGES = ALLOWED_TRANSITIONS

__all__ = [
    "ALLOWED_TRANSITIONS",
    "ALLOWED_EDGES",
    "AMBIGUOUS_MAP_NOTES",
    "ActivityType",
    "Reason",
    "State",
    "UnknownTransition",
    "WakeCause",
    "check_edge",
    "put",
]
