# -*- coding: utf-8 -*-
"""tw run, list, and stop. The child talks to the sitting link. Doing stays server-side."""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import uuid
from typing import Any

from agent_coord.client.tw.link import _desk, open_session, pointer_path
from agent_coord.client.tw.sample import take


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


def list_runs(desk: str) -> list[dict[str, Any]]:
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


def query_status(desk: str, watch_id: str | None = None) -> dict[str, Any]:
    who = _desk(desk)
    try:
        session = open_session(who)
    except OSError:
        return {"type": "reply", "ok": False, "msg": "down"}
    try:
        msg: dict[str, Any] = {"type": "status"}
        if watch_id:
            msg["watch_id"] = watch_id
        reply = session.request(msg)
        return reply if isinstance(reply, dict) else {"type": "reply", "ok": False, "msg": "bad"}
    except OSError:
        return {"type": "reply", "ok": False, "msg": "down"}
    finally:
        session.close()


def _pump(stream: Any, sink: Any, key: str, lock: Any, counters: dict[str, int]) -> None:
    if stream is None:
        return
    while True:
        chunk = stream.read(4096)
        if not chunk:
            return
        with lock:
            counters[key] = counters.get(key, 0) + len(chunk)
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


def run_argv(desk: str, argv: list[str], log_path: str | None = None) -> int:
    who = _desk(desk)
    if not argv or any(not isinstance(part, str) or part == "" for part in argv):
        return 2
    watch_id = "tw-" + uuid.uuid4().hex[:16]
    try:
        session = open_session(who)
    except OSError:
        return 1
    try:
        registered = session.request(
            {"type": "register", "key": watch_id, "argv": argv}
        )
        if not (isinstance(registered, dict) and registered.get("ok") is True):
            return 1
        sink = None
        pumps: list[threading.Thread] = []
        lock = threading.Lock()
        counters = {"stdout": 0, "stderr": 0}
        proc = None
        try:
            if log_path:
                sink = open(log_path, "ab")
            proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            pumps = [
                threading.Thread(
                    target=_pump,
                    args=(proc.stdout, sink, "stdout", lock, counters),
                    daemon=True,
                ),
                threading.Thread(
                    target=_pump,
                    args=(proc.stderr, sink, "stderr", lock, counters),
                    daemon=True,
                ),
            ]
            for pump in pumps:
                pump.start()
            runs = _load(who)
            runs[watch_id] = {"pid": proc.pid, "argv": argv, "stop": False}
            _save(who, runs)
            print(watch_id, flush=True)
            started = session.request(
                {
                    "type": "event",
                    "watch_id": watch_id,
                    "kind": "start",
                    "pid": proc.pid,
                }
            )
            if not (isinstance(started, dict) and started.get("ok") is True):
                return 1
            while proc.poll() is None:
                if _flagged(who, watch_id):
                    break
                if _pending(session._conn):
                    msg = session.read()
                    if (
                        isinstance(msg, dict)
                        and msg.get("type") == "stop"
                        and str(msg.get("watch_id") or "") == watch_id
                    ):
                        break
                    continue
                time.sleep(0.1)
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2)
            for pump in pumps:
                pump.join(2)
            code = proc.returncode if proc.returncode is not None else 1
            _send_sample(session, watch_id, proc.pid, counters, lock, sink is not None)
            try:
                session.send(
                    {
                        "type": "event",
                        "watch_id": watch_id,
                        "kind": "exit",
                        "exit_code": code,
                        "pid": proc.pid,
                    }
                )
            except OSError:
                pass
            return code
        finally:
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2)
            for pump in pumps:
                pump.join(1)
            if sink is not None:
                sink.close()
    finally:
        _drop(who, watch_id)
        session.close()
