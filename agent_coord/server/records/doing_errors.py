"""Card 1303: doing errors per desk, read at request time from tw transitions. No writes, no wakes.

A score brings attention to what a desk can improve. Each count names a kind of trouble and its
next step:
- failed: a tw run that ended non-zero, by kind: usage (exit 4), git_fatal (exit 128), other_nonzero.
- reruns_2m: a failed run followed by the desk's next run within 2 minutes of its end.
- left_open: a run the office closed (reconcile or sweep) because tw never reported the end.

Windows: last_n (the desk's last N runs, all of them when it has fewer), 7d and 30d; plus hourly
(24) and daily (30) buckets. by_cmd uses the tw_start meta cmd (command word only).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

LAST_N = 100
FAILED_KINDS = ("usage", "git_fatal", "other_nonzero")
KINDS = (*FAILED_KINDS, "reruns_2m", "left_open")
RERUN_S = 120
ITEMS_MAX = 5
BY_CMD_MAX = 5
NEXT = {
    "usage": "exit 4: check the args and paths, and that the tool is set up, before tw runs it",
    "git_fatal": "exit 128: check the git login, branch and identity in that checkout",
    "other_nonzero": "read the first error line in the run log and fix that cause before a rerun",
    "reruns_2m": "a quick rerun after a failure: find the cause first, then add a one-line check for it",
    "left_open": "keep the connect up until tw reports the end; read back mill connected --run",
}
# The command word tw sends on a start (card 1303): a program, plus one subcommand word.
CMD_RE = re.compile(r"[a-z0-9][a-z0-9._+-]{0,31}( [a-z][a-z0-9-]{0,31})?")

_RUNS_SQL = (
    "SELECT s.activity_id AS id, s.at AS start_at, e.at AS end_at, e.reason AS end_reason,"
    " JSON_EXTRACT(e.meta, '$.exit_code') AS ec, JSON_UNQUOTE(JSON_EXTRACT(e.meta, '$.cause')) AS cause,"
    " JSON_UNQUOTE(JSON_EXTRACT(s.meta, '$.cmd')) AS cmd"
    " FROM transition s"
    " LEFT JOIN transition e ON e.activity_type = 'doing' AND e.activity_id = s.activity_id"
    "  AND e.reason IN ('tw_finished', 'tw_failed', 'tw_stale')"
    " WHERE s.desk_id = %s AND s.activity_type = 'doing' AND s.to_state = 'active' AND s.reason = 'tw_start'"
)


def _rows(cn, sql: str, args: tuple) -> list[dict]:
    cur = cn.cursor(dictionary=True)
    try:
        cur.execute(sql, args)
        return [{k: v.decode() if isinstance(v, (bytes, bytearray)) else v for k, v in r.items()}
                for r in cur.fetchall()]
    finally:
        cur.close()


def _int(raw: Any) -> int | None:
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode()
    try:
        return int(raw) if raw is not None and str(raw).strip() not in ("", "null") else None
    except ValueError:
        return None


def kind_of(end_reason: Any, exit_code: Any, cause: Any) -> str | None:
    """The doing-error kind of one ended run: a FAILED_KINDS name, left_open, or None (clean or live)."""
    if end_reason == "tw_stale" or (end_reason == "tw_failed" and cause in ("reconcile", "sweep")):
        return "left_open"
    if end_reason != "tw_failed":
        return None
    code = _int(exit_code)
    return "usage" if code == 4 else "git_fatal" if code == 128 else "other_nonzero"


def _iso(at: Any) -> str | None:
    return at.strftime("%Y-%m-%dT%H:%M:%SZ") if isinstance(at, datetime) else None


def _runs(cn, desk_id: int, since: datetime) -> list[dict]:
    """The desk's runs since SINCE plus its last LAST_N runs, oldest first, each with kind and rerun."""
    recent = _rows(cn, _RUNS_SQL + " AND s.at >= %s", (desk_id, since))
    last = _rows(cn, _RUNS_SQL + " ORDER BY s.at DESC, s.id DESC LIMIT %s", (desk_id, LAST_N))
    by_id = {int(r["id"]): r for r in (*recent, *last)}
    runs = sorted(by_id.values(), key=lambda r: (r["start_at"], int(r["id"])))
    for i, r in enumerate(runs):
        r["kind"] = kind_of(r["end_reason"], r["ec"], r["cause"])
        nxt = runs[i + 1]["start_at"] if i + 1 < len(runs) else None
        r["rerun"] = bool(
            r["kind"] in FAILED_KINDS and r["end_at"] is not None and nxt is not None
            and 0 <= (nxt - r["end_at"]).total_seconds() <= RERUN_S
        )
        cmd = r.get("cmd")
        r["cmd"] = cmd if isinstance(cmd, str) and CMD_RE.fullmatch(cmd) else None
    last_ids = {int(r["id"]) for r in last}
    for r in runs:
        r["in_last"] = int(r["id"]) in last_ids
    return runs


def _count(runs: list[dict]) -> dict[str, Any]:
    failed = {k: 0 for k in FAILED_KINDS}
    items: dict[str, list[int]] = {k: [] for k in KINDS}
    reruns = left = 0
    for r in runs:
        kind = r["kind"]
        if kind in failed:
            failed[kind] += 1
            items[kind].append(int(r["id"]))
        if kind == "left_open":
            left += 1
            items["left_open"].append(int(r["id"]))
        if r["rerun"]:
            reruns += 1
            items["reruns_2m"].append(int(r["id"]))
    return {"runs": len(runs), "failed": failed, "failed_n": sum(failed.values()), "reruns_2m": reruns,
            "left_open": left, "items": {k: v[:ITEMS_MAX] for k, v in items.items()}}


def _by_cmd(runs: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for r in runs:
        if r["cmd"]:
            groups.setdefault(r["cmd"], []).append(r)
    out = []
    for cmd, rows in groups.items():
        c = _count(rows)
        secs = sorted((r["end_at"] - r["start_at"]).total_seconds() for r in rows if r["end_at"] is not None)
        out.append({"cmd": cmd, "runs": c["runs"], "failed": c["failed"], "failed_n": c["failed_n"],
                    "reruns_2m": c["reruns_2m"], "left_open": c["left_open"],
                    "p50_s": round(secs[len(secs) // 2], 1) if secs else None,
                    "max_s": round(secs[-1], 1) if secs else None})
    out.sort(key=lambda g: (-g["failed_n"], -g["runs"], g["cmd"]))
    return out[:BY_CMD_MAX]


def _window(runs: list[dict], anchor: datetime) -> dict[str, Any] | None:
    if not runs:
        return None
    return {**_count(runs), "anchor_at": _iso(anchor), "by_cmd": _by_cmd(runs)}


def _buckets(runs: list[dict], now: datetime, step: timedelta, n: int) -> list[dict]:
    top = now.replace(minute=0, second=0, microsecond=0) if step == timedelta(hours=1) else \
        now.replace(hour=0, minute=0, second=0, microsecond=0)
    out = []
    for i in range(n - 1, -1, -1):
        lo = top - step * i
        c = _count([r for r in runs if lo <= r["start_at"] < lo + step])
        out.append({"start_at": _iso(lo), "runs": c["runs"], "failed": c["failed"],
                    "failed_n": c["failed_n"], "reruns_2m": c["reruns_2m"], "left_open": c["left_open"]})
    return out


def desk_errors(cn, desk_id: int, now: datetime | None = None) -> dict[str, Any]:
    """The doing-error block for one desk (the extra block on its doing.task.end_reason score)."""
    now = now or _utcnow(cn)
    runs = _runs(cn, desk_id, now - timedelta(days=30))
    last = [r for r in runs if r["in_last"]]
    windows: dict[str, Any] = {}
    reason = None
    if last:
        oldest = last[0]["start_at"]
        windows["last_n"] = {**_window(last, oldest), "n": len(last), "span_s": int((now - oldest).total_seconds())}
    else:
        windows["last_n"] = None
        reason = "no tw runs"
    for name, days in (("7d", 7), ("30d", 30)):
        lo = now - timedelta(days=days)
        windows[name] = _window([r for r in runs if r["start_at"] >= lo], lo)
    return {
        "kinds": list(KINDS),
        "next": dict(NEXT),
        "n": LAST_N,
        "reason": reason,
        "windows": windows,
        "reasons": {k: (None if v else "no tw runs in this window") for k, v in windows.items()},
        "hourly": _buckets(runs, now, timedelta(hours=1), 24),
        "daily": _buckets(runs, now, timedelta(days=1), 30),
    }


def exit_count(cn, desk_id: int, doing_id: int) -> dict[str, Any] | None:
    """Card 1303: for a run that just failed, how often this desk hit the same kind (and cmd) in its
    last N runs, this run included; n is the actual total (at most LAST_N). None for a clean run.
    It rides the exit or crash hop reply as "errors" (grok-tui 6946); tw prints it when count > 1."""
    now = _utcnow(cn)
    last = _rows(cn, _RUNS_SQL + " ORDER BY s.at DESC, s.id DESC LIMIT %s", (desk_id, LAST_N))
    this = next((r for r in last if int(r["id"]) == int(doing_id)), None)
    if this is None:
        return None
    kind = kind_of(this["end_reason"], this["ec"], this["cause"])
    if kind not in FAILED_KINDS:
        return None
    cmd = this["cmd"] if isinstance(this["cmd"], str) and CMD_RE.fullmatch(this["cmd"]) else None
    same = [r for r in last if kind_of(r["end_reason"], r["ec"], r["cause"]) == kind
            and (cmd is None or r["cmd"] == cmd)]
    oldest = min(r["start_at"] for r in last)
    return {"kind": kind, "cmd": cmd, "count": len(same), "n": len(last),
            "span_s": int((now - oldest).total_seconds()), "next": NEXT[kind]}


def _utcnow(cn) -> datetime:
    row = _rows(cn, "SELECT UTC_TIMESTAMP(6) AS now", ())
    return row[0]["now"]
