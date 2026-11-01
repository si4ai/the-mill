"""Known gaps in the #238 matrix: case id -> card. Each is xfail(strict=True).

When a card's fix lands, its cases pass and strict xfail turns CI red.
Remove those lines in the same MR as the fix.
"""
from __future__ import annotations

GAPS: dict[str, str] = {
    'create todo parent_type bad_enum': '#238 gap, no card yet: create parent not checked',
    'create todo parent_id unknown': '#238 gap, no card yet: create parent not checked',
    'note project over_length': '#238 gap, no card yet: note project',
    'claim project over_length': '#238 gap, no card yet: claim project',
    'unclaim project over_length': '#238 gap, no card yet: unclaim project',
    'assign project over_length': '#238 gap, no card yet: assign project',
    'assign desk empty': '#238 gap, no card yet: assign desk',
    'assign desk unknown': '#238 gap, no card yet: assign desk',
    'assign desk over_length': '#238 gap, no card yet: assign desk',
    'pass project over_length': '#238 gap, no card yet: pass project',
    'score project unknown': '#238 gap, no card yet: score project',
    'score project over_length': '#238 gap, no card yet: score project',
    'score name over_length': '#238 gap, no card yet: score name',
}
