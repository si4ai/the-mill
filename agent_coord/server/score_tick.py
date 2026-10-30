# -*- coding: utf-8 -*-
"""Publish mill-wall.ticks, mill-desk.idle_verbs, mill-desk.hint_drop from dest logs.

Not a sit keep-alive. Interval minutes, not 15s. Office host KPIs go through
mill_score_admin_upsert (roster Office, owned by the Admin roster; Admin is a
roster, not a desk). Per-desk KPIs use mill_score_upsert on that desk.
mill-wall 500 must not kill this.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from agent_coord.const import CONST_ADMIN, CONST_OFFICE
from agent_coord.config import mill_home
from agent_coord.server.admin.guard import office_name

KPI_TICKS = "mill-wall.ticks"
KPI_IDLE = "mill-desk.idle_verbs"
KPI_DROP = "mill-desk.hint_drop"
KPI_API_N = "mill-wall.api_n"
KPI_API_MS = "mill-wall.api_ms"
KPI_API_BYTES = "mill-wall.api_bytes"
KPI_FLOOR_N = "mill-wall.floor_n"
KPI_FLOOR_MS = "mill-wall.floor_ms"
KPI_FLOOR_BYTES = "mill-wall.floor_bytes"
KPI_WS_PUSH = "mill-wall.ws_push"
KPI_WS_MISS = "mill-wall.ws_miss"
KPI_ERR_N = "mill-wall.err_n"
ROSTER = CONST_OFFICE
OWNER = CONST_ADMIN  # the Admin roster; written only through rec_score.admin_upsert
TARGET = "0"
TARGET_MS = "100"
HOST_KPIS = (
    KPI_API_N,
    KPI_API_MS,
    KPI_API_BYTES,
    KPI_FLOOR_N,
    KPI_FLOOR_MS,
    KPI_FLOOR_BYTES,
    KPI_WS_PUSH,
    KPI_WS_MISS,
    KPI_ERR_N,
)
DESK_KPIS = (KPI_TICKS, KPI_IDLE, KPI_DROP)
_MS = re.compile(r"\bms=([0-9.]+)")
_REQ_B = re.compile(r"\breq_b=(\d+)")
_RESP_B = re.compile(r"\bresp_b=(\d+)")
_HTTP_500 = re.compile(r"\s500\s")
_WS_PUSH = re.compile(r"\bws push\b.*\bok=1\b")
_WS_MISS = re.compile(r"\bfanout miss\b|\bmiss=[1-9]")
_CRASH = re.compile(r"\bserve crash\b|\bTraceback\b", re.I)
HOST_NOTES = {
    KPI_API_N: "mill commands POST /api/mill in window",
    KPI_API_MS: "p95 ms mill commands; target 100",
    KPI_API_BYTES: "mill command req_b+resp_b in window",
    KPI_FLOOR_N: "GET /api/floor in window",
    KPI_FLOOR_MS: "p95 ms GET /api/floor; target 100",
    KPI_FLOOR_BYTES: "GET /api/floor resp_b in window",
    KPI_WS_PUSH: "Hub ws push ok=1 in window",
    KPI_WS_MISS: "Hub fanout miss; target 0",
    KPI_ERR_N: "mill-api 500 + mill-wall-svc crash; target 0",
}
_DESK = re.compile(r"\bdesk=([A-Za-z0-9._-]{1,64})")


def _desk_stored(token: str) -> str:
    return (token or "").strip()

# mill-known book X. mill score-add NAME opts in. Not a product catalog.
WINDOW_S = 3600
EVERY_S = 900
BOOK_SQL: dict[str, tuple[str, str]] = {
    "todo.shipped": (
        "SELECT COUNT(*) FROM todo WHERE status='shipped'",
        "cards shipped (book)",
    ),
    "todo.open": (
        "SELECT COUNT(*) FROM todo WHERE status='open'",
        "cards open (book)",
    ),
    "join.n": ("SELECT COUNT(*) FROM seat", "desks on join (book)"),
    "here.n": ("SELECT COUNT(*) FROM seat", "desks on join (book)"),
    # Informational throughput (activities/h). Target empty like mill-wall.api_n / floor_n.
    "mill-office.activities": (
        f"SELECT COUNT(*) FROM activity WHERE updated >= NOW(6) - INTERVAL {WINDOW_S} SECOND",
        "activity rows touched in last hour (book); informational",
    ),
}
# Book KPIs default target 0; informational ones use empty (no red alarm).
BOOK_TARGET: dict[str, str] = {
    "mill-office.activities": "",
}

# Opt-in book KPIs measured from mill-perf (not SQL). Same score-add gate as BOOK_SQL.
from agent_coord.server.wake_first import (  # noqa: E402
    BOOK_PERF as _WAKE_BOOK_PERF,
    KPI_RETRY,
    KPI_WAKE_MS,
    KPI_WAKE_RPC,
    KPI_WRONG_N,
)
from agent_coord.server.commands_to_done import (  # noqa: E402
    BOOK_PERF as _VTD_BOOK_PERF,
    KPI_COMMANDS_TO_DONE,
)
from agent_coord.server.hold_blocked import (  # noqa: E402
    BOOK_PERF as _HOLD_BOOK_PERF,
    KPI_HOLD_BLOCKED_MS,
)
from agent_coord.server.nest_sor import (  # noqa: E402
    BOOK_PERF as _NEST_BOOK_PERF,
    KPI_NEST_HIT,
    KPI_NEST_REASK,
)
from agent_coord.server.mail_sor import (  # noqa: E402
    BOOK_PERF as _MAIL_BOOK_PERF,
    KPI_MAIL_HIT,
    KPI_MAIL_REASK,
)

BOOK_PERF: dict[str, str] = {
    **_WAKE_BOOK_PERF,
    **_VTD_BOOK_PERF,
    **_HOLD_BOOK_PERF,
    **_NEST_BOOK_PERF,
    **_MAIL_BOOK_PERF,
}

for _kpi in BOOK_PERF:
    BOOK_TARGET.setdefault(_kpi, "")

_TS = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?)Z\s+")
_PERF_OP = re.compile(r"\bop=([^\s]+)")
_API_COMMAND = re.compile(r"\bPOST (?:/mill/v1/|/api/mill/)([a-z0-9-]+)\b", re.I)
_FLOOR = re.compile(r"\bGET /api/floor\b|\bop=api\.floor\b", re.I)
_PERF_DROP = re.compile(r"\bop=ws\.recv\b.*\bdrop=1\b")
_BC_DROP = re.compile(r"\bhint drop desk=")

TICK_OPS = frozenset({"api.mill.heartbeat", "heartbeat"})
IDLE_OPS = frozenset(
    {
        "api.mill.inbox",
        "api.mill.wake",
        "api.mill.peek",
        "api.mill.todo",
        "api.floor",
        "inbox",
        "wake",
        "peek",
        "todo",
        "leftover",
    }
)


def _parse_ts(line: str) -> datetime | None:
    m = _TS.match(line or "")
    if not m:
        return None
    raw = m.group(1)
    if "." not in raw:
        raw = raw + ".000000"
    try:
        return datetime.strptime(raw, "%Y-%m-%dT%H:%M:%S.%f").replace(tzinfo=timezone.utc)
    except ValueError:
        try:
            return datetime.strptime(raw[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            return None


def _in_window(ts: datetime | None, since: datetime) -> bool:
    return ts is not None and ts >= since


def count_perf(text: str, since: datetime) -> tuple[int, int]:
    ticks = 0
    idle = 0
    for line in (text or "").splitlines():
        ts = _parse_ts(line)
        if not _in_window(ts, since):
            continue
        m = _PERF_OP.search(line)
        op = (m.group(1) if m else "").strip()
        if op in TICK_OPS:
            ticks += 1
        if op in IDLE_OPS:
            idle += 1
        if _FLOOR.search(line) and op != "api.floor":
            idle += 1
    return ticks, idle


def _p95(values: list[float]) -> int:
    if not values:
        return 0
    xs = sorted(values)
    i = min(len(xs) - 1, max(0, int(round(0.95 * (len(xs) - 1)))))
    return int(round(xs[i]))

def _p50(values: list[float]) -> int:
    if not values:
        return 0
    xs = sorted(values)
    i = min(len(xs) - 1, max(0, int(round(0.50 * (len(xs) - 1)))))
    return int(round(xs[i]))


_WAKE_FIRST_OP = re.compile(r"\bop=wake\.first_ok\b")
_RPC_N = re.compile(r"\brpc=(\d+)")
_WRONG_N = re.compile(r"\bwrong=(\d+)")
_RETRY_N = re.compile(r"\bretry=(\d+)")
_COMMANDS_TO_DONE_OP = re.compile(r"\bop=card\.verbs_to_done\b")
_COMMANDS_N = re.compile(r"\bverbs=(\d+)")
_HOLD_BLOCKED_OP = re.compile(r"\bop=hold\.blocked\b")
_NEST_HIT_OP = re.compile(r"\bop=nest\.hit\b")
_REASK_N = re.compile(r"\breask=(\d+)")
_MAIL_HIT_OP = re.compile(r"\bop=mail\.hit\b")


def measure_wake_first(text: str, since: datetime) -> tuple[int, int]:
    """p50 ms + p50 rpc from wake.first_ok stamps in window. (0,0) if none."""
    ms_vals: list[float] = []
    rpc_vals: list[float] = []
    for line in (text or "").splitlines():
        ts = _parse_ts(line)
        if not _in_window(ts, since):
            continue
        if not _WAKE_FIRST_OP.search(line):
            continue
        mm = _MS.search(line)
        if mm:
            try:
                ms_vals.append(float(mm.group(1)))
            except ValueError:
                pass
        rm = _RPC_N.search(line)
        if rm:
            try:
                rpc_vals.append(float(rm.group(1)))
            except ValueError:
                pass
    return _p50(ms_vals), _p50(rpc_vals)


def measure_wrong_retry(text: str, since: datetime) -> tuple[int, int]:
    """p50 wrong= + p50 retry= from wake.first_ok stamps in window. (0,0) if none."""
    wrong_vals: list[float] = []
    retry_vals: list[float] = []
    for line in (text or "").splitlines():
        ts = _parse_ts(line)
        if not _in_window(ts, since):
            continue
        if not _WAKE_FIRST_OP.search(line):
            continue
        wm = _WRONG_N.search(line)
        if wm:
            try:
                wrong_vals.append(float(wm.group(1)))
            except ValueError:
                pass
        rm = _RETRY_N.search(line)
        if rm:
            try:
                retry_vals.append(float(rm.group(1)))
            except ValueError:
                pass
    return _p50(wrong_vals), _p50(retry_vals)


def measure_commands_to_done(text: str, since: datetime) -> int:
    """p50 verbs= from card.verbs_to_done stamps in window. 0 if none."""
    vals: list[float] = []
    for line in (text or "").splitlines():
        ts = _parse_ts(line)
        if not _in_window(ts, since):
            continue
        if not _COMMANDS_TO_DONE_OP.search(line):
            continue
        vm = _COMMANDS_N.search(line)
        if vm:
            try:
                vals.append(float(vm.group(1)))
            except ValueError:
                pass
    return _p50(vals)



def measure_hold_blocked(text: str, since: datetime) -> int:
    """sum ms= from hold.blocked stamps in window. 0 if none."""
    total = 0.0
    for line in (text or "").splitlines():
        ts = _parse_ts(line)
        if not _in_window(ts, since):
            continue
        if not _HOLD_BLOCKED_OP.search(line):
            continue
        mm = _MS.search(line)
        if mm:
            try:
                total += float(mm.group(1))
            except ValueError:
                pass
    return int(round(total))


def measure_nest_sor(text: str, since: datetime) -> tuple[int, int]:
    """count nest.hit lines + reask=1 lines in window. (0,0) if none."""
    hits = 0
    reasks = 0
    for line in (text or "").splitlines():
        ts = _parse_ts(line)
        if not _in_window(ts, since):
            continue
        if not _NEST_HIT_OP.search(line):
            continue
        hits += 1
        rm = _REASK_N.search(line)
        if rm:
            try:
                if int(rm.group(1)) >= 1:
                    reasks += 1
            except ValueError:
                pass
    return hits, reasks


def measure_mail_sor(text: str, since: datetime) -> tuple[int, int]:
    """count mail.hit lines + reask=1 lines in window. (0,0) if none."""
    hits = 0
    reasks = 0
    for line in (text or "").splitlines():
        ts = _parse_ts(line)
        if not _in_window(ts, since):
            continue
        if not _MAIL_HIT_OP.search(line):
            continue
        hits += 1
        rm = _REASK_N.search(line)
        if rm:
            try:
                if int(rm.group(1)) >= 1:
                    reasks += 1
            except ValueError:
                pass
    return hits, reasks

def p95_ops(text: str, since: datetime, prefixes: tuple[str, ...]) -> int:
    """p95 ms= for mill-perf lines whose op= starts with one of prefixes."""
    vals: list[float] = []
    for line in (text or "").splitlines():
        ts = _parse_ts(line)
        if not _in_window(ts, since):
            continue
        m = _PERF_OP.search(line)
        op = (m.group(1) if m else "").strip()
        if not any(op == p or op.startswith(p + ".") for p in prefixes):
            continue
        mm = _MS.search(line)
        if not mm:
            continue
        try:
            vals.append(float(mm.group(1)))
        except ValueError:
            pass
    return _p95(vals)


def count_drops(text: str, since: datetime, *, backchannel: bool = False) -> int:
    """Sit FIFO overflow. mill-perf `op=ws.recv drop=1` or mill-backchannel `hint drop`."""
    n = 0
    pat = _BC_DROP if backchannel else _PERF_DROP
    for line in (text or "").splitlines():
        ts = _parse_ts(line)
        if not _in_window(ts, since):
            continue
        if pat.search(line):
            n += 1
    return n


def count_api(text: str, since: datetime) -> tuple[int, int]:
    ticks = 0
    idle = 0
    for line in (text or "").splitlines():
        ts = _parse_ts(line)
        if not _in_window(ts, since):
            continue
        m = _API_COMMAND.search(line)
        command = (m.group(1) if m else "").strip().lower()
        if command in TICK_OPS:
            ticks += 1
        if command in IDLE_OPS:
            idle += 1
        if _FLOOR.search(line):
            idle += 1
    return ticks, idle


def _measure_desks(dest: Path, since: datetime) -> dict[str, dict[str, int]]:
    """Per-desk mill-host X from mill-perf (desk=)."""
    out: dict[str, dict[str, int]] = {}
    perf = dest / "mill-perf.log"
    if not perf.is_file():
        return out
    text = perf.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        ts = _parse_ts(line)
        if not _in_window(ts, since):
            continue
        dm = _DESK.search(line)
        if not dm:
            continue
        who = _desk_stored(dm.group(1))
        row = out.setdefault(who, {KPI_TICKS: 0, KPI_IDLE: 0, KPI_DROP: 0})
        m = _PERF_OP.search(line)
        op = (m.group(1) if m else "").strip()
        if op in TICK_OPS:
            row[KPI_TICKS] += 1
        if op in IDLE_OPS:
            row[KPI_IDLE] += 1
        if _PERF_DROP.search(line):
            row[KPI_DROP] += 1
    return out


def _measure_host(dest: Path, since: datetime) -> dict[str, int]:
    """Office mill-host X from dest logs. Wall SCORE Last."""
    out = {k: 0 for k in HOST_KPIS}
    api = dest / "mill-api.log"
    perf = dest / "mill-perf.log"
    bc = dest / "mill-backchannel.log"
    svc = dest / "mill-wall-svc.log"
    api_text = api.read_text(encoding="utf-8", errors="replace") if api.is_file() else ""
    perf_text = perf.read_text(encoding="utf-8", errors="replace") if perf.is_file() else ""
    bc_text = bc.read_text(encoding="utf-8", errors="replace") if bc.is_file() else ""
    svc_text = svc.read_text(encoding="utf-8", errors="replace") if svc.is_file() else ""
    for line in api_text.splitlines():
        ts = _parse_ts(line)
        if not _in_window(ts, since):
            continue
        req = int(_REQ_B.search(line).group(1)) if _REQ_B.search(line) else 0
        resp = int(_RESP_B.search(line).group(1)) if _RESP_B.search(line) else 0
        if _API_COMMAND.search(line):
            out[KPI_API_N] += 1
            out[KPI_API_BYTES] += req + resp
        if _FLOOR.search(line):
            out[KPI_FLOOR_N] += 1
            out[KPI_FLOOR_BYTES] += resp
        if _HTTP_500.search(line):
            out[KPI_ERR_N] += 1
    if perf_text:
        out[KPI_API_MS] = p95_ops(perf_text, since, ("api.mill", "verb"))
        out[KPI_FLOOR_MS] = p95_ops(perf_text, since, ("api.floor",))
    for line in bc_text.splitlines():
        ts = _parse_ts(line)
        if not _in_window(ts, since):
            continue
        if _WS_PUSH.search(line):
            out[KPI_WS_PUSH] += 1
        if _WS_MISS.search(line):
            out[KPI_WS_MISS] += 1
    for line in svc_text.splitlines():
        ts = _parse_ts(line)
        if ts is not None and not _in_window(ts, since):
            continue
        if _CRASH.search(line):
            out[KPI_ERR_N] += 1
    return out


def measure(*, dest: Path | None = None, window_s: int = WINDOW_S, now: datetime | None = None) -> dict[str, Any]:
    dest = dest or mill_home()
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(seconds=max(60, int(window_s)))
    ticks = 0
    idle = 0
    drops = 0
    perf = dest / "mill-perf.log"
    api = dest / "mill-api.log"
    bc = dest / "mill-backchannel.log"
    if perf.is_file():
        t, i = count_perf(perf.read_text(encoding="utf-8", errors="replace"), since)
        ticks += t
        idle += i
        drops += count_drops(perf.read_text(encoding="utf-8", errors="replace"), since)
    elif api.is_file():
        t, i = count_api(api.read_text(encoding="utf-8", errors="replace"), since)
        ticks += t
        idle += i
    if drops == 0 and bc.is_file():
        drops += count_drops(
            bc.read_text(encoding="utf-8", errors="replace"), since, backchannel=True
        )
    if perf.is_file() and api.is_file():
        # Prefer mill-perf (one line per op). mill-api is the same HTTPS; don't double-count.
        pass
    host = _measure_host(dest, since)
    wake_ms = 0
    wake_rpc = 0
    wrong_n = 0
    retry_n = 0
    commands_to_done = 0
    hold_blocked_ms = 0
    nest_hit_n = 0
    nest_reask_n = 0
    mail_hit_n = 0
    mail_reask_n = 0
    if perf.is_file():
        perf_text = perf.read_text(encoding="utf-8", errors="replace")
        wake_ms, wake_rpc = measure_wake_first(perf_text, since)
        wrong_n, retry_n = measure_wrong_retry(perf_text, since)
        commands_to_done = measure_commands_to_done(perf_text, since)
        hold_blocked_ms = measure_hold_blocked(perf_text, since)
        nest_hit_n, nest_reask_n = measure_nest_sor(perf_text, since)
        mail_hit_n, mail_reask_n = measure_mail_sor(perf_text, since)
    return {
        KPI_TICKS: ticks,
        KPI_IDLE: idle,
        KPI_DROP: drops,
        **host,
        KPI_WAKE_MS: wake_ms,
        KPI_WAKE_RPC: wake_rpc,
        KPI_WRONG_N: wrong_n,
        KPI_RETRY: retry_n,
        KPI_COMMANDS_TO_DONE: commands_to_done,
        KPI_HOLD_BLOCKED_MS: hold_blocked_ms,
        KPI_NEST_HIT: nest_hit_n,
        KPI_NEST_REASK: nest_reask_n,
        KPI_MAIL_HIT: mail_hit_n,
        KPI_MAIL_REASK: mail_reask_n,
        "desks": _measure_desks(dest, since),
        "since": since.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "until": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window_s": int(window_s),
        "dest": str(dest),
    }


def ensure_desk_scores(desk: str) -> dict[str, Any]:
    """Mint mill-host KPI rows for this desk at mill connect. Empty Last, target 0."""
    from agent_coord.server.records import connect
    from agent_coord.server.records import score as rec_score

    who = _desk_stored(desk)
    notes = {
        KPI_TICKS: "this desk extra mill heartbeat while sitting; target 0",
        KPI_IDLE: "this desk idle mill JSON in window; target 0",
        KPI_DROP: "this desk sit FIFO drop=1 in window; target 0",
    }
    cn = connect()
    out: dict[str, Any] = {"ok": True, "desk": who, "rows": []}
    try:
        for kpi in DESK_KPIS:
            rows = rec_score.upsert(cn, office_name(cn), who, kpi, "", TARGET, notes[kpi])
            out["rows"].append({"kpi": kpi, "sql": rows})
    except Exception as e:
        out["ok"] = False
        out["error"] = str(e)[:240]
    finally:
        try:
            cn.close()
        except Exception:
            pass
    return out


def measure_book(cn) -> dict[str, int]:
    """COUNT mill-known book KPIs that already have a score row (opt-in)."""
    cur = cn.cursor()
    out: dict[str, int] = {}
    try:
        cur.execute(
            "SELECT s.kpi FROM score s WHERE s.roster_id=1"
        )
        wanted = {r[0] for r in cur.fetchall() if r and r[0] in BOOK_SQL}
        for kpi in wanted:
            sql, _note = BOOK_SQL[kpi]
            cur.execute(sql)
            rec = cur.fetchone()
            out[kpi] = int(rec[0] if rec else 0)
    except Exception:
        pass
    finally:
        cur.close()
    return out


def score_add(kpi: str, *, target: str = TARGET, note: str = "") -> dict[str, Any]:
    kpi = (kpi or "").strip()
    if (
        kpi not in BOOK_SQL
        and kpi not in BOOK_PERF
        and kpi not in (KPI_TICKS, KPI_IDLE, KPI_DROP) + HOST_KPIS
    ):
        return {
            "ok": False,
            "error": "mill-known only",
            "book": list(BOOK_SQL) + list(BOOK_PERF),
            "perf": [KPI_TICKS, KPI_IDLE, KPI_DROP, *HOST_KPIS],
            "their_x": "mill score NAME value --target",
        }
    from agent_coord.server.records import connect
    from agent_coord.server.records import score as rec_score

    cn = connect()
    try:
        if kpi in BOOK_SQL:
            note_s = (note or BOOK_SQL[kpi][1])[:200]
        elif kpi in BOOK_PERF:
            note_s = (note or BOOK_PERF[kpi])[:200]
        else:
            note_s = (note or "mill-host")[:200]
        # Prefer BOOK_TARGET (may be "") over TARGET/"0" for informational book KPIs.
        if kpi in BOOK_TARGET:
            tgt = BOOK_TARGET[kpi]
        else:
            tgt = str(target) if target != "" else TARGET
        rows = rec_score.admin_upsert(cn, kpi, "", tgt, note_s)
        extra = measure_book(cn) if kpi in BOOK_SQL else {}
        if kpi in extra:
            rec_score.admin_upsert(cn, kpi, str(extra[kpi]), tgt, note_s)
        return {"ok": True, "kpi": kpi, "target": tgt, "sql": rows, "last": extra.get(kpi)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:240]}
    finally:
        try:
            cn.close()
        except Exception:
            pass


def publish(counts: dict[str, Any]) -> dict[str, Any]:
    from agent_coord.server.records import connect
    from agent_coord.server.records import score as rec_score

    cn = connect()
    out: dict[str, Any] = {"ok": True, "rows": []}
    try:
        # Day evidence older than 30 days, every score, including an idle desk (#204).
        try:
            from agent_coord.server.records.db import call as sql_call

            sql_call(cn, "mill_score_evidence_purge", [None])
            out["purge"] = "ok"
        except Exception as e:
            out["purge"] = str(e)[:160]
        for kpi, note in (
            (
                KPI_TICKS,
                "server complexity: api.mill.heartbeat in window; target 0",
            ),
            (
                KPI_IDLE,
                "prompt complexity: mill inbox/wake/todo/floor in window; target 0",
            ),
            (
                KPI_DROP,
                "sit FIFO overflow: mill-perf op=ws.recv drop=1 in window; target 0",
            ),
        ):
            val = str(int(counts.get(kpi) or 0))
            rows = rec_score.admin_upsert(cn, kpi, val, TARGET, note[:200])
            out["rows"].append({"kpi": kpi, "value": val, "target": TARGET, "sql": rows})
        for kpi in HOST_KPIS:
            tgt = TARGET_MS if kpi.endswith("_ms") else ("0" if kpi in (KPI_WS_MISS, KPI_ERR_N) else "")
            val = str(int(counts.get(kpi) or 0))
            rows = rec_score.admin_upsert(cn, kpi, val, tgt, HOST_NOTES.get(kpi, "mill-host")[:200])
            out["rows"].append({"kpi": kpi, "value": val, "target": tgt, "sql": rows})
        by_desk = counts.get("desks") or {}
        notes = {
            KPI_TICKS: "this desk extra mill heartbeat while sitting; target 0",
            KPI_IDLE: "this desk idle mill JSON in window; target 0",
            KPI_DROP: "this desk sit FIFO drop=1 in window; target 0",
        }
        if isinstance(by_desk, dict):
            for who, kv in by_desk.items():
                if not isinstance(kv, dict):
                    continue
                for kpi in DESK_KPIS:
                    val = str(int(kv.get(kpi) or 0))
                    try:
                        rows = rec_score.upsert(
                            cn, office_name(cn), who, kpi, val, TARGET, notes[kpi][:200]
                        )
                    except Exception as e:
                        # A desk token from the logs that is not a desk now (retired,
                        # renamed) skips its own rows; the office rows still publish.
                        out.setdefault("skipped", []).append(
                            {"desk": str(who)[:64], "error": str(e)[:120]}
                        )
                        break
                    out["rows"].append(
                        {"desk": who, "kpi": kpi, "value": val, "target": TARGET, "sql": rows}
                    )
        book = measure_book(cn)
        counts.update(book)
        for kpi, n in book.items():
            note = BOOK_SQL[kpi][1]
            tgt = BOOK_TARGET.get(kpi, TARGET)
            rows = rec_score.admin_upsert(cn, kpi, str(int(n)), tgt, note[:200])
            out["rows"].append({"kpi": kpi, "value": str(int(n)), "target": tgt, "sql": rows})
        # Opt-in book perf (wake_first_*): publish only when score row already exists.
        try:
            cur = cn.cursor()
            try:
                cur.execute("SELECT s.kpi FROM score s WHERE s.roster_id=1")
                wanted = {r[0] for r in cur.fetchall() if r and r[0] in BOOK_PERF}
            finally:
                cur.close()
        except Exception:
            wanted = set()
        for kpi in wanted:
            note = BOOK_PERF[kpi]
            tgt = BOOK_TARGET.get(kpi, TARGET)
            val = str(int(counts.get(kpi) or 0))
            rows = rec_score.admin_upsert(cn, kpi, val, tgt, note[:200])
            out["rows"].append({"kpi": kpi, "value": val, "target": tgt, "sql": rows})
    except Exception as e:
        out["ok"] = False
        out["error"] = str(e)[:240]
        try:
            _publish_sql(cn, counts)
            out["ok"] = True
            out["fallback"] = "sql"
        except Exception as e2:
            out["error"] = (out.get("error") or "") + " | " + str(e2)[:160]
    finally:
        try:
            cn.close()
        except Exception:
            pass
    return out


def _publish_sql(cn, counts: dict[str, Any]) -> None:
    """Last resort: update the existing Office/Admin-roster rows (the reserved ids 1 and 2, #722)."""
    cur = cn.cursor()
    try:
        cur.execute(
            "SELECT (SELECT id FROM name WHERE type='roster' AND id=1 AND deleted IS NULL LIMIT 1),"
            " (SELECT id FROM name WHERE type='roster' AND id=2 AND deleted IS NULL LIMIT 1)",
        )
        office, admin = cur.fetchone() or (None, None)
        if office is None or admin is None:
            raise RuntimeError("score fallback: Office or Admin roster missing")
        for kpi in (KPI_TICKS, KPI_IDLE, KPI_DROP):
            val = str(int(counts.get(kpi) or 0))
            cur.execute(
                "UPDATE score SET value=%s, target=%s, updated=CURRENT_TIMESTAMP(6) "
                "WHERE kpi=%s AND roster_id=%s AND desk_id=%s",
                (val, TARGET, kpi, office, admin),
            )
        cn.commit()
    finally:
        cur.close()


def tick(*, dest: Path | None = None, window_s: int = WINDOW_S) -> dict[str, Any]:
    counts = measure(dest=dest, window_s=window_s)
    pub = publish(counts)
    counts["publish"] = pub
    return counts


def run_loop(*, every_s: int = EVERY_S, window_s: int = WINDOW_S, stop=None) -> int:
    import time

    every_s = max(60, int(every_s))
    while True:
        try:
            row = tick(window_s=window_s)
            _log(row)
        except Exception as e:
            _log({"ok": False, "error": str(e)[:240]})
        if stop is not None and stop.wait(every_s):
            return 0
        if stop is None:
            time.sleep(every_s)


def _log(row: dict[str, Any]) -> None:
    import json
    from datetime import datetime, timezone

    dest = mill_home()
    try:
        dest.mkdir(parents=True, exist_ok=True)
        line = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ ") + json.dumps(
            row, default=str
        )
        with (dest / "mill-score.log").open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
