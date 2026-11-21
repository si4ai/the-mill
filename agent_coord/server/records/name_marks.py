"""Card 1255: mark a reference to a soft-deleted name, in one place.

A live-choice list (rosters, labels, trees) hides a trashed name. An activity
(todo, mail, hold, doing, wake, score) that still refers to one keeps showing
it, marked. mark_deleted walks a feed or reply payload, collects the name
strings under REF_KEYS, reads which of them are retired (name.deleted) or
trashed (name.trashed) in one SELECT, and gives each dict that refers to one
a sorted ``deleted_names`` list. A dict with no such reference is unchanged
and gets no key. Names are unique across types (card 1163), so a name string
alone says which row it is.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Iterable

# Keys whose value is a name (or a list of names) in feed rows and replies.
REF_KEYS = frozenset(
    {
        "asker", "assigned", "body_updater", "creator", "desk", "deskId", "from",
        "label", "labels", "owner", "project_id", "resource", "roster", "roster_id",
        "sender", "to", "tree", "updated_by", "volunteer",
    }
)
MARK_KEY = "deleted_names"
_log = logging.getLogger(__name__)
_CHUNK = 500

Lookup = Callable[[set[str]], set[str]]


def _names_in(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        v = value.strip()
        if v.startswith("["):  # SQL JSON array text, e.g. a todo's labels
            try:
                value = json.loads(v)
            except ValueError:
                return
        elif v:
            yield v
            return
    if isinstance(value, (list, tuple)):
        for x in value:
            if isinstance(x, str) and x.strip():
                yield x.strip()


def _collect(node: Any, out: set[str]) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            if k in REF_KEYS:
                out.update(_names_in(v))
            if isinstance(v, (dict, list, tuple)):
                _collect(v, out)
    elif isinstance(node, (list, tuple)):
        for x in node:
            _collect(x, out)


def deleted_names(cn, names: set[str]) -> set[str]:
    """Which of these names are retired or trashed (casefolded). One SELECT per 500 names."""
    want = sorted({n for n in names if n})
    hit: set[str] = set()
    cur = cn.cursor()
    try:
        for i in range(0, len(want), _CHUNK):
            part = want[i : i + _CHUNK]
            marks = ",".join(["%s"] * len(part))
            cur.execute(
                "SELECT name FROM name WHERE name IN (" + marks + ")"
                " AND (deleted IS NOT NULL OR trashed IS NOT NULL)",
                tuple(part),
            )
            hit.update(str(r[0]).casefold() for r in cur.fetchall() if r and r[0])
    finally:
        cur.close()
    return hit


def _mark(node: Any, gone: set[str]) -> Any:
    if isinstance(node, dict):
        out = {k: _mark(v, gone) if isinstance(v, (dict, list, tuple)) else v for k, v in node.items()}
        mine = sorted(
            {n for k in REF_KEYS if k in node for n in _names_in(node[k]) if n.casefold() in gone}
        )
        if mine:
            out[MARK_KEY] = mine
        return out
    if isinstance(node, list):
        return [_mark(x, gone) for x in node]
    if isinstance(node, tuple):
        return tuple(_mark(x, gone) for x in node)
    return node


def mark_deleted(cn, payload: Any, *, lookup: Lookup | None = None) -> Any:
    """Return payload with ``deleted_names`` on each dict that refers to a retired or trashed name.

    The input is not changed. No reference, or none deleted: the same payload back.
    """
    names: set[str] = set()
    _collect(payload, names)
    if not names or (cn is None and lookup is None):
        return payload
    try:
        gone = (lookup or (lambda ns: deleted_names(cn, ns)))(names)
    except Exception as e:  # a failed mark never fails the read; the row shows unmarked
        _log.warning("name marks not read: %s", type(e).__name__)
        return payload
    if not gone:
        return payload
    return _mark(payload, gone)
