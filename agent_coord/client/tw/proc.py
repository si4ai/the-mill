# -*- coding: utf-8 -*-
"""tw run, list, and stop. The child talks to the sitting link. Doing stays server-side."""
from __future__ import annotations

import json
import sys
import os
import subprocess
import threading
import time
import uuid
from typing import Any

from agent_coord.client.tw.link import _desk, open_session, pointer_path
from agent_coord.client.tw.notice import Notices
from agent_coord.client.tw.sample import take
from agent_coord.client.tw.spool import Spool, retry_delay


def runs_path(desk: str):
    pointer = pointer_path(_desk(desk))
    return pointer.with_name(pointer.name + ".runs.json")


def _load(desk: str) -> dict[str, dict[str, Any]]:
    path = runs_path(desk)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return raw


def _save(desk: str, runs: dict[str, dict[str, Any]]) -> None:
    path = runs_path(desk)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(runs), encoding="utf-8")
    tmp.replace(path)


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        code = wintypes.DWORD()
        ok = kernel.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel.CloseHandle(handle)
        return bool(ok) and code.value == 259
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _end(pid: int) -> None:
    if pid <= 0:
        return
    if os.name == "nt":
        import ctypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel.OpenProcess(0x0001, False, pid)
        if not handle:
            return
        kernel.TerminateProcess(handle, 1)
        kernel.CloseHandle(handle)
        return
    try:
        os.kill(pid, 15)
    except OSError:
        return


def _http_event(body: dict[str, Any]) -> bool:
    """One direct tw.event hop when the sitting link is gone. No retry loop."""
    payload: dict[str, Any] = {"verb": "tw.event"}
    for key in ("watch_id", "desk", "card", "kind", "cause", "exit_code", "counts"):
        if key in body:
            payload[key] = body[key]
    if body.get("wake") is False:
        payload["wake"] = False
    try:
        from agent_coord.client.http import mill_http_call

        got = mill_http_call(payload)
    except Exception:
        return False
    return isinstance(got, dict) and got.get("ok") is True


def _reclaim_lost(desk: str) -> None:
    """Card 1098: a dead tw_pid means the wrapper died without an exit hop."""
    runs = _load(desk)
    if not runs:
        return
    kept: dict[str, dict[str, Any]] = {}
    changed = False
    for watch_id, row in runs.items():
        if not isinstance(row, dict):
            changed = True
            continue
        tw_pid = int(row.get("tw_pid") or 0)
        if tw_pid and not _alive(tw_pid):
            ok = _http_event(
                {"watch_id": watch_id, "kind": "crash", "cause": "lost"}
            )
            if not ok:
                print(
                    f"tw: lost run {watch_id} not recorded; mill connected shows it active",
                    file=sys.stderr,
                )
            changed = True
            continue
        kept[watch_id] = row
    if changed:
        _save(desk, kept)


def list_runs(desk: str) -> list[dict[str, Any]]:
    _reclaim_lost(desk)
    runs = _load(desk)
    live: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    for watch_id, row in runs.items():
        if not isinstance(row, dict):
            continue
        pid = int(row.get("pid") or 0)
        if not _alive(pid):
            continue
        live[watch_id] = row
        rows.append(
            {
                "watch_id": watch_id,
                "pid": pid,
                "argv": list(row.get("argv") or []),
            }
        )
    if live != runs:
        _save(desk, live)
    return rows


def stop_run(desk: str, watch_id: str) -> int:
    wid = str(watch_id or "").strip()
    runs = _load(desk)
    row = runs.get(wid)
    if not isinstance(row, dict):
        return 1
    row["stop"] = True
    runs[wid] = row
    _save(desk, runs)
    pid = int(row.get("pid") or 0)
    deadline = time.time() + 5.0
    while time.time() < deadline:
        if not _alive(pid):
            return 0
        time.sleep(0.05)
    if _alive(pid):
        _end(pid)
    deadline = time.time() + 2.0
    while time.time() < deadline:
        if not _alive(pid):
            return 0
        time.sleep(0.05)
    return 1


def _pending(conn: Any) -> bool:
    if os.name == "nt":
        import ctypes
        import msvcrt
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        avail = wintypes.DWORD()
        handle = msvcrt.get_osfhandle(conn.fileno())
        ok = kernel.PeekNamedPipe(handle, None, 0, None, ctypes.byref(avail), None)
        return bool(ok) and avail.value > 0
    import select

    readable, _, _ = select.select([conn], [], [], 0)
    return bool(readable)


def _flagged(desk: str, watch_id: str) -> bool:
    row = _load(desk).get(watch_id)
    return isinstance(row, dict) and bool(row.get("stop"))


def _drop(desk: str, watch_id: str) -> None:
    runs = _load(desk)
    if watch_id in runs:
        runs.pop(watch_id, None)
        _save(desk, runs)


def _live_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "watch_id": row["watch_id"],
        "pid": int(row["pid"]),
        "kind": "",
        "exit_code": None,
        "stdout_bytes": 0,
        "stderr_bytes": 0,
        "log": False,
        "sample": {},
    }


def _local_status(desk: str, watch_id: str | None) -> dict[str, Any] | None:
    """A live local run. Byte counts stay on the sit link."""
    rows: list[dict[str, Any]] = []
    for row in list_runs(desk):
        if watch_id and row["watch_id"] != watch_id:
            continue
        rows.append(_live_snapshot(row))
    if watch_id:
        if not rows:
            return None
        out: dict[str, Any] = {
            "type": "reply",
            "ok": True,
            "msg": "status",
            "watch_id": watch_id,
        }
        out["snapshot"] = rows[0]
        return out
    if not rows:
        return None
    return {"type": "reply", "ok": True, "msg": "status", "snapshot": rows}


def _status_miss(reply: Any) -> bool:
    if not isinstance(reply, dict) or reply.get("ok") is True:
        return False
    return str(reply.get("msg") or "") in ("missing", "down")


def query_status(desk: str, watch_id: str | None = None) -> dict[str, Any]:
    who = _desk(desk)
    local = _local_status(who, watch_id)
    try:
        session = open_session(who)
    except OSError:
        if local is not None:
            return local
        return {"type": "reply", "ok": False, "msg": "down"}
    try:
        msg: dict[str, Any] = {"type": "status"}
        if watch_id:
            msg["watch_id"] = watch_id
        reply = session.request(msg)
        if _status_miss(reply) and local is not None:
            return local
        return reply if isinstance(reply, dict) else {"type": "reply", "ok": False, "msg": "bad"}
    except OSError:
        if local is not None:
            return local
        return {"type": "reply", "ok": False, "msg": "down"}
    finally:
        session.close()


def _pump(
    stream: Any,
    sink: Any,
    key: str,
    lock: Any,
    counters: dict[str, int],
    texts: list[str] | None = None,
) -> None:
    if stream is None:
        return
    while True:
        chunk = stream.read(4096)
        if not chunk:
            return
        with lock:
            counters[key] = counters.get(key, 0) + len(chunk)
            if texts is not None:
                texts.append(chunk.decode("utf-8", "replace"))
            if sink is not None:
                sink.write(chunk)
                sink.flush()


def _send_sample(
    session: Any,
    watch_id: str,
    pid: int,
    counters: dict[str, int],
    lock: Any,
    log_on: bool,
) -> None:
    with lock:
        stdout_bytes = int(counters.get("stdout", 0))
        stderr_bytes = int(counters.get("stderr", 0))
    try:
        sample = take(pid)
    except OSError:
        sample = {}
    try:
        session.request(
            {
                "type": "sample",
                "watch_id": watch_id,
                "pid": pid,
                "stdout_bytes": stdout_bytes,
                "stderr_bytes": stderr_bytes,
                "log": bool(log_on),
                "sample": sample,
            }
        )
    except OSError:
        return


def _event_body(
    watch_id: str,
    kind: str,
    pid: int,
    *,
    cause: str | None = None,
    exit_code: int | None = None,
    no_wake: bool = False,
) -> dict[str, Any]:
    msg: dict[str, Any] = {
        "type": "event",
        "watch_id": watch_id,
        "kind": kind,
        "pid": pid,
    }
    if cause:
        msg["cause"] = cause
    if exit_code is not None:
        msg["exit_code"] = exit_code
    if no_wake:
        msg["wake"] = False
    return msg


def _emit(session: Any, msg: dict[str, Any]) -> bool:
    try:
        reply = session.request(msg)
    except OSError:
        return False
    return isinstance(reply, dict) and reply.get("ok") is True


def _end_all(procs: list[Any]) -> None:
    for proc in procs:
        if proc.poll() is None:
            proc.terminate()
    for proc in procs:
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)


def _chain(steps: list[list[str]]) -> list[Any]:
    procs: list[Any] = []
    previous: Any = None
    try:
        for argv in steps:
            proc = subprocess.Popen(
                argv,
                stdin=previous,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if previous is not None:
                previous.close()
            previous = proc.stdout
            procs.append(proc)
    except Exception:
        for proc in procs:
            if proc.poll() is None:
                proc.kill()
            for stream in (proc.stdout, proc.stderr, proc.stdin):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass
            try:
                proc.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                pass
        raise
    return procs


def run_argv(
    desk: str,
    argv: list[str],
    log_path: str | None = None,
    *,
    pattern: str | None = None,
    quiet_s: float = 30.0,
    no_wake: bool = False,
    steps: list[list[str]] | None = None,
) -> int:
    who = _desk(desk)
    _reclaim_lost(who)
    if steps is None:
        if not argv or any(not isinstance(part, str) or part == "" for part in argv):
            return 2
        steps = [list(argv)]
    elif (
        not steps
        or any(
            not item or any(not isinstance(part, str) or part == "" for part in item)
            for item in steps
        )
    ):
        return 2
    watch_id = "tw-" + uuid.uuid4().hex[:16]
    session: Any = None
    attempt = 0
    next_try = 0.0
    spool = Spool()
    sink = None
    pumps: list[threading.Thread] = []
    procs: list[Any] = []
    try:
        try:
            session = open_session(who)
            registered = session.request(
                {"type": "register", "key": watch_id, "argv": steps[0]}
            )
            if not (isinstance(registered, dict) and registered.get("ok") is True):
                return 1
        except OSError:
            if session is not None:
                try:
                    session.close()
                except OSError:
                    pass
            session = None
            next_try = time.monotonic() + retry_delay(0)
            attempt = 1
        lock = threading.Lock()
        counters = {"stdout": 0, "stderr": 0}
        texts: list[str] = []
        notes = Notices(pattern, quiet_s)
        if log_path:
            sink = open(log_path, "ab")
        procs = _chain(steps)
        last = procs[-1]
        pumps.append(
            threading.Thread(
                target=_pump,
                args=(last.stdout, sink, "stdout", lock, counters, texts),
                daemon=True,
            )
        )
        for proc in procs:
            pumps.append(
                threading.Thread(
                    target=_pump,
                    args=(proc.stderr, None, "stderr", lock, counters),
                    daemon=True,
                )
            )
        for pump in pumps:
            pump.start()
        runs = _load(who)
        runs[watch_id] = {
            "pid": procs[0].pid,
            "argv": steps[0],
            "stop": False,
            "tw_pid": os.getpid(),
        }
        _save(who, runs)
        print(watch_id, flush=True)

        def _lose() -> None:
            nonlocal session
            if session is None:
                return
            try:
                session.close()
            except OSError:
                pass
            session = None

        def _backoff() -> None:
            nonlocal attempt, next_try
            next_try = time.monotonic() + retry_delay(attempt)
            attempt += 1

        def _hop(body: dict[str, Any]) -> None:
            nonlocal attempt
            if session is None:
                spool.add(body)
                return
            try:
                reply = session.request(body)
            except OSError:
                spool.add(body)
                _lose()
                _backoff()
                return
            if isinstance(reply, dict) and reply.get("ok") is True:
                attempt = 0
                return
            spool.add(body)
            _backoff()

        def _flush() -> None:
            if session is None:
                return
            if spool.overflow:
                spool.overflow = False
                spool.add(
                    _event_body(
                        watch_id,
                        "overflow",
                        procs[0].pid,
                        cause="spool",
                        no_wake=no_wake,
                    )
                )
            pending = spool.drain()
            for index, body in enumerate(pending):
                try:
                    reply = session.request(body)
                except OSError:
                    for rest in pending[index:]:
                        spool.add(rest)
                    _lose()
                    _backoff()
                    return
                if not (isinstance(reply, dict) and reply.get("ok") is True):
                    for rest in pending[index:]:
                        spool.add(rest)
                    _backoff()
                    return
            attempt = 0

        def _reconnect() -> None:
            nonlocal session
            if session is not None or time.monotonic() < next_try:
                return
            try:
                fresh = open_session(who)
            except OSError:
                _backoff()
                return
            try:
                registered = fresh.request(
                    {"type": "register", "key": watch_id, "argv": steps[0]}
                )
            except OSError:
                registered = None
            if not (isinstance(registered, dict) and registered.get("ok") is True):
                try:
                    fresh.close()
                except OSError:
                    pass
                _backoff()
                return
            session = fresh
            _flush()

        _hop(_event_body(watch_id, "start", procs[0].pid, no_wake=no_wake))
        notes.start(time.monotonic())

        def _drain_notices() -> None:
            with lock:
                chunk = "".join(texts)
                texts.clear()
                total = int(counters.get("stdout", 0)) + int(counters.get("stderr", 0))
            for kind, cause in notes.feed(chunk, total, time.monotonic()):
                _hop(
                    _event_body(
                        watch_id,
                        kind,
                        procs[0].pid,
                        cause=cause,
                        no_wake=no_wake,
                    )
                )

        stopped = False
        while last.poll() is None:
            _drain_notices()
            if _flagged(who, watch_id):
                stopped = True
                break
            if session is not None and _pending(session._conn):
                try:
                    msg = session.read()
                except OSError:
                    _lose()
                    _backoff()
                    continue
                if (
                    isinstance(msg, dict)
                    and msg.get("type") == "stop"
                    and str(msg.get("watch_id") or "") == watch_id
                ):
                    if str(msg.get("reason") or "") == "sit-end":
                        continue
                    stopped = True
                    break
                continue
            if session is None or spool.items:
                if session is None:
                    _reconnect()
                elif time.monotonic() >= next_try:
                    _flush()
            time.sleep(0.05)
        # Stages still alive before tw ends them are tw-killed; ignore their codes.
        alive_non_last = {
            i for i, proc in enumerate(procs[:-1]) if proc.poll() is None
        }
        _end_all(procs)
        for pump in pumps:
            pump.join(2)
        _drain_notices()
        code = 0
        for index, proc in enumerate(procs):
            rc = proc.returncode
            if rc in (0, None):
                continue
            if index < len(procs) - 1 and index in alive_non_last:
                continue
            # SIGPIPE on a non-last stage is the pipe closing, not a real fail.
            if index < len(procs) - 1 and int(rc) in (-13,):
                continue
            code = int(rc)
            break
        if code == 0 and last.returncode not in (0, None):
            code = int(last.returncode)
        if session is None:
            _reconnect()
        if session is not None:
            _send_sample(session, watch_id, procs[0].pid, counters, lock, sink is not None)
        exit_body = _event_body(
            watch_id,
            "exit",
            procs[0].pid,
            exit_code=code,
            cause="stopped" if stopped else None,
            no_wake=no_wake,
        )
        _hop(exit_body)
        if session is not None and spool.items and time.monotonic() >= next_try:
            _flush()
        # Durable fallback when the link was down at exit (card 1098).
        if any(
            str(item.get("kind") or "") == "exit"
            and str(item.get("watch_id") or "") == watch_id
            for item in spool.items
        ):
            if not _http_event(exit_body):
                print(
                    "tw: exit not recorded (link down); mill connected shows it active",
                    file=sys.stderr,
                )
            else:
                spool.items[:] = [
                    item
                    for item in spool.items
                    if not (
                        str(item.get("kind") or "") == "exit"
                        and str(item.get("watch_id") or "") == watch_id
                    )
                ]
        return code
    finally:
        _end_all(procs)
        for pump in pumps:
            pump.join(1)
        if sink is not None:
            sink.close()
        _drop(who, watch_id)
        if session is not None:
            try:
                session.close()
            except OSError:
                pass
