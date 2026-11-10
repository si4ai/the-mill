# -*- coding: utf-8 -*-
"""Run a command against the sitting link. Doing stays server-side."""
from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from agent_coord.client.tw.link import _desk, open_session, pointer_path


def runs_path(desk: str):
    pointer = pointer_path(_desk(desk))
    return pointer.with_name(pointer.name + ".runs.json")


def _ts_ms() -> int:
    return time.time_ns() // 1_000_000


def _iso(ms: int) -> str:
    return datetime.datetime.fromtimestamp(
        ms / 1000.0, datetime.timezone.utc
    ).strftime("%Y-%m-%dT%H:%M:%SZ")


def log_file(desk: str, watch_id: str) -> Path:
    pointer = pointer_path(_desk(desk))
    return pointer.with_name(pointer.name + "." + watch_id + ".log")


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


def _windows_image(pid: int) -> str:
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(32768)
        buf = ctypes.create_unicode_buffer(size.value)
        kernel.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
        ok = kernel.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size))
        if not ok:
            return ""
        return os.path.basename(buf.value)
    finally:
        kernel.CloseHandle(handle)


def _linux_image(pid: int) -> str:
    try:
        return os.path.basename(os.readlink("/proc/%s/exe" % pid))
    except OSError:
        return ""


def _darwin_image(pid: int) -> str:
    import ctypes

    try:
        lib = ctypes.CDLL("libproc.dylib", use_errno=True)
    except OSError:
        return ""
    buf = ctypes.create_string_buffer(4096)
    lib.proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    lib.proc_pidpath.restype = ctypes.c_int
    n = lib.proc_pidpath(int(pid), buf, 4096)
    if n <= 0:
        return ""
    return os.path.basename(buf.value[:n].decode("utf-8", "replace"))


def _image_name(pid: int) -> str:
    if pid <= 0:
        return ""
    if os.name == "nt":
        return _windows_image(pid)
    if sys.platform == "darwin":
        return _darwin_image(pid)
    return _linux_image(pid)


def _windows_cmdline(pid: int) -> str:
    """command line for this pid. empty if the pid is closed."""
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll")
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return ""
    try:
        ntdll.NtQueryInformationProcess.argtypes = [
            wintypes.HANDLE,
            wintypes.ULONG,
            wintypes.LPVOID,
            wintypes.ULONG,
            ctypes.POINTER(wintypes.ULONG),
        ]
        ntdll.NtQueryInformationProcess.restype = wintypes.LONG
        need = wintypes.ULONG(0)
        # 60 is ProcessCommandLineInformation. the first call sizes the buffer.
        ntdll.NtQueryInformationProcess(handle, 60, None, 0, ctypes.byref(need))
        size = max(int(need.value or 0), 16)
        buf = ctypes.create_string_buffer(size)
        status = ntdll.NtQueryInformationProcess(
            handle, 60, buf, size, ctypes.byref(need)
        )
        if status < 0 or status > 0:
            return ""
        length = int.from_bytes(buf.raw[:2], "little")
        if length <= 0:
            return ""
        ptr = int.from_bytes(buf.raw[8:16], "little")
        base = ctypes.addressof(buf)
        if base <= ptr < base + size:
            return ctypes.wstring_at(ptr, length // 2)
        end = min(16 + length, size)
        return buf.raw[16:end].decode("utf-16-le", "replace")
    finally:
        kernel.CloseHandle(handle)


def _posix_cmdline(pid: int) -> str:
    try:
        raw = Path("/proc/%s/cmdline" % pid).read_bytes()
    except OSError:
        raw = b""
    if raw:
        return " ".join(
            part.decode("utf-8", "replace") for part in raw.split(b"\0") if part
        )
    if sys.platform != "darwin":
        return ""
    try:
        out = subprocess.check_output(
            ["ps", "-p", str(int(pid)), "-o", "command="],
            stderr=subprocess.DEVNULL,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.decode("utf-8", "replace").strip()


def _cmdline(pid: int) -> str:
    if pid <= 0:
        return ""
    if os.name == "nt":
        return _windows_cmdline(pid)
    return _posix_cmdline(pid)


def _python_image(name: str) -> bool:
    base = name.lower()
    if base.endswith(".exe"):
        base = base[:-4]
    return base == "python" or base.startswith("python")


def _cmdline_is_tw(text: str) -> bool:
    """true when the command line is the tw console script or python -m of it."""
    if not text:
        return False
    folded = text.lower()
    if re.search(
        r"(?:^|[\s\"'])-m[\s\"']+agent_coord\.client\.tw(?:$|[\s\"'])",
        folded,
    ):
        return True
    # a path whose last step is the tw script. a later bare argument does not count.
    return re.search(r"[\\/]tw(?:\.exe)?(?=$|[\s\"'])", folded) is not None


def _still_tw(pid: int) -> bool:
    """the pid is alive and still the tw wrapper.

    a console script's image is python, not tw. the command line names tw.
    a reused pid whose program is python but not tw is not the wrapper.
    """
    if pid <= 0 or not _alive(pid):
        return False
    image = _image_name(pid).lower()
    if image in {"tw", "tw.exe"}:
        return True
    if not _python_image(image):
        return False
    return _cmdline_is_tw(_cmdline(pid))


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


def _reclaim_lost(desk: str) -> None:
    """Drop a row whose wrapper is already gone. connect records the crash."""
    runs = _load(desk)
    if not runs:
        return
    kept: dict[str, dict[str, Any]] = {}
    changed = False
    for watch_id, row in runs.items():
        if not isinstance(row, dict):
            changed = True
            continue
        if row.get("state") == "finished":
            kept[watch_id] = row
            continue
        tw_pid = int(row.get("tw_pid") or 0)
        if tw_pid and not _alive(tw_pid):
            if row.get("start") and row.get("exit_code") is None:
                kept[watch_id] = row
                continue
            changed = True
            continue
        kept[watch_id] = row
    if changed:
        _save(desk, kept)


def list_runs(desk: str) -> list[dict[str, Any]]:
    _reclaim_lost(desk)
    runs = _load(desk)
    kept: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    for watch_id, row in runs.items():
        if not isinstance(row, dict):
            continue
        pid = int(row.get("pid") or 0)
        finished = row.get("state") == "finished"
        if not finished and not _alive(pid):
            if row.get("start") and row.get("exit_code") is None:
                kept[watch_id] = row
            continue
        kept[watch_id] = row
        item: dict[str, Any] = {
            "watch_id": watch_id,
            "pid": pid,
            "argv": list(row.get("argv") or []),
        }
        if finished:
            item["exit_code"] = row.get("exit_code")
        rows.append(item)
    if kept != runs:
        _save(desk, kept)
    return rows


def running_runs(desk: str) -> list[dict[str, Any]]:
    """Runs still going. The pid here is tw's pid, the one a stop would signal."""
    stored = _load(desk)
    rows: list[dict[str, Any]] = []
    for row in list_runs(desk):
        if row.get("exit_code") is not None:
            continue
        full = stored.get(row["watch_id"])
        if not isinstance(full, dict):
            continue
        rows.append(
            {
                "watch_id": row["watch_id"],
                "tw_pid": int(full.get("tw_pid") or 0),
                "command": list(full.get("argv") or row.get("argv") or []),
                "start": str(full.get("start") or ""),
                "log": str(full.get("log") or ""),
            }
        )
    return rows


def stop_run(desk: str, watch_id: str) -> int:
    wid = str(watch_id or "").strip()
    runs = _load(desk)
    row = runs.get(wid)
    if not isinstance(row, dict):
        return 1
    if row.get("state") == "finished":
        return 0
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


def reconcile_ghosts(desk: str, outbox) -> list[str]:
    """A started run with no exit whose tw pid is gone or reused.

    Records a lost crash on the run and in the hop file. Returns watch ids
    that are still live. The host list stays unsent until its call is named.
    """
    runs = _load(desk)
    now = _ts_ms()
    live: list[str] = []
    changed = False
    for watch_id, row in list(runs.items()):
        if not isinstance(row, dict):
            continue
        if row.get("state") == "finished" or row.get("exit_code") is not None:
            continue
        if not row.get("start") or row.get("reconciled"):
            continue
        tw_pid = int(row.get("tw_pid") or 0)
        if _still_tw(tw_pid):
            live.append(watch_id)
            continue
        body = {
            "watch_id": watch_id,
            "kind": "crash",
            "cause": "lost",
            "exit_code": 1,
            "ts_ms": now,
        }
        try:
            outbox.add(body)
        except OSError:
            continue
        fresh = dict(row)
        fresh["state"] = "finished"
        fresh["exit_code"] = 1
        fresh["cause"] = "lost"
        fresh["ts_ms"] = now
        fresh["reconciled"] = True
        fresh["tw_pid"] = 0
        runs.pop(watch_id, None)
        runs[watch_id] = fresh
        changed = True
    if changed:
        finished = [
            key
            for key, item in runs.items()
            if isinstance(item, dict) and item.get("state") == "finished"
        ]
        for key in finished[:-20]:
            runs.pop(key, None)
        _save(desk, runs)
    return live


def _store_finished(desk: str, watch_id: str, row: dict[str, Any]) -> None:
    """Keep a finished run so a later list can show its exit."""
    runs = _load(desk)
    runs.pop(watch_id, None)
    runs[watch_id] = row
    finished = [
        key
        for key, item in runs.items()
        if isinstance(item, dict) and item.get("state") == "finished"
    ]
    for key in finished[:-20]:
        runs.pop(key, None)
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
        if row.get("exit_code") is not None:
            rows.append(
                {
                    "watch_id": row["watch_id"],
                    "pid": int(row["pid"]),
                    "kind": "exit",
                    "exit_code": row["exit_code"],
                    "stdout_bytes": 0,
                    "stderr_bytes": 0,
                    "log": False,
                    "sample": {},
                }
            )
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


def _mirror(stream: Any, chunk: bytes) -> None:
    buf = getattr(stream, "buffer", None)
    if buf is not None:
        buf.write(chunk)
        buf.flush()
        return
    stream.write(chunk.decode("utf-8", "replace"))
    stream.flush()


def _pump(stream: Any, sink: Any, key: str, lock: Any, counters: dict[str, int], mirror: Any) -> None:
    if stream is None:
        return
    while True:
        # one byte. a 4096 read on a pipe waits until that many bytes or exit.
        chunk = stream.read(1)
        if not chunk:
            return
        with lock:
            counters[key] = counters.get(key, 0) + len(chunk)
            if sink is not None:
                sink.write(chunk)
                sink.flush()
            if mirror is not None:
                try:
                    _mirror(mirror, chunk)
                except OSError:
                    pass


def _event_body(
    watch_id: str,
    kind: str,
    pid: int,
    *,
    cause: str | None = None,
    exit_code: int | None = None,
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
    msg["ts_ms"] = _ts_ms()
    return msg


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


def _assign_job(pid: int):
    """Windows: the child ends when the job handle closes with this process."""
    if os.name != "nt" or pid <= 0:
        return None
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)

    class _Basic(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _Io(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class _Ext(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _Basic),
            ("IoInfo", _Io),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    job = kernel.CreateJobObjectW(None, None)
    if not job:
        return None
    info = _Ext()
    info.BasicLimitInformation.LimitFlags = 0x2000
    if not kernel.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
        kernel.CloseHandle(job)
        return None
    proc = kernel.OpenProcess(0x0101, False, pid)
    if not proc:
        kernel.CloseHandle(job)
        return None
    ok = kernel.AssignProcessToJobObject(job, proc)
    kernel.CloseHandle(proc)
    if not ok:
        kernel.CloseHandle(job)
        return None
    return job


def _close_job(job) -> None:
    if not job:
        return
    import ctypes

    ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(job)


def _arm_forward(procs: list[Any], killed: threading.Event):
    """Forward a stop of this process to the child. Returns a restore callable."""
    if os.name == "nt":
        import ctypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        handler_type = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_uint)

        def _on_ctrl(ctrl):
            if ctrl in (0, 1):
                killed.set()
                _end_all(procs)
            return 0

        held = handler_type(_on_ctrl)
        kernel.SetConsoleCtrlHandler(held, 1)

        def restore() -> None:
            kernel.SetConsoleCtrlHandler(held, 0)

        restore.held = held
        return restore

    import signal

    previous: dict[int, Any] = {}

    def _on_signal(signum, frame):
        killed.set()
        _end_all(procs)
        prev = previous.get(signum)
        if callable(prev):
            prev(signum, frame)

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            previous[sig] = signal.signal(sig, _on_signal)
        except (ValueError, OSError):
            pass

    def restore() -> None:
        for sig, prev in previous.items():
            try:
                signal.signal(sig, prev)
            except (ValueError, OSError):
                pass

    return restore


def _recipe() -> None:
    from agent_coord.client.session_errors import bridge_hint

    print(bridge_hint(), file=sys.stderr)


def run_argv(
    desk: str,
    argv: list[str],
    log_path: str | None = None,
    *,
    arm_forward: bool = False,
) -> int:
    who = _desk(desk)
    _reclaim_lost(who)
    if not argv or any(not isinstance(part, str) or part == "" for part in argv):
        return 2
    watch_id = "tw-" + uuid.uuid4().hex[:16]
    session: Any = None
    sink = None
    pumps: list[threading.Thread] = []
    procs: list[Any] = []
    finished: dict[str, Any] | None = None
    started = False
    job = None
    restore = None
    killed = threading.Event()
    try:
        try:
            session = open_session(who)
        except OSError:
            _recipe()
            return 1
        try:
            registered = session.request({"type": "register", "key": watch_id, "argv": list(argv)})
        except OSError:
            _recipe()
            return 1
        if not (isinstance(registered, dict) and registered.get("ok") is True):
            return 1
        try:
            proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        procs.append(proc)
        job = _assign_job(proc.pid)
        if arm_forward:
            restore = _arm_forward(procs, killed)
        target = Path(log_path) if log_path else log_file(who, watch_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        sink = open(target, "ab")
        print("%s %s %s" % (watch_id, os.getpid(), target), file=sys.stderr, flush=True)
        lock = threading.Lock()
        counters = {"stdout": 0, "stderr": 0}
        pumps.append(
            threading.Thread(
                target=_pump,
                args=(proc.stdout, sink, "stdout", lock, counters, sys.stdout),
                daemon=True,
            )
        )
        pumps.append(
            threading.Thread(
                target=_pump,
                args=(proc.stderr, sink, "stderr", lock, counters, sys.stderr),
                daemon=True,
            )
        )
        for pump in pumps:
            pump.start()
        observed_ms = _ts_ms()
        observed = _iso(observed_ms)
        runs = _load(who)
        runs[watch_id] = {
            "pid": proc.pid,
            "argv": list(argv),
            "stop": False,
            "tw_pid": os.getpid(),
            "log": str(target),
            "start": observed,
        }
        _save(who, runs)
        started = True
        noted = False

        def _lose() -> None:
            nonlocal session
            if session is None:
                return
            try:
                session.close()
            except OSError:
                pass
            session = None

        def _note() -> None:
            nonlocal noted
            if noted:
                return
            noted = True
            _recipe()

        def _send(body: dict[str, Any]) -> bool:
            if session is None:
                _note()
                return False
            try:
                reply = session.request(body)
            except OSError:
                _lose()
                _note()
                return False
            return isinstance(reply, dict) and reply.get("ok") is True

        start_body = _event_body(watch_id, "start", proc.pid)
        start_body["ts_ms"] = observed_ms
        _send(start_body)
        stopped = False
        crashed = False
        while proc.poll() is None:
            if killed.is_set():
                crashed = True
                break
            if _flagged(who, watch_id):
                stopped = True
                break
            if session is not None:
                try:
                    ready = _pending(session._conn)
                except OSError:
                    _lose()
                    _note()
                    ready = False
                if ready:
                    try:
                        msg = session.read()
                    except OSError:
                        _lose()
                        _note()
                        continue
                    if (
                        isinstance(msg, dict)
                        and msg.get("type") == "stop"
                        and str(msg.get("watch_id") or "") == watch_id
                        and str(msg.get("reason") or "") != "sit-end"
                    ):
                        stopped = True
                        break
                    continue
            time.sleep(0.05)
        if stopped or crashed:
            _end_all(procs)
        else:
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                _end_all(procs)
        for pump in pumps:
            pump.join(2)
        with lock:
            stdout_bytes = int(counters.get("stdout", 0))
            stderr_bytes = int(counters.get("stderr", 0))
        code = proc.returncode
        if code is None:
            code = 1
        code = int(code)
        # a signal death is negative. recording it as a plain exit and
        # returning it makes tw itself exit with the low 8 bits (15 -> 241).
        signaled = code < 0
        if signaled:
            code = 128 + ((-code) & 127)
        if crashed or signaled:
            body = _event_body(
                watch_id, "crash", proc.pid, cause="killed", exit_code=code
            )
        else:
            body = _event_body(
                watch_id,
                "exit",
                proc.pid,
                exit_code=code,
                cause="stopped" if stopped else None,
            )
        body["stdout_bytes"] = stdout_bytes
        body["stderr_bytes"] = stderr_bytes
        body["log"] = True
        _send(body)
        finished = {
            "pid": proc.pid,
            "argv": list(argv),
            "stop": False,
            "tw_pid": 0,
            "state": "finished",
            "exit_code": code,
            "log": str(target),
        }
        return code
    finally:
        _end_all(procs)
        for pump in pumps:
            pump.join(1)
        if restore is not None:
            restore()
        _close_job(job)
        if sink is not None:
            sink.close()
        if finished is not None:
            _store_finished(who, watch_id, finished)
        elif started:
            _drop(who, watch_id)
        if session is not None:
            try:
                session.close()
            except OSError:
                pass
