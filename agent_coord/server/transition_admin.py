"""card 1098: transition compress config + admin summary (wall admin pane)."""
from __future__ import annotations

from typing import Any


def compress_packet() -> dict[str, Any]:
    """Office compress-vs-capture setting for Admin / board_packet."""
    from agent_coord.config import (
        DEFAULT_TRANSITION_PAIRS,
        settings,
        transition_mode,
        transition_pairs,
    )

    # stable display: prefer a/b with sorted ends
    pretty: list[str] = []
    for typ, states in sorted(transition_pairs(), key=lambda x: (x[0], sorted(x[1]))):
        ends = sorted(states)
        if len(ends) == 1:
            pretty.append(f"{typ}:{ends[0]}/{ends[0]}")
        else:
            pretty.append(f"{typ}:{ends[0]}/{ends[1]}")
    return {
        "mode": transition_mode(),
        "pairs": pretty,
        "pairs_raw": str(settings().get("transition_pairs") or DEFAULT_TRANSITION_PAIRS),
        "default_pairs": DEFAULT_TRANSITION_PAIRS,
        "note": (
            "compress (default): two-state cycles share one transition row with count n "
            "(odd=at to_state, even=at from_state). capture: every flip is its own row."
        ),
    }


def set_compress(data: dict[str, Any]) -> dict[str, Any]:
    """Apply mode and/or pairs from an Admin POST body."""
    from agent_coord.config import set_transition_compress

    mode = data.get("mode", data.get("transition_mode"))
    pairs = data.get("pairs", data.get("transition_pairs"))
    if mode is None and pairs is None:
        from agent_coord.helpers.errors import CoordError

        raise CoordError("transition: pass mode and/or pairs")
    out = set_transition_compress(
        mode=None if mode is None else str(mode),
        pairs=None if pairs is None else str(pairs),
    )
    return {**compress_packet(), **out}


def analysis(cn, *, limit: int = 20) -> dict[str, Any]:
    """Small transition-table summary for the admin pane."""
    cur = cn.cursor()
    try:
        cur.execute(
            "SELECT activity_type, COUNT(*) AS rows_n, COALESCE(SUM(n), COUNT(*)) AS events_n"
            " FROM transition GROUP BY activity_type ORDER BY activity_type"
        )
        by_type = [
            {"activity_type": r[0], "rows": int(r[1]), "events": int(r[2])}
            for r in (cur.fetchall() or [])
        ]
        cur.execute(
            "SELECT activity_type, from_state, to_state, n, at"
            " FROM transition WHERE n > 1 ORDER BY n DESC, at DESC LIMIT %s",
            (max(1, min(int(limit), 100)),),
        )
        compressed = [
            {
                "activity_type": r[0],
                "from_state": r[1],
                "to_state": r[2],
                "n": int(r[3]),
                "at": r[4].isoformat(sep=" ") if hasattr(r[4], "isoformat") else str(r[4]),
            }
            for r in (cur.fetchall() or [])
        ]
        cur.execute("SELECT COUNT(*), COALESCE(SUM(n),0) FROM transition")
        row = cur.fetchone() or (0, 0)
        total_rows, total_events = int(row[0] or 0), int(row[1] or 0)
        return {
            "total_rows": total_rows,
            "total_events": total_events,
            "saved_rows": max(0, total_events - total_rows),
            "by_type": by_type,
            "top_compressed": compressed,
        }
    except Exception as e:
        return {
            "total_rows": 0,
            "total_events": 0,
            "saved_rows": 0,
            "by_type": [],
            "top_compressed": [],
            "error": str(e)[:200],
        }
    finally:
        cur.close()
