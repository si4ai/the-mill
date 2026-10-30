"""Closed vocabulary for the mill book.

name.type and activity.type are stored as these strings. tables.sql is the
ENUM spelling in MySQL. This module is the spelling for the Python process.
"""

from __future__ import annotations

# name.type
CONST_DESK = "desk"
# A roster is an unordered list of desks; every member is equal (0.7.0).
CONST_ROSTER = "roster"
CONST_LABEL = "label"
CONST_TREE = "tree"
CONST_RES = "res"

# Call aliases. They are not stored.
CONST_ALIAS_PROJ = "proj"
CONST_ALIAS_FILE = "file"
CONST_ALIAS_RESOURCE = "resource"

NAME_TYPES = (
    CONST_DESK,
    CONST_ROSTER,
    CONST_LABEL,
    CONST_TREE,
    CONST_RES,
)

# activity.type, and the payload type that points at an activity
CONST_MAIL = "mail"
CONST_TODO = "todo"
CONST_DOING = "doing"
CONST_HOLD = "hold"
CONST_SCORE = "score"

ACTIVITY_TYPES = (
    CONST_MAIL,
    CONST_TODO,
    CONST_DOING,
    CONST_HOLD,
    CONST_SCORE,
)

# Dictionary kind. Not an activity type and not a watcher type.
CONST_WATCH_NAME = "name"

# Seeds. Office is name id 1. Admin is name id 2.
CONST_OFFICE = "Office"
CONST_ADMIN = "Admin"
