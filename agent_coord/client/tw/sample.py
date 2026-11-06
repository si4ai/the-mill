# -*- coding: utf-8 -*-
"""Small numeric sample of one child. Text stays out."""
from __future__ import annotations

import os


def take(pid: int) -> dict[str, int]:
    """threads, children, rss, cpu_ms, sockets. Missing keys mean unknown."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return {}
    try:
        if os.name == "nt":
            return _nt(pid)
        return _posix(pid)
    except OSError:
        return {}


def _posix(pid: int) -> dict[str, int]:
    out: dict[str, int] = {}
    status_path = "/proc/%s/status" % pid
    try:
        text = open(status_path, encoding="utf-8").read()
    except OSError:
        return {}
    for line in text.splitlines():
        if line.startswith("Threads:"):
            out["threads"] = int(line.split()[1])
        elif line.startswith("VmRSS:"):
            out["rss"] = int(line.split()[1]) * 1024
    try:
        stat = open("/proc/%s/stat" % pid, encoding="utf-8").read()
        rest = stat[stat.rfind(")") + 2 :].split()
        ticks = os.sysconf("SC_CLK_TCK") or 100
        out["cpu_ms"] = (int(rest[11]) + int(rest[12])) * 1000 // int(ticks)
    except (OSError, IndexError, ValueError):
        pass
    children = 0
    sockets = 0
    try:
        for name in os.listdir("/proc"):
            if not name.isdigit():
                continue
            try:
                raw = open("/proc/%s/stat" % name, encoding="utf-8").read()
                rest = raw[raw.rfind(")") + 2 :].split()
                if int(rest[1]) == pid:
                    children += 1
            except (OSError, IndexError, ValueError):
                continue
    except OSError:
        pass
    out["children"] = children
    fd_dir = "/proc/%s/fd" % pid
    try:
        for name in os.listdir(fd_dir):
            try:
                target = os.readlink(os.path.join(fd_dir, name))
            except OSError:
                continue
            if target.startswith("socket:"):
                sockets += 1
    except OSError:
        pass
    out["sockets"] = sockets
    return out


def _nt(pid: int) -> dict[str, int]:
    import ctypes
    from ctypes import wintypes

    ulong_ptr = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ulong_ptr),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_char * 260),
        ]

    class FILETIME(ctypes.Structure):
        _fields_ = [
            ("dwLowDateTime", wintypes.DWORD),
            ("dwHighDateTime", wintypes.DWORD),
        ]

    class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    kernel.Process32First.argtypes = [ctypes.c_void_p, ctypes.POINTER(PROCESSENTRY32)]
    kernel.Process32Next.argtypes = [ctypes.c_void_p, ctypes.POINTER(PROCESSENTRY32)]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.GetProcessTimes.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(FILETIME),
        ctypes.POINTER(FILETIME),
        ctypes.POINTER(FILETIME),
        ctypes.POINTER(FILETIME),
    ]

    out: dict[str, int] = {}
    snap = kernel.CreateToolhelp32Snapshot(0x2, 0)
    invalid = ctypes.c_void_p(-1).value
    if snap and snap != invalid:
        entry = PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
        threads = 0
        children = 0
        ok = kernel.Process32First(snap, ctypes.byref(entry))
        while ok:
            if int(entry.th32ProcessID) == pid:
                threads = int(entry.cntThreads)
            if int(entry.th32ParentProcessID) == pid:
                children += 1
            ok = kernel.Process32Next(snap, ctypes.byref(entry))
        kernel.CloseHandle(snap)
        if threads:
            out["threads"] = threads
        out["children"] = children

    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return out
    try:
        created, exited, kernel_t, user_t = FILETIME(), FILETIME(), FILETIME(), FILETIME()
        if kernel.GetProcessTimes(
            handle,
            ctypes.byref(created),
            ctypes.byref(exited),
            ctypes.byref(kernel_t),
            ctypes.byref(user_t),
        ):
            def _ticks(item: FILETIME) -> int:
                return (int(item.dwHighDateTime) << 32) + int(item.dwLowDateTime)

            out["cpu_ms"] = (_ticks(kernel_t) + _ticks(user_t)) // 10000
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD]
        pmc = PROCESS_MEMORY_COUNTERS()
        pmc.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
        if psapi.GetProcessMemoryInfo(handle, ctypes.byref(pmc), pmc.cb):
            out["rss"] = int(pmc.WorkingSetSize)
    finally:
        kernel.CloseHandle(handle)
    out.setdefault("sockets", 0)
    return out
