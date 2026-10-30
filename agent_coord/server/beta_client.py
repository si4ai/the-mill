"""Client-lane rules for card 866.

done_when and pass evidence are stored by the server. This module shapes the
glance, computed live by uc_a6_glance, which stays a clean refusal until that read is installed.
"""
from __future__ import annotations

from typing import Any

from agent_coord.helpers.errors import CoordError

ACTIVITY_CAP = 30

# The glance row's keys: the reply shape the client reads (the vote count went with the vote table).
_CACHE_KEYS = (
    "id",
    "at",
    "refresh_us",
    "present",
    "held",
    "open_n",
    "claimed_n",
    "parked_n",
    "shipped_n",
    "done_n",
    "letters_1d",
    "card_moves_1d",
    "doings_1d",
    "holds_1d",
    "points_1d",
)
_ACTIVITY_KEYS = ("seq", "at", "kind", "ref", "desk")
_KINDS = frozenset({"letter", "card", "doing", "hold", "score"})


def shape_glance(cache_rows: list[dict] | None, activity_rows: list[dict] | None) -> dict[str, Any]:
    """Two sets. No office-wide unread. Activity is the newest 30."""
    src = cache_rows[0] if cache_rows else {}
    if not isinstance(src, dict):
        src = {}
    cache = {key: src.get(key) for key in _CACHE_KEYS}
    activity: list[dict[str, Any]] = []
    for row in list(activity_rows or [])[:ACTIVITY_CAP]:
        if not isinstance(row, dict):
            continue
        kind = str(row.get("kind") or "")
        if kind not in _KINDS:
            # Card 876: a newer kind must not fail the glance. Skip that row.
            continue
        activity.append({key: row.get(key) for key in _ACTIVITY_KEYS})
    return {"cache": cache, "activity": activity}


def read_glance(cn) -> dict[str, Any]:
    """Call uc_a6_glance (computed on each read, no cache) and keep its two result sets apart.

    Until a book defines that procedure (BETA-CHANGES.md, "Not in any book yet") this refuses with
    "the glance is not installed".
    """
    cur = cn.cursor(dictionary=True)
    sets: list[list[dict]] = []
    try:
        cur.execute("CALL uc_a6_glance()")
        for _ in range(4):
            if getattr(cur, "with_rows", False):
                sets.append(list(cur.fetchall()))
            else:
                sets.append([])
            nxt = getattr(cur, "nextset", None)
            if nxt is None or not nxt():
                break
    except CoordError:
        raise
    except Exception as exc:
        msg = str(exc).lower()
        if "1305" in msg or "does not exist" in msg or "doesn't exist" in msg:
            raise CoordError("glance: the glance is not installed") from exc
        raise CoordError("glance: the glance could not be read") from exc
    finally:
        try:
            cur.close()
        except Exception:
            pass
    cache = sets[0] if sets else []
    activity = sets[1] if len(sets) > 1 else []
    return shape_glance(cache, activity)
