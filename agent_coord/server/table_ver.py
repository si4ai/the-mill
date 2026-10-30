"""Per-table versions for the wall pane cache.

A write bumps the tables that procedure changes. A read bumps nothing.
push_* and mill_wall_* bump nothing: fanout and the wall score are not pane writes.
"""

from __future__ import annotations

import threading

_lock = threading.Lock()
_versions: dict[str, int] = {}

# Reads whose names do not end in _select, _get, or _list.
_READS = frozenset({
    "mill_activity_bucket",
    "mill_span",
    "mill_between",
    "mill_floor_part",
    "mill_floor_fp",
    "mill_floor_scope_load",
    "mill_tree_subtree",
    "mill_tree_ancestors",
    "mill_tree_watchers",
    "mill_human_open",
    "mill_mail_inbox",
    "mill_todo_page",
})

# Pane name is the /api/v1 path segment. Each pane names the tables it reads.
PANE_TABLES: dict[str, tuple[str, ...]] = {
    "rooms": ("tree", "name", "mail"),
    "mailbox": ("mail", "mail_to", "name", "tree"),
    "tree-mail": ("tree", "mail", "name"),
    "tree-todo": ("tree", "todo", "name"),
    "todos": ("todo", "name"),
    "agents": ("seat", "doing", "name"),
    "scores": ("score", "name"),
    "holds": ("hold", "name"),
    "watchers": ("watcher", "name"),
    "events": ("activity", "name"),
    "names": ("name",),
    "map": ("tree", "mail", "todo", "name"),
    "timeline": ("activity", "name"),
}


def tables_for_proc(name: str) -> tuple[str, ...]:
    """Tables a successful CALL changes. Empty means the cache key stays put."""
    n = (name or "").strip().lower()
    if not n or n in _READS:
        return ()
    if n.endswith(("_select", "_get", "_list")):
        return ()
    if "push" in n.split("_"):
        return ()
    if n.startswith("mill_wall_"):
        return ()
    if n == "mill_mail_open":
        return ("mail_to",)
    if n.startswith("mill_mail_"):
        return ("mail", "mail_to")
    if n.startswith("mill_todo_"):
        return ("todo",)
    if n.startswith("mill_hold_"):
        return ("hold",)
    if n.startswith("mill_join_"):
        return ("seat", "doing")
    if n.startswith("mill_score_"):
        return ("score",)
    if n.startswith("mill_name_"):
        return ("name",)
    if n.startswith("mill_tree_"):
        return ("tree",)
    if n.startswith("mill_label_"):
        return ("label",)
    if n.startswith("mill_watcher_"):
        return ("watcher",)
    if n.startswith("mill_activity_"):
        return ("activity",)
    if n.startswith("mill_member_"):
        return ("member",)
    return ()


def bump(tables: tuple[str, ...] | list[str]) -> None:
    with _lock:
        for table in tables:
            _versions[table] = _versions.get(table, 0) + 1


def version_of(table: str) -> int:
    with _lock:
        return int(_versions.get(table, 0))


def version_stamp(tables: tuple[str, ...] | list[str]) -> str:
    """Stable text for a cache key. A bump of any named table changes it."""
    with _lock:
        return ",".join(f"{table}:{int(_versions.get(table, 0))}" for table in tables)
