# -*- coding: utf-8 -*-
"""One seat for mill connect and for a desk command.

The socket open, the seat status, a single blocking command, and the release
live here. mill connect holds the seat. A command that cannot see a sit opens
one, sends that command, and releases the bearer. The office sees the same
command frame either way.
"""
from __future__ import annotations

from agent_coord.client.seat.session import borrow, command, hold
from agent_coord.client.seat.status import Status, look, other_holder

__all__ = [
    "Status",
    "borrow",
    "command",
    "hold",
    "look",
    "other_holder",
]
