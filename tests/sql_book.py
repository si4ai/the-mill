"""Session tip-schema for @pytest.mark.sql tests (card 986).

Shared path (default): one CREATE DATABASE + full pack apply per xdist worker.
Between tests, only table data is cleared (TRUNCATE + reseed). Procedures and
tables stay. Tests that only read can skip the reset (sql_readonly).

fresh_schema path: only for apply/wipe/migration/parity (or a non-tip book).
Each module gets a uniquely named database, applies, and DROPs in a finalizer
so modules can run in parallel across workers.
"""
from __future__ import annotations

import hashlib
import os
import re
import threading
import time
from contextlib import contextmanager
from typing import Any

# Tip pack data tables (TRUNCATE order free under FOREIGN_KEY_CHECKS=0).
DATA_TABLES = (
    "mill_invite_join",
    "mill_invite",
    "label",
    "watcher",
    "tree",
    "tree_read",
    "mail_to",
    "member",
    "mail",
    "todo",
    "doing",
    "seat",
    "hold",
    "score_point",
    "score_evidence",
    "score",
    "human_member",
    "human_desk",
    "human",
    "transition_edge",
    "transition",
    "wake",
    "activity",
    "name",
)

_SAFE = re.compile(r"[^A-Za-z0-9_]+")
_lock = threading.Lock()
_applied: dict[str, str] = {}  # worker_key -> db name
_timings: dict[str, float] = {}
_dirty_shared = False


def worker_key() -> str:
    w = (os.environ.get("PYTEST_XDIST_WORKER") or "").strip()
    if w:
        return _SAFE.sub("_", w).strip("_") or "w"
    return f"p{os.getpid()}"


def shared_db_name() -> str:
    return f"mill_sql_shared_{worker_key()}"[:64]


def fresh_db_name(prefix: str, *, nodeid: str = "") -> str:
    """Unique schema name for one fresh_schema module/test (parallel-safe)."""
    base = _SAFE.sub("_", (prefix or "mill_fresh").strip()).strip("_") or "mill_fresh"
    dig = hashlib.sha1(f"{worker_key()}:{nodeid}:{prefix}".encode()).hexdigest()[:10]
    # MySQL id max 64; keep prefix readable.
    return f"{base[:40]}_{worker_key()[:8]}_{dig}"[:64]


def _admin_connect():
    import mysql.connector
    from agent_coord.server.records.db import conn_kwargs

    kw = conn_kwargs()
    kw.pop("database", None)
    kw["autocommit"] = True
    return mysql.connector.connect(**kw)


def create_database(name: str) -> float:
    """CREATE DATABASE IF NOT EXISTS. Returns seconds."""
    t0 = time.perf_counter()
    admin = _admin_connect()
    try:
        cur = admin.cursor()
        cur.execute(
            f"CREATE DATABASE IF NOT EXISTS `{name}` "
            "DEFAULT CHARACTER SET utf8mb4 DEFAULT COLLATE utf8mb4_0900_ai_ci"
        )
        cur.close()
    finally:
        admin.close()
    return time.perf_counter() - t0


def drop_database(name: str) -> float:
    """DROP DATABASE IF EXISTS. Returns seconds."""
    t0 = time.perf_counter()
    admin = _admin_connect()
    try:
        cur = admin.cursor()
        cur.execute(f"DROP DATABASE IF EXISTS `{name}`")
        cur.close()
    finally:
        admin.close()
    return time.perf_counter() - t0


def apply_tip(cn) -> float:
    """Full tip pack apply with wipe (tables+routines). Returns seconds."""
    from agent_coord.server import records

    t0 = time.perf_counter()
    records.apply(cn, wipe=True)
    return time.perf_counter() - t0


def reseed(cn) -> None:
    """System/Office/Admin name rows, System seat, and system score seeds from tables.sql."""
    cur = cn.cursor()
    try:
        cur.execute("SET @mill_1022_old_mode := @@SESSION.sql_mode")
        cur.execute(
            "SET SESSION sql_mode = CONCAT(@@SESSION.sql_mode, ',NO_AUTO_VALUE_ON_ZERO')"
        )
        cur.execute(
            "INSERT IGNORE INTO name (id, type, name) VALUES "
            "(0, 'desk', 'System'), (1, 'roster', 'Office'), (2, 'roster', 'Admin')"
        )
        cur.execute("SET SESSION sql_mode = @mill_1022_old_mode")
        cur.execute("ALTER TABLE name AUTO_INCREMENT = 100")
        cur.execute(
            "INSERT IGNORE INTO seat (desk_id, token_hash, delivery_mode, wake_on) "
            "VALUES (0, NULL, 'polling', 'addressed')"
        )
        for kpi, note in (
            (
                "mill-wall.ticks",
                "server complexity: api.mill.heartbeat per desk-hour while sitting; target 0",
            ),
            (
                "mill-desk.idle_verbs",
                "prompt complexity: mill inbox/todo per desk-hour with no HINT; target 0",
            ),
            (
                "mill-desk.hint_drop",
                "sit FIFO overflow: mill-perf op=ws.recv drop=1 in window; target 0",
            ),
        ):
            cur.execute(
                "INSERT INTO score (updated, desk_id, roster_id, kpi, value, target, note) "
                "SELECT CURRENT_TIMESTAMP(6), NULL, 1, %s, '', '0', %s FROM DUAL "
                "WHERE NOT EXISTS ("
                " SELECT 1 FROM score WHERE roster_id = 1 AND desk_id IS NULL AND kpi = %s"
                ")",
                (kpi, note, kpi),
            )
        cur.execute(
            "INSERT IGNORE INTO activity (type, id, created, updated, desk_id, roster_id, act, bytes) "
            "SELECT 'score', s.id, s.created, s.updated, s.desk_id, s.roster_id, 'create', NULL "
            "FROM score s WHERE s.kpi IN "
            "('mill-wall.ticks', 'mill-desk.idle_verbs', 'mill-desk.hint_drop')"
        )

        # card 1022: allowed edges (truncated clears them; reseed from Python Enums)
        from agent_coord.server.transition_enums import ALLOWED_TRANSITIONS
        cur.execute("DELETE FROM transition_edge")
        rows = sorted(
            {(a.value, f.value, to.value, r.value) for a, f, to, r in ALLOWED_TRANSITIONS}
        )
        if rows:
            cur.executemany(
                "INSERT INTO transition_edge (activity_type, from_state, to_state, reason) "
                "VALUES (%s, %s, %s, %s)",
                rows,
            )
        cn.commit()
    finally:
        cur.close()


def reset_data(cn) -> None:
    """TRUNCATE all tip data tables and reseed. Does not touch routines."""
    cur = cn.cursor()
    try:
        cur.execute("SET FOREIGN_KEY_CHECKS = 0")
        for table in DATA_TABLES:
            try:
                cur.execute(f"TRUNCATE TABLE `{table}`")
            except Exception:
                # Table may be absent on a half-applied book; ignore.
                pass
        cur.execute("SET FOREIGN_KEY_CHECKS = 1")
        cn.commit()
    finally:
        cur.close()
    reseed(cn)

    # Modules that call set_trust(limited) must not poison later shared suites.
    try:
        from agent_coord.server.records.trust_fn import init_trust_fn
        init_trust_fn(cn, "high")
    except Exception:
        pass


def ensure_shared_schema() -> str:
    """Apply tip schema once per worker. Returns the shared database name."""
    global _timings
    key = worker_key()
    with _lock:
        if key in _applied:
            return _applied[key]
        db = shared_db_name()
        create_s = create_database(db)
        from agent_coord.server import records

        cn = records.connect(db)
        try:
            apply_s = apply_tip(cn)
            try:
                from agent_coord.server.records.trust_fn import init_trust_fn
                init_trust_fn(cn, "high")
            except Exception:
                pass
        finally:
            cn.close()
        _applied[key] = db
        _timings.setdefault("shared_create_s", create_s)
        _timings.setdefault("shared_apply_s", apply_s)
        return db


def timings() -> dict[str, float]:
    return dict(_timings)


def record_timing(name: str, seconds: float) -> None:
    _timings[name] = seconds


def _session_caps(cn) -> None:
    cur = cn.cursor()
    try:
        cur.execute("SET SESSION innodb_lock_wait_timeout = 30")
        cur.execute("SET SESSION lock_wait_timeout = 30")
    finally:
        cur.close()


def connect_shared(*, reset: bool = True):
    """Connection to the worker's shared tip book. Optional data reset."""
    from agent_coord.server import records

    db = ensure_shared_schema()
    # Explicit database= avoids the process pool sticking to a stale schema.
    cn = records.connect(db)
    _session_caps(cn)
    if reset:
        reset_data(cn)
    os.environ["AGENT_COORD_DATABASE"] = db
    return cn


@contextmanager
def shared_cn(*, reset: bool = True):
    cn = connect_shared(reset=reset)
    try:
        yield cn
    finally:
        cn.close()


def open_fresh_book(
    prefix: str,
    *,
    nodeid: str,
    finalizer_register,
) -> Any:
    """Unique DB, full tip apply, DROP on finalizer (even after failure)."""
    from agent_coord.server import records

    db = fresh_db_name(prefix, nodeid=nodeid)
    create_s = drop_database(db)  # ensure absent
    create_s += create_database(db)
    cn = records.connect(db)
    try:
        apply_s = apply_tip(cn)
    except BaseException:
        cn.close()
        drop_database(db)
        raise
    _session_caps(cn)
    record_timing("fresh_drop_create_s", create_s)
    record_timing("fresh_apply_s", apply_s)
    os.environ["AGENT_COORD_DATABASE"] = db

    def _cleanup() -> None:
        try:
            cn.close()
        except Exception:
            pass
        try:
            drop_database(db)
        except Exception:
            pass

    finalizer_register(_cleanup)
    return cn


def mark_shared_dirty() -> None:
    global _dirty_shared
    _dirty_shared = True


def clear_shared_dirty() -> None:
    global _dirty_shared
    _dirty_shared = False


def shared_is_dirty() -> bool:
    return _dirty_shared


def restore_tip_routines(cn) -> None:
    """Refresh tip fn_/sp_ only (never re-apply tables.sql / FKs)."""
    from agent_coord.install.migrate import (
        _apply_stmt,
        _drop_functions,
        split_script,
        sql_apply_order,
    )

    cur = cn.cursor()
    try:
        try:
            cur.execute("SET GLOBAL log_bin_trust_function_creators = 1")
        except Exception:
            pass
        _drop_functions(cur)
        for path in sql_apply_order():
            if path.name in ("wipe.sql", "tables.sql"):
                continue
            if not (path.stem.startswith("fn_") or path.stem.startswith("sp_")):
                continue
            blob = path.read_text(encoding="utf-8-sig")
            for stmt in split_script(blob):
                _apply_stmt(cur, stmt)
        cn.commit()
    except Exception:
        cn.rollback()
        raise
    finally:
        cur.close()
