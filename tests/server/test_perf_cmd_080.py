# -*- coding: utf-8 -*-
"""0.8.0 lane D (F171): one mill-perf line per command with its cost, behind a switch.

Seen (dogfood pass on the cloud office, 0.7.18): mill-perf.log is always on; an
op=verb line has only ms, desk, verb and ok; SQL lines under 25 ms are dropped and
no field ties a SQL line to its command; stamps are whole seconds.

Wanted: AGENT_COORD_PERF / `perf =` in config.toml turns every perf line off
(near-zero cost) or on; `all` also keeps every fast SQL line. When on, each /ws
command line carries a request id (rid=) that its SQL lines carry too, the SQL it
ran (sql_n, sql_ms, rows), its bytes (req_b, resp_b), its outcome and a phase
breakdown (ph=q,open,run,close,sync,enc). The numbers are baselines, not gates.
"""
from __future__ import annotations

import asyncio
import itertools
import json
import re
import time
from typing import Any

import pytest

from agent_coord.helpers.errors import CoordError
from agent_coord.server import asgi as asgi_mod
from agent_coord.server import perf, push
from agent_coord.server.api.mill import rpc
from agent_coord.server.push import HUB


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)
    monkeypatch.setenv("AGENT_COORD_CONFIG", str(tmp_path / "config.toml"))
    monkeypatch.delenv("AGENT_COORD_PERF", raising=False)
    perf.reload()
    HUB.rooms.clear()
    yield tmp_path
    HUB.rooms.clear()
    monkeypatch.delenv("AGENT_COORD_PERF", raising=False)
    monkeypatch.delenv("AGENT_COORD_CONFIG", raising=False)
    perf.reload()


def _lines(home) -> list[str]:
    p = home / "mill-perf.log"
    return p.read_text(encoding="utf-8").splitlines() if p.is_file() else []


def _kv(line: str) -> dict[str, str]:
    return dict(m.groups() for m in re.finditer(r" (\w+)=(\S+)", line))


class _Book:
    _cn = object()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _WS:
    pass


_IDS = itertools.count(1)


def _run_ws(monkeypatch, command: str, handler) -> dict[str, Any]:
    monkeypatch.setattr("agent_coord.server.book.Book", lambda *a, **k: _Book())
    monkeypatch.setitem(rpc.HANDLERS, command, handler)
    ws = _WS()
    HUB.rooms.setdefault("DESK_alice", set()).add(ws)

    async def go() -> dict[str, Any]:
        return await asgi_mod._ws_handle_client_text(
            "DESK_alice", ws, json.dumps({"id": f"perf-{command}-{next(_IDS)}", "verb": command, "args": {}})
        )

    # Each request id is new: a repeated one returns the remembered reply (#137).
    return asyncio.run(go())  # asyncio.run waits for the executor, so the log line is written


def _sql_handler(c, body, project, owner):
    # The real path: records/db.call times each CALL through db._perf (Validator 3207, D1).
    from agent_coord.server.records import db

    db._perf("sql.mill_mail_insert", 30.25, n=1, ok=1)
    db._perf("sql.mill_mail_select", 1.5, n=4, ok=1)  # a fast read
    return [{"id": 9}]


def test_switch_defaults_on(home) -> None:
    assert perf.ON is True
    push.perf_log("api.floor", 1.0, status=200)
    assert len(_lines(home)) == 1


@pytest.mark.parametrize("val", ["0", "off", "false", "no"])
def test_env_off_silences_every_perf_line(home, monkeypatch, val) -> None:
    monkeypatch.setenv("AGENT_COORD_PERF", val)
    perf.reload()
    assert perf.ON is False
    push.perf_log("api.floor", 1.0, status=200)
    perf.sql_line("sql.mill_mail_insert", 90.0, n=1, ok=1)
    assert perf.begin("inbox", "alice") is None
    assert _lines(home) == []


def test_config_file_off_and_env_wins(home, monkeypatch) -> None:
    (home / "config.toml").write_text('perf = "off"\n', encoding="utf-8")
    perf.reload()
    assert perf.ON is False
    monkeypatch.setenv("AGENT_COORD_PERF", "on")
    perf.reload()
    assert perf.ON is True


def test_off_ws_command_writes_nothing(home, monkeypatch) -> None:
    monkeypatch.setenv("AGENT_COORD_PERF", "off")
    perf.reload()
    reply = _run_ws(monkeypatch, "inbox", _sql_handler)
    assert reply["ok"] is True and reply["result"] == [{"id": 9}]
    assert _lines(home) == []


def test_stamp_has_milliseconds(home) -> None:
    push.perf_log("api.floor", 1.0, status=200)
    assert re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z op=api\.floor ", _lines(home)[0])


def test_command_line_fields(home, monkeypatch) -> None:
    _run_ws(monkeypatch, "inbox", _sql_handler)
    verb = [ln for ln in _lines(home) if " op=verb " in ln]
    assert len(verb) == 1
    kv = _kv(verb[0])
    assert kv["verb"] == "inbox" and kv["ok"] == "1" and kv["desk"]
    assert re.fullmatch(r"\d+\.\d\d", kv["ms"])
    assert int(kv["req_b"]) > 0 and int(kv["resp_b"]) > 0
    # Both statements count, the fast read too, though its own line is not written.
    assert kv["sql_n"] == "2" and kv["rows"] == "5"
    assert float(kv["sql_ms"]) == pytest.approx(31.75, abs=0.01)
    ph = dict(p.split(":") for p in kv["ph"].split(","))
    assert set(ph) == {"q", "open", "run", "close", "sync", "enc"}
    assert all(float(v) >= 0 for v in ph.values())
    assert sum(float(v) for v in ph.values()) <= float(kv["ms"]) + 0.5


def test_sql_lines_carry_their_command_rid(home, monkeypatch) -> None:
    _run_ws(monkeypatch, "inbox", _sql_handler)
    _run_ws(monkeypatch, "inbox", _sql_handler)
    lines = _lines(home)
    verbs = [_kv(ln)["rid"] for ln in lines if " op=verb " in ln]
    sqls = [_kv(ln).get("rid") for ln in lines if " op=sql.mill_mail_insert " in ln]
    assert len(verbs) == 2 and verbs[0] != verbs[1]
    assert sqls == verbs  # each SQL line joins to exactly its own command
    assert not any(" op=sql.mill_mail_select " in ln for ln in lines)  # fast read: counted, not written


def test_all_keeps_fast_sql_lines(home, monkeypatch) -> None:
    monkeypatch.setenv("AGENT_COORD_PERF", "all")
    perf.reload()
    _run_ws(monkeypatch, "inbox", _sql_handler)
    lines = _lines(home)
    rid = [_kv(ln)["rid"] for ln in lines if " op=verb " in ln][0]
    fast = [ln for ln in lines if " op=sql.mill_mail_select " in ln]
    assert len(fast) == 1 and _kv(fast[0])["rid"] == rid


def test_sql_line_outside_a_command_keeps_the_old_rule(home) -> None:
    perf.sql_line("sql.mill_mail_select", 3.0, n=2, ok=1)
    perf.sql_line("sql.mill_mail_insert", 1.0, n=1, ok=1)
    perf.sql_line("sql.mill_mail_select", 1.0, ok=0, err="down")
    ops = [ln.split(" ")[1] + " " + ln.split(" ")[-1] for ln in _lines(home)]
    assert ops == ["op=sql.mill_mail_insert ok=1", "op=sql.mill_mail_select err=down"]
    assert all(" rid=" not in ln for ln in _lines(home))


def test_refused_command_line_has_rid_err_and_phases(home, monkeypatch) -> None:
    def refuse(c, body, project, owner):
        push.perf_log("sql.mill_hold_upsert", 40.0, ok=0, err="busy")
        raise CoordError("hold: refused")

    reply = _run_ws(monkeypatch, "hold", refuse)
    assert reply["ok"] is False
    lines = _lines(home)
    verb = [_kv(ln) for ln in lines if " op=verb " in ln]
    assert len(verb) == 1 and verb[0]["ok"] == "0" and verb[0]["err"] == "hold:"
    sql = [_kv(ln) for ln in lines if " op=sql.mill_hold_upsert " in ln]
    assert sql[0]["rid"] == verb[0]["rid"]
    assert verb[0]["sql_n"] == "1"
    assert "open" in verb[0]["ph"] and "run" in verb[0]["ph"]


def _per_call_us(fn, n: int = 50_000) -> float:
    best = float("inf")
    for _ in range(5):
        t = time.perf_counter()
        for _ in range(n):
            fn()
        best = min(best, (time.perf_counter() - t) / n * 1e6)
    return best


def test_off_costs_near_zero(home, monkeypatch) -> None:
    """Off: what one command pays for the hooks, against a bare call (micro-benchmark)."""
    monkeypatch.setenv("AGENT_COORD_PERF", "off")
    perf.reload()

    def bare() -> None:
        return None

    def hooks() -> None:
        # Every hook a /ws command and two of its CALLs pass through when off.
        cmd = perf.begin("inbox", "alice")
        perf.sql_line("sql.mill_mail_inbox", 1.0, n=1, ok=1)
        push.perf_log("sql.mill_mail_insert", 30.0, n=1, ok=1)
        perf.finish(cmd, 1.0, ok=1)

    base = _per_call_us(bare)
    off = _per_call_us(hooks)
    print(f"perf off: {off - base:.3f} us per command over a bare call")
    assert off - base < 5.0  # microseconds; a command is milliseconds


def test_finish_can_name_another_op(home) -> None:
    """The HTTP /api/mill path writes its own op (api.mill.<verb>) with the same fields."""
    cmd = perf.begin("send", "alice")
    perf.finish(cmd, 3.0, ok=1, req_b=10, resp_b=20, op="api.mill.send", status=200)
    (line,) = _lines(home)
    kv = _kv(line)
    assert " op=api.mill.send " in line and kv["rid"] == cmd.rid
    assert kv["status"] == "200" and kv["ok"] == "1" and kv["sql_n"] == "0"
