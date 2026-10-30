# -*- coding: utf-8 -*-
"""0.8.0 lane D (F171): a command line counts what its connection did in MySQL.

Seen: mill-perf.log never shows lock waits (only a 1213 deadlock or 1205 timeout
as an error), and not what a command's procedures ran inside MySQL.

Wanted (throwaway MySQL 8.4): when perf is on, the command line carries the
server-side numbers of the connection it ran on, read from performance_schema:
trips (top-level statements, about one round trip each), stmts (statements, nested ones too), rows_s (rows sent), rows_x (rows examined),
srv_ms (server time of the top-level statements) and lock_ms (time spent waiting
for row locks). A row-lock wait inside a procedure is counted once, not once per
later statement (performance_schema carries it forward inside a CALL). A book
user who cannot read performance_schema still gets the line, without those fields.
"""
from __future__ import annotations

import threading
import time

import pytest

from agent_coord.server import perf
from agent_coord.server.records.db import conn_kwargs
from tests.sql_isolate import throwaway_db

pytestmark = pytest.mark.sql

DB = throwaway_db("mill_perf_ps_test")


def _connect(**over):
    import mysql.connector

    kw = conn_kwargs()
    kw.pop("database", None)
    kw.update(over)
    return mysql.connector.connect(**kw)


@pytest.fixture
def book():
    try:
        admin = _connect(autocommit=True)
    except Exception as e:  # pragma: no cover - no MySQL here
        pytest.skip(f"mysql: {e}")
    cur = admin.cursor()
    cur.execute(f"DROP DATABASE IF EXISTS `{DB}`")
    cur.execute(f"CREATE DATABASE `{DB}`")
    cur.execute(f"USE `{DB}`")
    cur.execute("CREATE TABLE t (id INT PRIMARY KEY, v INT)")
    cur.execute("INSERT INTO t VALUES (1, 0), (2, 0), (3, 0)")
    cur.execute(
        "CREATE PROCEDURE bump(IN i INT) BEGIN UPDATE t SET v = v + 1 WHERE id = i;"
        " SELECT v FROM t WHERE id = i; SELECT id FROM t; END"
    )
    perf.reload()
    perf._PS["ok"] = True
    yield admin
    cur.execute(f"DROP DATABASE IF EXISTS `{DB}`")
    for u in ("mill_perf_np",):
        cur.execute(f"DROP USER IF EXISTS '{u}'@'%'")
    admin.close()


class _Book:
    def __init__(self, cn):
        self._cn = cn

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self._cn.close()


def _call(cn, name: str, args: list) -> None:
    cur = cn.cursor()
    cur.execute("CALL `%s`(%s)" % (name, ",".join(["%s"] * len(args))), tuple(args))
    while True:
        if cur.with_rows:
            cur.fetchall()
        if not cur.nextset():
            break
    cn.commit()
    cur.close()


def test_lock_wait_inside_a_procedure_is_counted_once(book) -> None:
    holder = _connect(database=DB)
    hc = holder.cursor()
    holder.start_transaction()
    hc.execute("UPDATE t SET v = v WHERE id = 1")
    threading.Timer(0.3, holder.commit).start()
    cmd = perf.begin("hold", "alice")
    t = time.perf_counter()
    perf.in_book(cmd, lambda: _Book(_connect(database=DB)), lambda c: _call(c._cn, "bump", [1]))
    wall = (time.perf_counter() - t) * 1000.0
    holder.close()
    f = perf.fields(cmd)
    assert 250.0 <= float(f["lock_ms"]) <= wall, f
    assert "lock_part" not in f
    # CALL plus its three statements, plus the commit
    assert int(f["stmts"]) >= 4
    assert int(f["rows_s"]) >= 4  # one v and three ids (MySQL's count; it adds one per CALL)
    assert int(f["rows_x"]) >= 3
    assert 250.0 <= float(f["srv_ms"]) <= wall


def test_no_wait_is_zero(book) -> None:
    cmd = perf.begin("hold", "alice")
    perf.in_book(cmd, lambda: _Book(_connect(database=DB)), lambda c: _call(c._cn, "bump", [2]))
    f = perf.fields(cmd)
    assert float(f["lock_ms"]) < 5.0


def test_the_snapshot_reads_do_not_count_themselves(book) -> None:
    cmd = perf.begin("hold", "alice")
    perf.in_book(cmd, lambda: _Book(_connect(database=DB)), lambda c: None)
    f = perf.fields(cmd)
    assert (f["trips"], f["stmts"], f["rows_s"], f["rows_x"], f["lock_ms"]) == (0, 0, 0, 0, "0.00"), f


def test_trips_count_round_trips(book) -> None:
    cmd = perf.begin("hold", "alice")
    perf.in_book(cmd, lambda: _Book(_connect(database=DB)), lambda c: _call(c._cn, "bump", [2]))
    # The CALL and its commit, plus the ping the C connector sends when a cursor
    # opens (the pure one sends other statements of its own).
    assert perf.fields(cmd)["trips"] >= 2


def test_two_waits_in_one_command_add_up(book) -> None:
    holders = []
    for i, wait in ((1, 0.2), (2, 0.4)):
        h = _connect(database=DB)
        h.start_transaction()
        h.cursor().execute("UPDATE t SET v = v WHERE id = %s", (i,))
        threading.Timer(wait, h.commit).start()
        holders.append(h)
    cmd = perf.begin("hold", "alice")

    def two(c) -> None:
        _call(c._cn, "bump", [1])
        _call(c._cn, "bump", [2])

    perf.in_book(cmd, lambda: _Book(_connect(database=DB)), two)
    for h in holders:
        h.close()
    f = perf.fields(cmd)
    assert 350.0 <= float(f["lock_ms"]) <= 520.0, f


def test_user_without_performance_schema_still_gets_a_line(book) -> None:
    cur = book.cursor()
    cur.execute("CREATE USER IF NOT EXISTS 'mill_perf_np'@'%' IDENTIFIED BY 'np-throwaway-1'")
    cur.execute(f"GRANT SELECT, UPDATE, EXECUTE ON `{DB}`.* TO 'mill_perf_np'@'%'")
    cmd = perf.begin("hold", "alice")
    out = perf.in_book(
        cmd,
        lambda: _Book(_connect(database=DB, user="mill_perf_np", password="np-throwaway-1")),
        lambda c: (_call(c._cn, "bump", [3]), "done")[1],
    )
    assert out == "done"
    f = perf.fields(cmd)
    assert "lock_ms" not in f and "stmts" not in f
    assert "open" in f["ph"] and "run" in f["ph"]


def test_on_cost_of_the_snapshot(book) -> None:
    """Baseline, not a gate: what the two performance_schema reads add per command."""
    cn = _connect(database=DB)
    best = float("inf")
    for _ in range(20):
        cmd = perf.begin("inbox", "alice")
        t = time.perf_counter()
        perf._ps_begin(cmd, cn)
        perf._ps_end(cmd, cn)
        best = min(best, (time.perf_counter() - t) * 1000.0)
    cn.close()
    print(f"perf on: performance_schema snapshot {best:.3f} ms per command")
    assert best < 50.0
