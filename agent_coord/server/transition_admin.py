"""card 1098: transition compress config + admin summary (wall admin pane)."""
from __future__ import annotations

from typing import Any


_SINCE_SQL = {
    "24h": " AND at >= (UTC_TIMESTAMP() - INTERVAL 24 HOUR)",
    "7d": " AND at >= (UTC_TIMESTAMP() - INTERVAL 7 DAY)",
}
_SINCE_MAIL = {
    "24h": " AND created >= (UTC_TIMESTAMP() - INTERVAL 24 HOUR)",
    "7d": " AND created >= (UTC_TIMESTAMP() - INTERVAL 7 DAY)",
}


def _since_key(since: str | None) -> str | None:
    raw = str(since or "").strip().lower()
    if not raw:
        return None
    if raw in _SINCE_SQL:
        return raw
    return None


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


def _pair_ends(states: frozenset[str]) -> tuple[str, str]:
    ends = sorted(states)
    if len(ends) == 1:
        return ends[0], ends[0]
    return ends[0], ends[1]


def _wake_stats(cur, where: str) -> list[dict[str, Any]]:
    """label/value rows from transition + mail_to (real counts only)."""
    out: list[dict[str, Any]] = []

    def add(label: str, value: int) -> None:
        out.append({"label": label, "value": int(value)})

    cur.execute(
        "SELECT reason, COUNT(*) FROM transition"
        " WHERE activity_type='wake'" + where + " GROUP BY reason"
    )
    by_reason = {str(r[0]): int(r[1]) for r in (cur.fetchall() or [])}
    add("queued", by_reason.get("wake_queue", 0))
    add("sent", by_reason.get("wake_sent", 0))
    add("missed", by_reason.get("wake_owed", 0))
    add("done", by_reason.get("wake_done", 0))

    # auto wake-done: W9 meta.auto=1 (card 1098 item 5)
    cur.execute(
        "SELECT COUNT(*) FROM transition"
        " WHERE activity_type='wake' AND reason='wake_done'"
        " AND CAST(JSON_UNQUOTE(JSON_EXTRACT(meta,'$.auto')) AS UNSIGNED)=1"
        + where
    )
    row = cur.fetchone() or (0,)
    add("auto_done", int(row[0] or 0))

    # receipt opened / unopened from mail_to (card 1093); window on created
    mail_where = ""
    if "INTERVAL 24 HOUR" in where:
        mail_where = _SINCE_MAIL["24h"]
    elif "INTERVAL 7 DAY" in where:
        mail_where = _SINCE_MAIL["7d"]
    cur.execute(
        "SELECT"
        " SUM(receipt=1 AND opened IS NULL),"
        " SUM(receipt=1 AND opened IS NOT NULL)"
        " FROM mail_to WHERE type='mail'" + mail_where
    )
    row = cur.fetchone() or (0, 0)
    add("receipt_unopened", int(row[0] or 0))
    add("receipt_opened", int(row[1] or 0))
    return out


def analysis(cn, *, limit: int = 20, since: str | None = None) -> dict[str, Any]:
    """Small transition-table summary for the admin pane.

    Optional since: '24h' or '7d' (else all rows). analysis.error is the only
    failure signal; on success the key is absent.
    """
    from agent_coord.config import transition_pairs

    sk = _since_key(since)
    where = _SINCE_SQL[sk] if sk else ""
    cur = None
    try:
        cur = cn.cursor()
        cur.execute(
            "SELECT activity_type, COUNT(*) AS rows_n, COALESCE(SUM(n), COUNT(*)) AS events_n"
            " FROM transition WHERE 1=1" + where + " GROUP BY activity_type ORDER BY activity_type"
        )
        by_type = []
        for r in cur.fetchall() or []:
            rows_n, events_n = int(r[1]), int(r[2])
            by_type.append(
                {
                    "activity_type": r[0],
                    "rows": rows_n,
                    "events": events_n,
                    "saved_rows": max(0, events_n - rows_n),
                }
            )

        # Per configured compress pair (include zero-fire pairs).
        cur.execute(
            "SELECT activity_type, from_state, to_state,"
            " COUNT(*) AS rows_n, COALESCE(SUM(n), COUNT(*)) AS events_n"
            " FROM transition WHERE 1=1" + where
            + " GROUP BY activity_type, from_state, to_state"
        )
        fired: dict[tuple[str, str, str], tuple[int, int]] = {}
        for r in cur.fetchall() or []:
            typ, fr, to = str(r[0]), str(r[1]), str(r[2])
            fired[(typ, fr, to)] = (int(r[3]), int(r[4]))

        by_pair: list[dict[str, Any]] = []
        for typ, states in sorted(transition_pairs(), key=lambda x: (x[0], sorted(x[1]))):
            a, b = _pair_ends(states)
            rows_n = events_n = 0
            # undirected: sum both directions (same-state counted once)
            seen: set[tuple[str, str]] = set()
            for fr, to in ((a, b), (b, a)):
                key = (fr, to)
                if key in seen:
                    continue
                seen.add(key)
                got = fired.get((typ, fr, to))
                if got:
                    rows_n += got[0]
                    events_n += got[1]
            by_pair.append(
                {
                    "activity_type": typ,
                    "from_state": a,
                    "to_state": b,
                    "rows": rows_n,
                    "events": events_n,
                    "saved_rows": max(0, events_n - rows_n),
                }
            )

        cur.execute(
            "SELECT activity_type, from_state, to_state, n, at"
            " FROM transition WHERE n > 1" + where + " ORDER BY n DESC, at DESC LIMIT %s",
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
        cur.execute(
            "SELECT COUNT(*), COALESCE(SUM(n),0) FROM transition WHERE 1=1" + where
        )
        row = cur.fetchone() or (0, 0)
        total_rows, total_events = int(row[0] or 0), int(row[1] or 0)
        wake = _wake_stats(cur, where)
        out: dict[str, Any] = {
            "total_rows": total_rows,
            "total_events": total_events,
            "saved_rows": max(0, total_events - total_rows),
            "by_type": by_type,
            "by_pair": by_pair,
            "top_compressed": compressed,
            "wake": wake,
        }
        if sk:
            out["since"] = sk
        return out
    except Exception as e:
        return {
            "total_rows": 0,
            "total_events": 0,
            "saved_rows": 0,
            "by_type": [],
            "by_pair": [],
            "top_compressed": [],
            "wake": [],
            "error": str(e)[:200],
        }
    finally:
        if cur is not None:
            cur.close()


def glance_block(cn) -> dict[str, Any]:
    """Read-only transition summary for the glance packet (trusted human readers).

    Same analysis the Admin 'transition' read returns, for all rows, 24h and 7d,
    plus the current mode and pairs. The mode/pairs change stays the gated write.
    The glance seal drops an 'error' key, so a failed window is marked
    stored=False and carries no figures.
    """
    cfg = compress_packet()
    windows: dict[str, Any] = {}
    for key, since in (("all", None), ("24h", "24h"), ("7d", "7d")):
        got = analysis(cn, limit=10, since=since)
        if got.get("error"):
            windows[key] = {"stored": False}
        else:
            got["stored"] = True
            windows[key] = got
    return {
        "mode": cfg["mode"],
        "pairs": cfg["pairs"],
        "pairs_state": pairs_state(),
        "windows": windows,
    }


def pairs_state() -> list[dict[str, Any]]:
    """Every default pair plus any configured pair, with whether it compresses.

    A pair on the configured list compresses; a pair off it writes every flip.
    A switched-off default pair still gets a row so the Wall can show a toggle.
    """
    from agent_coord.config import DEFAULT_TRANSITION_PAIRS, transition_pairs

    def parse(raw: str) -> set[tuple[str, frozenset[str]]]:
        out: set[tuple[str, frozenset[str]]] = set()
        for part in raw.split(","):
            typ, _, rest = part.strip().partition(":")
            a, _, b = rest.partition("/")
            typ, a, b = typ.strip().lower(), a.strip().lower(), b.strip().lower()
            if typ and a and b:
                out.add((typ, frozenset({a, b})))
        return out

    on = set(transition_pairs())
    rows = []
    for typ, states in sorted(on | parse(DEFAULT_TRANSITION_PAIRS), key=lambda x: (x[0], sorted(x[1]))):
        a, b = _pair_ends(states)
        rows.append(
            {
                "pair": f"{typ}:{a}/{b}",
                "activity_type": typ,
                "from_state": a,
                "to_state": b,
                "compress": (typ, states) in on,
            }
        )
    return rows
