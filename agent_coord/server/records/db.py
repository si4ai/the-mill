"""MySQL connection + CALL wrappers for mill records SPs."""

from __future__ import annotations

import re
import threading
import time
from typing import Any

from agent_coord.install.migrate import apply_records

_POOL = None
_POOL_LOCK = threading.Lock()
_POOL_SIZE = 8
_POOL_NAME = "mill_wall"
_POOL_WAIT_S = 2.0
# Lost connection, can't connect, too many connections, lock wait, deadlock.
_BOOK_DOWN_ERRNO = frozenset({1040, 1205, 1213, 2002, 2003, 2006, 2013})
_BOOK_DOWN_TYPES = frozenset({
    "OperationalError",
    "InterfaceError",
    "InternalError",
    "PoolError",
})


def conn_kwargs() -> dict:
    from agent_coord.config import mysql_kwargs

    return mysql_kwargs()


def _pool():
    """Lazy MySQLConnectionPool (modest size). Shared by Book / HTTP path."""
    global _POOL
    if _POOL is not None:
        return _POOL
    with _POOL_LOCK:
        if _POOL is not None:
            return _POOL
        from mysql.connector import pooling

        kw = conn_kwargs()
        _POOL = pooling.MySQLConnectionPool(
            pool_name=_POOL_NAME,
            pool_size=_POOL_SIZE,
            pool_reset_session=True,
            **kw,
        )
        return _POOL


def _has_unread(raw) -> bool:
    flag = getattr(raw, "unread_result", False)
    if callable(flag):
        try:
            flag = flag()
        except Exception:
            return True
    return bool(flag)


def _consume_pending(raw) -> bool:
    """Read leftover rows so a pooled session can reset and drop its table locks."""
    try:
        cmysql = getattr(raw, "_cmysql", None)
        if cmysql is not None:
            for _ in range(64):
                try:
                    cmysql.consume_result()
                except Exception:
                    return False
                try:
                    more = bool(cmysql.more_results())
                except Exception:
                    return False
                if not more:
                    break
                try:
                    cmysql.next_result()
                except Exception:
                    return False
            return not _has_unread(raw)
        for _ in range(64):
            if _has_unread(raw):
                raw.consume_results()
            if not getattr(raw, "_have_next_result", False):
                break
            cur = raw.cursor()
            try:
                more = cur.nextset()
                if more:
                    cur.fetchall()
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
            if not more:
                break
        return not _has_unread(raw) and not getattr(raw, "_have_next_result", False)
    except Exception:
        return False


def _drop_server_session(raw) -> None:
    """Close the server thread. A sleeping pooled thread keeps metadata locks."""
    cmysql = getattr(raw, "_cmysql", None)
    if cmysql is not None:
        try:
            cmysql.free_result()
        except Exception:
            pass
        try:
            cmysql.close()
        except Exception:
            pass
        try:
            raw._cmysql = None
        except Exception:
            pass
        return
    sock = getattr(raw, "_socket", None)
    if sock is not None:
        closer = getattr(sock, "close_connection", None)
        try:
            if closer is not None:
                closer()
            else:
                sock.close()
        except Exception:
            pass
    try:
        raw._socket = None
    except Exception:
        pass
    try:
        raw.unread_result = False
    except Exception:
        pass
    try:
        raw._have_next_result = False
    except Exception:
        pass


def _arm_pool_close(cn) -> None:
    """Finish leftover rows before a pooled socket is reused.

    A server thread with rows still open holds metadata locks, and
    DROP TRIGGER activity_del_watchers waits on that thread. Drop the thread
    when those rows cannot be read.
    """
    original = cn.close

    def close() -> None:
        raw = getattr(cn, "_cnx", cn)
        pending = _has_unread(raw) or bool(getattr(raw, "_have_next_result", False))
        if pending and not _consume_pending(raw):
            _drop_server_session(raw)
        try:
            original()
        except Exception:
            if not pending:
                raise
            _drop_server_session(raw)

    cn.close = close  # type: ignore[method-assign]


def _pool_busy(exc: BaseException) -> bool:
    """True when every pooled slot is checked out. Other failures are not a wait."""
    if type(exc).__name__ == "PoolError":
        return True
    return "pool exhausted" in str(exc).lower()


def book_down(exc: BaseException) -> bool:
    """True when the book or its pool cannot be used. A duplicate key is not this."""
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        errno = getattr(cur, "errno", None)
        if errno == 1062 or "Duplicate entry" in str(cur):
            return False
        if type(cur).__name__ in _BOOK_DOWN_TYPES or errno in _BOOK_DOWN_ERRNO:
            return True
        cur = cur.__cause__
    return False


# #818: a deadlock (1213, the connector raises InternalError) or a lock wait
# timeout (1205, DatabaseError) is worth one more try; matched on the code.
TRANSIENT_ERRNO = {1213: "deadlock", 1205: "lock wait timeout"}


def transient_errno(exc: BaseException | None) -> int | None:
    """1213 or 1205 when exc (or what caused it) is a deadlock or lock wait, else None."""
    seen = 0
    while exc is not None and seen < 5:
        errno = getattr(exc, "errno", None)
        if errno in TRANSIENT_ERRNO:
            return int(errno)
        exc = exc.__cause__
        seen += 1
    return None


def retryable_db(exc: BaseException) -> bool:
    """One more try for a dropped connection, a deadlock or a lock wait.
    Never for a duplicate key (1062)."""
    if getattr(exc, "errno", None) == 1062 or "Duplicate entry" in str(exc):
        return False
    if transient_errno(exc) is not None:
        return True
    if type(exc).__name__ not in ("OperationalError", "InterfaceError"):
        return False
    return book_down(exc)


def connect(database: str | None = None):
    """Checkout a pooled connection (close() returns it). Override DB -> direct.

    A full pool waits about 2s. A down book fails at once (#144).
    """
    kw = conn_kwargs()
    if database and database != kw.get("database"):
        import mysql.connector

        kw = dict(kw)
        kw["database"] = database
        return mysql.connector.connect(**kw)
    deadline = time.monotonic() + _POOL_WAIT_S
    while True:
        try:
            cn = _pool().get_connection()
            break
        except Exception as exc:
            if not _pool_busy(exc) or time.monotonic() >= deadline:
                raise
            time.sleep(0.05)
    _arm_pool_close(cn)
    return cn


def book_sql_state() -> dict[str, Any]:
    """Whether the book holds this pack's SQL (#614). Read only; a failed read is not ok."""
    from agent_coord.install.migrate import SQL_FIX, sql_state

    try:
        cn = connect()
    except Exception:
        return {"ok": False, "pack": "", "book": "", "fix": SQL_FIX, "error": "book unavailable"}
    try:
        return sql_state(cn)
    except Exception as e:
        return {"ok": False, "pack": "", "book": "", "fix": SQL_FIX, "error": type(e).__name__}
    finally:
        try:
            cn.close()
        except Exception:
            pass


def book_ping() -> bool:
    """True when the book answers a ping. No rows and no secrets (#144)."""
    try:
        cn = connect()
    except Exception:
        return False
    try:
        try:
            cn.ping(reconnect=False, attempts=1, delay=0)
        except TypeError:
            cn.ping(False)
        return True
    except Exception:
        return False
    finally:
        try:
            cn.close()
        except Exception:
            pass


def warm_pool() -> None:
    """Import auth plugin + open all pool slots (ping each) so first HTTP is not cold."""
    try:
        import mysql.connector.plugins.caching_sha2_password  # noqa: F401
    except Exception:
        pass
    held = []
    try:
        for _ in range(max(1, int(_POOL_SIZE))):
            try:
                cn = connect()
            except Exception:
                break
            held.append(cn)
            try:
                try:
                    cn.ping(reconnect=True, attempts=1, delay=0)
                except TypeError:
                    try:
                        cn.ping(True)
                    except Exception:
                        pass
                except Exception:
                    pass
            except Exception:
                pass
    finally:
        for cn in held:
            try:
                cn.close()
            except Exception:
                pass


def warm_read_paths(projects: list[str] | None = None) -> None:
    """Background warm: rooms + lean mailbox path (after listen). Best-effort."""
    plist = list(projects or []) or ["the-mill"]
    mail_ps = [str(p).strip() for p in plist if str(p).strip()]
    want = {str(p).strip() for p in plist if p}
    cn = connect()
    try:
        from agent_coord.server.records.floor import build_mailbox, build_rooms

        try:
            build_rooms(cn, want)
        except Exception:
            pass
        try:
            build_mailbox(cn, mail_ps, want)
        except Exception:
            pass
    finally:
        try:
            cn.close()
        except Exception:
            pass


# 0.8.0: the kind-checked name FKs and seat FKs refuse a wrong id with 1452, a CHECK with
# 3819. The raw text names the book; the refusal names only what was wrong.
_FK_NAME = re.compile(r"CONSTRAINT `([A-Za-z0-9_]+)`")
_CHECK_NAME = re.compile(r"[Cc]heck constraint '([A-Za-z0-9_]+)'")
_FK_WHAT = (
    ("_desk", "that desk has no seat in this office"),
    ("_updated", "that desk has no seat in this office"),
    ("_creator", "that desk has no seat in this office"),
    ("_assigned", "that desk has no seat in this office"),
    ("_roster", "that id is not a roster"),
    ("_member_name", "that id is not a roster"),
    ("_label_name", "that id is not a label"),
    ("_tree_name", "that id is not a plan"),
    ("_tree_read_tree", "that id is not a plan"),
    ("_res", "that id is not a resource"),
)


def fk_refusal(exc: BaseException | None) -> str | None:
    """A plain refusal line for an FK (1452) or CHECK (3819) error, else None."""
    errno = int(getattr(exc, "errno", 0) or 0)
    text = str(getattr(exc, "msg", "") or exc or "")
    if errno == 1452:
        m = _FK_NAME.search(text)
        name = m.group(1) if m else ""
        for tail, what in _FK_WHAT:
            if name.endswith(tail):
                return f"refused: {what} ({name}); nothing changed"
        return f"refused: no such row for {name or 'that reference'}; nothing changed"
    if errno == 3819:
        m = _CHECK_NAME.search(text)
        return f"refused: {m.group(1) if m else 'a check'} does not hold; nothing changed"
    return None


def apply(cn, *, wipe: bool = False) -> dict[str, Any]:
    return apply_records(cn, wipe=wipe)


def _bump_write(name: str) -> None:
    """Move pane versions after a successful write. A read leaves them alone."""
    try:
        from agent_coord.server.table_ver import bump, tables_for_proc

        tables = tables_for_proc(name)
        if tables:
            bump(tables)
    except Exception:
        pass


def _perf(op: str, ms: float, **kv: Any) -> None:
    """One CALL's cost. perf.sql_line counts it on the command line (fast reads too), keeps the
    25 ms rule for a fast read's own line, and writes it anyway under `all` (F171)."""
    try:
        from agent_coord.server import perf

        perf.sql_line(op, ms, **kv)
    except Exception:
        pass


def finish_cursor(cur) -> None:
    """Read every row and result set still sitting on this cursor."""
    try:
        cur.fetchall()
    except Exception:
        pass
    nxt = getattr(cur, "nextset", None)
    if nxt is None:
        return
    for _ in range(64):
        try:
            more = nxt()
        except Exception:
            return
        if not more:
            return
        try:
            cur.fetchall()
        except Exception:
            return


def drain_proc(cur) -> list[dict[str, Any]]:
    """Rows from CALL, then the trailing argument SELECT and any further sets."""
    rows: list[dict[str, Any]] = []
    stored = getattr(cur, "stored_results", None)
    if stored is not None:
        for res in stored():
            cols = list(getattr(res, "column_names", ()) or ())
            for tup in res.fetchall():
                rows.append(dict(zip(cols, tup)))
    finish_cursor(cur)
    return rows


_PROC_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


def _exec_call_ok() -> bool:
    """One CALL statement with nextset() result sets (Connector/Python 9+)."""
    try:
        import mysql.connector

        return int(str(mysql.connector.__version__).split(".")[0]) >= 9
    except Exception:
        return False


_EXEC_CALL = _exec_call_ok()


class Inline:
    """One CALL arg spelled as a SQL function call with its own params (#867).

    CALL cmd_pass(MILL_DESK_ID(%s), %s, ...) resolves a desk name to its id in the
    same round trip as the command. Only plain function calls are allowed.
    """

    __slots__ = ("sql", "params")

    def __init__(self, sql: str, *params: Any):
        if not _INLINE_SQL.match(sql or ""):
            raise ValueError("Inline: one function call, %s placeholders only")
        self.sql = sql
        self.params = params


_INLINE_SQL = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\((?:%s(?:,\s*%s)*)?\)$")


def _inline_resolve(cur, args: list) -> list:
    """Older-connector path: read each Inline arg's value first (one SELECT each)."""
    out = []
    for a in args:
        if isinstance(a, Inline):
            cur.execute("SELECT " + a.sql, tuple(a.params))
            row = cur.fetchone()
            out.append(row[0] if row else None)
        else:
            out.append(a)
    return out


def _run_proc(cur, name: str, args: list) -> list[dict[str, Any]]:
    """Rows of every result set of CALL name(args).

    callproc() costs three round trips (SET @_arg..., CALL, SELECT @_arg...). No
    procedure has OUT parameters, so one CALL statement returns the same rows (F24).
    An older connector, a cursor without nextset(), or a name that is not a plain
    identifier keeps callproc.
    """
    if not _EXEC_CALL or not _PROC_NAME.match(name or "") or not hasattr(cur, "nextset"):
        cur.callproc(name, _inline_resolve(cur, args))
        return drain_proc(cur)
    marks = ",".join(a.sql if isinstance(a, Inline) else "%s" for a in args)
    params: list[Any] = []
    for a in args:
        params.extend(a.params if isinstance(a, Inline) else (a,))
    cur.execute("CALL `%s`(%s)" % (name, marks), tuple(params))
    rows: list[dict[str, Any]] = []
    for _ in range(64):
        if getattr(cur, "with_rows", False):
            cols = list(getattr(cur, "column_names", ()) or ())
            for tup in cur.fetchall():
                rows.append(dict(zip(cols, tup)))
        if not cur.nextset():
            break
    return rows


# #818: one transaction for a command and its doing row. While request_tx runs
# on a connection, call() and the read helpers do not commit, and the stored
# procedures skip their own START TRANSACTION / COMMIT (@mill_req_tx).
_REQ_TX: dict[int, dict[str, Any]] = {}


class RequestRolledBack(Exception):
    """A statement failed inside request_tx; everything it wrote was rolled back."""

    def __init__(self, cause: BaseException):
        super().__init__(str(cause))
        self.cause = cause


def in_request_tx(cn) -> bool:
    return id(cn) in _REQ_TX


def commit(cn) -> None:
    """Commit now, unless a request transaction is open (it commits at its end)."""
    if id(cn) in _REQ_TX:
        return
    cn.commit()


def after_commit(cn, fn) -> None:
    """Run fn after the request transaction commits (dropped on a rollback); now if none is open."""
    st = _REQ_TX.get(id(cn))
    if st is None:
        fn()
        return
    st["after"].append(fn)


def _req_flag(cn, on: bool) -> None:
    cur = cn.cursor()
    try:
        cur.execute("SET @mill_req_tx = 1" if on else "SET @mill_req_tx = NULL")
        if on:
            cur.execute("START TRANSACTION")
    finally:
        cur.close()


def request_tx(cn, run):
    """run() as one transaction on cn (#818). Every call() and stored procedure
    on cn joins it: call() neither commits nor retries, and the procedures skip
    their own START TRANSACTION / COMMIT (@mill_req_tx).

    It commits only when run() returns and no statement failed on the way (a
    handler that catches a failed call does not hide it). Otherwise everything
    rolls back: RequestRolledBack is raised for a failed statement, else run()'s
    own error. after_commit work runs after the commit; a rollback drops it.

    When the failure is retryable (retryable_db: a dropped connection, a deadlock
    1213 or a lock wait 1205, whether raised or caught by a handler), the whole
    run goes again once on the same connection. If that fails too, a transient
    cause is raised as RequestRolledBack, so the caller can say nothing changed.
    """
    for attempt in (1, 2):
        try:
            cn.rollback()  # no read snapshot carried in
        except Exception:
            pass
        st: dict[str, Any] = {"after": [], "failed": None}
        _req_flag(cn, True)
        _REQ_TX[id(cn)] = st
        try:
            out = run()
            if st["failed"] is not None:
                raise RequestRolledBack(st["failed"])
            cn.commit()
        except BaseException as e:
            try:
                cn.rollback()
            except Exception:
                pass
            _REQ_TX.pop(id(cn), None)
            try:
                _req_flag(cn, False)
            except Exception:
                pass
            raised = e.cause if isinstance(e, RequestRolledBack) else e
            # A handler may turn a failed call into its own error; the failed call decides.
            cause = next(
                (x for x in (st["failed"], raised) if isinstance(x, Exception) and retryable_db(x)),
                None,
            )
            if cause is None:
                raise
            if attempt == 1:
                continue
            if isinstance(e, RequestRolledBack) and e.cause is cause:
                raise
            raise RequestRolledBack(cause) from e
        _REQ_TX.pop(id(cn), None)
        try:
            _req_flag(cn, False)
        except Exception:
            pass
        for fn in st["after"]:
            try:
                fn()
            except Exception:
                pass
        return out
    raise RuntimeError("request_tx: no attempt ran")


def call(cn, name: str, args: list | tuple = ()) -> list[dict[str, Any]]:
    t0 = time.perf_counter()
    st = _REQ_TX.get(id(cn))
    if st is not None:
        # Inside request_tx: no commit, no retry, no rollback here; the request decides.
        cur = _cursor(cn)
        try:
            rows = _run_proc(cur, name, list(args))
            _bump_write(name)
            _perf(f"sql.{name}", (time.perf_counter() - t0) * 1000.0, n=len(rows), ok=1)
            return rows
        except Exception as e:
            if st["failed"] is None:
                st["failed"] = e
            _perf(f"sql.{name}", (time.perf_counter() - t0) * 1000.0, ok=0, err=str(e)[:160])
            raise
        finally:
            finish_cursor(cur)
            try:
                cur.close()
            except Exception:
                pass
    last: BaseException | None = None
    for attempt in (1, 2):
        cur = _cursor(cn)
        try:
            rows = _run_proc(cur, name, list(args))
            cn.commit()
            ms = (time.perf_counter() - t0) * 1000.0
            _bump_write(name)
            _perf(f"sql.{name}", ms, n=len(rows), ok=1)
            return rows
        except Exception as e:
            last = e
            try:
                cn.rollback()
            except Exception:
                pass
            if attempt == 1 and retryable_db(e):
                continue
            _perf(f"sql.{name}", (time.perf_counter() - t0) * 1000.0, ok=0, err=str(e)[:160])
            raise
        finally:
            finish_cursor(cur)
            try:
                cur.close()
            except Exception:
                pass
    if last is not None:
        raise last
    raise RuntimeError("call produced no result")


def _cursor(cn):
    """Cursor with optional buffered from config (safe default False)."""
    try:
        from agent_coord.config import mysql_cursor_kwargs

        return cn.cursor(**mysql_cursor_kwargs())
    except Exception:
        return cn.cursor()


def scalar_done(cn, sql: str, args: tuple = ()):
    """scalar, then end the read transaction the way call() does (no snapshot or
    metadata lock left open on a pooled connection)."""
    try:
        return scalar(cn, sql, args)
    finally:
        try:
            commit(cn)
        except Exception:
            pass


def rows_done(cn, sql: str, args: tuple = ()) -> list[dict[str, Any]]:
    """Plain SELECT rows as dicts, then end the read transaction like scalar_done."""
    cur = _cursor(cn)
    try:
        cur.execute(sql, args)
        cols = list(cur.column_names or ())
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        cur.close()
        try:
            commit(cn)
        except Exception:
            pass


def scalar(cn, sql: str, args: tuple = ()):
    cur = _cursor(cn)
    try:
        cur.execute(sql, args)
        rec = cur.fetchone()
        return rec[0] if rec else None
    finally:
        cur.close()
