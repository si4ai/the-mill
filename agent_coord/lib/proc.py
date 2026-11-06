"""Is the lock holder still a live process? PID reuse is detected via start token."""

from __future__ import annotations

import os
import sys


def this_process() -> tuple[int, int]:
    pid = os.getpid()
    tok = proc_token(pid)
    return pid, int(tok or 0)


def proc_token(pid: int) -> int | None:
    """Process start token if `pid` is alive; None if dead or unknown."""
    if pid is None or int(pid) <= 0:
        return None
    pid = int(pid)
    if sys.platform == "win32":
        return _win_token(pid)
    return _posix_token(pid)


def parent_gone(pid: int | None, lookup=None) -> bool:
    """True when the launching process is gone.

    pid 0 means unknown: stay up. A live but unreadable process (lookup
    returns 0) is not gone.
    """
    if not pid or int(pid) <= 0:
        return False
    look = proc_token if lookup is None else lookup
    return look(int(pid)) is None


def holder_dead(pid: int | None, start: int | None) -> bool:
    """True if we are sure the recorded process is gone (or PID was reused)."""
    if not pid:
        return False
    tok = proc_token(int(pid))
    if tok is None:
        return True
    # 0 = live but unreadable (Windows access-denied, PID still in the snapshot).
    # Must not look like a start-token mismatch or we steal from a live PID.
    if tok == 0:
        return False
    if start and int(start) and tok != int(start):
        return True
    return False


def _posix_token(pid: int) -> int | None:
    path = f"/proc/{pid}/stat"
    try:
        with open(path, encoding="utf-8") as f:
            buf = f.read()
    except FileNotFoundError:
        return None
    except OSError:
        return None
    rpar = buf.rfind(")")
    if rpar < 0:
        return None
    fields = buf[rpar + 2 :].split()
    if len(fields) < 20:
        return None
    if fields[0] == "Z":
        return None
    try:
        return int(fields[19])
    except ValueError:
        return None


_ERROR_ACCESS_DENIED = 5
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_SYNCHRONIZE = 0x00100000
_STILL_ACTIVE = 259
_WAIT_OBJECT_0 = 0
_TH32CS_SNAPPROCESS = 0x2


def _win_token(pid: int) -> int | None:
    """Start token if pid is a live process; None if it has exited.

    After taskkill /F, OpenProcess often still succeeds (exited object) or
    fails with access denied (5) for a PID that is already gone. Neither of
    those must look live. A live process we cannot query returns 0 so
    holder_dead will not steal.
    """
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.GetExitCodeProcess.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.GetProcessTimes.restype = wintypes.BOOL
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]

    class FILETIME(ctypes.Structure):
        _fields_ = [
            ("dwLowDateTime", wintypes.DWORD),
            ("dwHighDateTime", wintypes.DWORD),
        ]

    rights = _PROCESS_QUERY_LIMITED_INFORMATION | _SYNCHRONIZE
    handle = kernel32.OpenProcess(rights, False, pid)
    if not handle:
        handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        can_wait = False
    else:
        can_wait = True

    if handle:
        try:
            if can_wait and kernel32.WaitForSingleObject(handle, 0) == _WAIT_OBJECT_0:
                return None
            exit_code = wintypes.DWORD()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                if exit_code.value != _STILL_ACTIVE:
                    return None
            create = FILETIME()
            exit_t = FILETIME()
            kernel = FILETIME()
            user = FILETIME()
            ok = kernel32.GetProcessTimes(
                handle,
                ctypes.byref(create),
                ctypes.byref(exit_t),
                ctypes.byref(kernel),
                ctypes.byref(user),
            )
            if not ok:
                return 0
            tok = (int(create.dwHighDateTime) << 32) | int(create.dwLowDateTime)
            return tok if tok else 0
        finally:
            kernel32.CloseHandle(handle)

    err = ctypes.get_last_error()
    if err == _ERROR_ACCESS_DENIED:
        running = _win_pid_running(pid)
        if running is True:
            return 0
        if running is False:
            return None
        return 0
    return None


def _win_pid_running(pid: int) -> bool | None:
    """True if the PID is in the process snapshot. None if the snapshot failed."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32.Process32FirstW.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(PROCESSENTRY32W),
    ]
    kernel32.Process32NextW.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(PROCESSENTRY32W),
    ]

    invalid = ctypes.c_void_p(-1).value
    snap = kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if not snap or snap == invalid:
        return None
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            if int(entry.th32ProcessID) == pid:
                return True
            ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
        return False
    finally:
        kernel32.CloseHandle(snap)


# agent-ux 1214: console-script launchers (pip writes mill.exe etc. on
# Windows). Each `mill <command>` runs launcher.exe -> python.exe, so python's
# parent is a fresh launcher per call, never the shell that ran
# `mill connect`. The connect bridge matches on the shell, so walk past them.
CONSOLE_LAUNCHERS = frozenset(
    {"mill.exe", "agent-coord.exe", "mill-hold.exe", "tw.exe"}
)
_MAX_LAUNCHER_HOPS = 3


def _win_process_table() -> dict[int, tuple[int, str]]:
    """pid -> (parent pid, exe file name) from one Toolhelp snapshot. {} on failure."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    invalid = ctypes.c_void_p(-1).value
    snap = kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if not snap or snap == invalid:
        return {}
    table: dict[int, tuple[int, str]] = {}
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            table[int(entry.th32ProcessID)] = (
                int(entry.th32ParentProcessID),
                str(entry.szExeFile or ""),
            )
            ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snap)
    return table


def _is_launcher(exe: str, *, in_venv: bool, python_exe: str) -> bool:
    name = (exe or "").strip().lower()
    if not name:
        return False
    if name in CONSOLE_LAUNCHERS:
        return True
    # A Windows venv python.exe is a redirector: it starts the base
    # python.exe as a child and waits. Same name as ours, only in a venv.
    if in_venv and name.startswith("python") and name == (python_exe or "").lower():
        return True
    return False


def shell_parent_pid(
    ppid: int | None = None,
    *,
    platform: str | None = None,
    table: dict[int, tuple[int, str]] | None = None,
    in_venv: bool | None = None,
    python_exe: str | None = None,
) -> int:
    """Parent pid with console-script launchers skipped (Windows only).

    Linux/Mac: console scripts exec python in place, so this is os.getppid().
    Windows: walk up past mill.exe-style launchers (and a venv python
    redirector) so `mill connect` and `mill <command>` started from the same
    shell agree on the shell pid, whichever launcher each used.
    """
    start = int(os.getppid() if ppid is None else ppid)
    plat = sys.platform if platform is None else platform
    if plat != "win32" or start <= 0:
        return start
    if table is None:
        try:
            table = _win_process_table()
        except Exception:
            table = {}
    if not table:
        return start
    if in_venv is None:
        in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    if python_exe is None:
        python_exe = os.path.basename(sys.executable or "")
    pid = start
    for _ in range(_MAX_LAUNCHER_HOPS):
        row = table.get(pid)
        if not row:
            break
        parent, exe = row
        if not _is_launcher(exe, in_venv=bool(in_venv), python_exe=python_exe):
            break
        if int(parent or 0) <= 0 or int(parent) == pid:
            break
        pid = int(parent)
    return pid
