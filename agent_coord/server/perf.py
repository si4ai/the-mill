# -*- coding: utf-8 -*-
"""Per-command cost lines in mill-perf.log, behind one switch (0.8.0, F171).

The switch is `perf` in config.toml or AGENT_COORD_PERF (env wins), read when the
wall starts (reload() reads it again):

- on (default): every perf line; a /ws command writes one op=verb line with its
  request id (rid=), the SQL it ran, its bytes, its outcome and its phases. Each
  SQL line written while the command runs carries the same rid. A fast
  successful read (a _select/_get/_list under 25 ms) is counted on the command
  line but gets no line of its own (#220).
- all: as on, and the fast reads get their own lines too.
- off / 0 / false / no: no perf line at all. Each hook is then one module
  global check (test_perf_cmd_080: well under a microsecond per command).

The numbers are baselines to compare, not gates. docs/protocol/profiler.md lists
the fields.
"""
from __future__ import annotations

import itertools
import secrets
import threading
import time
from typing import Any, Callable

ON = True
ALL = False
_OFF = frozenset(("0", "off", "false", "no"))


def reload() -> None:
    """Read the switch from config.toml and AGENT_COORD_PERF."""
    global ON, ALL
    raw = "on"
    try:
        from agent_coord.config import settings

        raw = str(settings().get("perf") or "on")
    except Exception:
        pass
    v = raw.strip().lower()
    ON = v not in _OFF
    ALL = ON and v == "all"


_FAST_MS = 25.0
_RID_PREFIX = secrets.token_hex(2)  # tells two wall processes' ids apart
_SEQ = itertools.count(1)
_tl = threading.local()


class Cmd:
    """What one command cost so far. Only the thread that runs it writes the SQL sums."""

    __slots__ = ("rid", "verb", "desk", "ph", "sql_n", "sql_ms", "rows", "ps")

    def __init__(self, verb: str, desk: str) -> None:
        self.rid = f"{_RID_PREFIX}-{next(_SEQ):x}"
        self.verb = verb
        self.desk = desk
        self.ph: dict[str, float] = {}
        self.sql_n = 0
        self.sql_ms = 0.0
        self.rows = 0
        self.ps: dict[str, Any] | None = None


def begin(verb: str, desk: str) -> Cmd | None:
    """A new command record, or None when perf is off."""
    if not ON:
        return None
    return Cmd(verb, desk)


def current() -> Cmd | None:
    return getattr(_tl, "cmd", None)


def phase(cmd: Cmd | None, name: str, ms: float) -> None:
    if cmd is not None:
        cmd.ph[name] = cmd.ph.get(name, 0.0) + ms


def _fast_read(op: str, ms: float, kv: dict[str, Any]) -> bool:
    return (
        kv.get("ok") == 1
        and ms < _FAST_MS
        and op.startswith("sql.")
        and op[4:].endswith(("_select", "_get", "_list"))
    )


def note(op: str, ms: float, kv: dict[str, Any]) -> str | None:
    """Count a SQL line into the command running on this thread; its rid, if any."""
    cmd = getattr(_tl, "cmd", None)
    if cmd is None:
        return None
    if op.startswith("sql."):
        cmd.sql_n += 1
        cmd.sql_ms += ms
        n = kv.get("n")
        if isinstance(n, int):
            cmd.rows += n
    return cmd.rid


def sql_line(op: str, ms: float, **kv: Any) -> None:
    """One statement's line (records/db.py calls this for every CALL)."""
    if not ON:
        return
    try:
        rid = note(op, ms, kv)
        if not ALL and _fast_read(op, ms, kv):
            return
        from agent_coord.server.push import perf_write

        perf_write(op, ms, kv, rid)
    except Exception:
        pass


def in_book(cmd: Cmd, book: Callable[[], Any], fn: Callable[[Any], Any]) -> Any:
    """fn(c) in a fresh Book, timed as open / run / close, with its SQL counted."""
    prev = getattr(_tl, "cmd", None)
    _tl.cmd = cmd
    t = time.perf_counter()
    t_run = None
    try:
        with book() as c:
            t_run = time.perf_counter()
            phase(cmd, "open", (t_run - t) * 1000.0)
            cn = getattr(c, "_cn", None)
            _ps_begin(cmd, cn)
            try:
                return fn(c)
            finally:
                _ps_end(cmd, cn)
                t = time.perf_counter()
                phase(cmd, "run", (t - t_run) * 1000.0)
    finally:
        if t_run is not None:
            phase(cmd, "close", (time.perf_counter() - t) * 1000.0)
        _tl.cmd = prev


def fields(cmd: Cmd) -> dict[str, Any]:
    """The command line's fields after ms, in line order."""
    out: dict[str, Any] = {
        "sql_n": cmd.sql_n,
        "sql_ms": f"{cmd.sql_ms:.2f}",
        "rows": cmd.rows,
    }
    ps = cmd.ps or {}
    for k in ("trips", "stmts", "rows_s", "rows_x", "srv_ms", "lock_ms", "lock_part"):
        if k in ps:
            out[k] = ps[k]
    if cmd.ph:
        out["ph"] = ",".join(f"{k}:{v:.2f}" for k, v in cmd.ph.items())
    return out


def finish(
    cmd: Cmd | None,
    ms: float,
    *,
    ok: int,
    err: str | None = None,
    req_b: int | None = None,
    resp_b: int | None = None,
    op: str = "verb",
    **extra: Any,
) -> None:
    """Write the command's line (op=verb on /ws). err stays last: readers take it to the line end."""
    if cmd is None or not ON:
        return
    try:
        kv: dict[str, Any] = {"desk": cmd.desk, "verb": cmd.verb, "ok": ok, **extra, "req_b": req_b, "resp_b": resp_b}
        kv.update(fields(cmd))
        kv["err"] = err
        from agent_coord.server.push import perf_write

        perf_write(op, ms, kv, cmd.rid)
    except Exception:
        pass


# ---- server side: performance_schema numbers for the command's connection ----
#
# Why performance_schema: MySQL 8.4 keeps per-thread statement sums
# (events_statements_summary_by_thread_by_event_name) and each thread's last
# statements (events_statements_history, 10 by default), both on by default.
# Innodb_row_lock_time is global only, so its delta would mix in every other
# desk. One SET before the command and one SELECT after it read both; the SET
# is a set_option statement, which the sums leave out, so the reads do not
# count themselves.
#
# Lock time: LOCK_TIME includes InnoDB row-lock waits. Inside a CALL it carries
# forward: each later nested statement reports the time so far since the CALL
# began. So each top-level statement's lock is the largest LOCK_TIME among it and
# its nested statements, and the command's lock_ms is the sum of those. When the
# history ring no longer holds the SET (more statements than it keeps),
# lock_part=1 marks lock_ms as a lower bound.

_PS: dict[str, bool] = {"ok": True}
# Errors that mean this book user or server has no performance_schema to read.
_PS_OFF_ERRNO = frozenset((1044, 1142, 1146, 1227, 1305, 1370, 1683))

_SET = "'statement/sql/set_option'"
_PS_SUMS = (
    "SELECT CONCAT_WS(',',"
    " SUM(IF((EVENT_NAME = 'statement/sp/stmt' OR EVENT_NAME LIKE 'statement/sql/%') AND EVENT_NAME <> " + _SET + ", COUNT_STAR, 0)),"
    " SUM(IF(EVENT_NAME <> " + _SET + ", SUM_ROWS_SENT, 0)),"
    " SUM(IF(EVENT_NAME <> " + _SET + ", SUM_ROWS_EXAMINED, 0)),"
    " SUM(IF(EVENT_NAME LIKE 'statement/sql/%' AND EVENT_NAME <> " + _SET + ", SUM_TIMER_WAIT, 0)),"
    " SUM(IF(EVENT_NAME LIKE 'statement/sql/%' OR EVENT_NAME LIKE 'statement/com/%', COUNT_STAR, 0)))"
    " FROM performance_schema.events_statements_summary_by_thread_by_event_name"
    " WHERE THREAD_ID = PS_CURRENT_THREAD_ID()"
)
_PS_BEGIN = (
    "SET @mill_ps_e = (SELECT EVENT_ID FROM performance_schema.events_statements_current"
    " WHERE THREAD_ID = PS_CURRENT_THREAD_ID()), @mill_ps = (" + _PS_SUMS + ")"
)
_PS_END = (
    "SELECT 0, @mill_ps, (" + _PS_SUMS + "), NULL"
    " UNION ALL SELECT EVENT_ID, NESTING_EVENT_LEVEL, LOCK_TIME, @mill_ps_e"
    " FROM performance_schema.events_statements_history"
    " WHERE THREAD_ID = PS_CURRENT_THREAD_ID() AND EVENT_ID >= @mill_ps_e"
)


def _ps_failed(e: BaseException) -> None:
    if getattr(e, "errno", None) in _PS_OFF_ERRNO:
        _PS["ok"] = False  # this book cannot give them; stop asking until restart


def _query(cn: Any, sql: str) -> list:
    """Run sql on the connection itself, not a cursor: opening a cursor pings the
    server first, a round trip of its own. Returns every row."""
    cn.cmd_query(sql)
    if not getattr(cn, "unread_result", False):
        return []
    rows, _ = cn.get_rows()
    return [tuple(r) for r in rows]


def _ps_begin(cmd: Cmd, cn: Any) -> None:
    if not _PS["ok"] or cn is None:
        return
    try:
        _query(cn, _PS_BEGIN)
        cmd.ps = {}
    except Exception as e:
        _ps_failed(e)


def _sums(raw: Any) -> list[int]:
    try:
        return [int(float(x)) for x in str(raw).split(",")]
    except Exception:
        return []


def _ps_end(cmd: Cmd, cn: Any) -> None:
    if cmd.ps is None or cn is None:
        return
    try:
        got = _query(cn, _PS_END)
    except Exception as e:
        _ps_failed(e)
        cmd.ps = None
        return
    if not got:
        cmd.ps = None
        return
    a, b = _sums(got[0][1]), _sums(got[0][2])
    if len(a) != 5 or len(b) != 5:
        cmd.ps = None
        return
    d = [y - x for x, y in zip(a, b)]
    ps: dict[str, Any] = {
        "stmts": d[0],
        "rows_s": d[1],
        "rows_x": d[2],
        "srv_ms": f"{d[3] / 1e9:.2f}",
        "trips": d[4] - 1,  # top-level statements and pings (round trips), less the SET
    }
    hist = sorted((int(r[0]), int(r[1]), int(r[2] or 0), r[3]) for r in got[1:])
    start = int(hist[0][3]) if hist and hist[0][3] is not None else None
    lock_ps = 0
    top_lock = 0
    seen_top = False
    for eid, level, lock, _ in hist:
        if eid == start:
            continue  # the SET itself
        if level == 0:
            lock_ps += top_lock
            top_lock, seen_top = lock, True
        else:
            top_lock = max(top_lock, lock)
    lock_ps += top_lock
    ps["lock_ms"] = f"{lock_ps / 1e9:.2f}"
    if not hist or start is None or hist[0][0] != start or not seen_top:
        ps["lock_part"] = 1
    cmd.ps = ps


reload()
