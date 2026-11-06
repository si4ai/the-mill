# -*- coding: utf-8 -*-
"""Local named pipe. Windows only. WSL uses the unix socket."""
from __future__ import annotations

import ctypes
import threading
import time
from ctypes import wintypes
from typing import Any, Callable

PIPE_ACCESS_DUPLEX = 0x00000003
FILE_FLAG_OVERLAPPED = 0x40000000
PIPE_TYPE_BYTE = 0x00000000
PIPE_READMODE_BYTE = 0x00000000
PIPE_WAIT = 0x00000000
PIPE_REJECT_REMOTE_CLIENTS = 0x00000008
ERROR_PIPE_CONNECTED = 535
ERROR_BROKEN_PIPE = 109
ERROR_OPERATION_ABORTED = 995
ERROR_IO_PENDING = 997
PIPE_UNLIMITED_INSTANCES = 255
_WAIT_TIMEOUT = 258
_INFINITE = 0xFFFFFFFF

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateNamedPipeW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.c_void_p,
]
_kernel32.CreateNamedPipeW.restype = wintypes.HANDLE
_kernel32.ConnectNamedPipe.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
_kernel32.ConnectNamedPipe.restype = wintypes.BOOL
_kernel32.ReadFile.argtypes = [
    wintypes.HANDLE,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    ctypes.c_void_p,
]
_kernel32.ReadFile.restype = wintypes.BOOL
_kernel32.WriteFile.argtypes = [
    wintypes.HANDLE,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    ctypes.c_void_p,
]
_kernel32.WriteFile.restype = wintypes.BOOL
_kernel32.GetOverlappedResult.argtypes = [
    wintypes.HANDLE,
    ctypes.c_void_p,
    ctypes.POINTER(wintypes.DWORD),
    wintypes.BOOL,
]
_kernel32.GetOverlappedResult.restype = wintypes.BOOL
_kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.CreateEventW.restype = wintypes.HANDLE
_kernel32.SetEvent.argtypes = [wintypes.HANDLE]
_kernel32.SetEvent.restype = wintypes.BOOL
_kernel32.ResetEvent.argtypes = [wintypes.HANDLE]
_kernel32.ResetEvent.restype = wintypes.BOOL
_kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_kernel32.WaitForSingleObject.restype = wintypes.DWORD
_kernel32.WaitForMultipleObjects.argtypes = [
    wintypes.DWORD,
    ctypes.POINTER(wintypes.HANDLE),
    wintypes.BOOL,
    wintypes.DWORD,
]
_kernel32.WaitForMultipleObjects.restype = wintypes.DWORD
_kernel32.DisconnectNamedPipe.argtypes = [wintypes.HANDLE]
_kernel32.DisconnectNamedPipe.restype = wintypes.BOOL
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL
_kernel32.CancelIoEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
_kernel32.CancelIoEx.restype = wintypes.BOOL

_INVALID = ctypes.c_void_p(-1).value


class _OVERLAPPED(ctypes.Structure):
    _fields_ = [
        ("Internal", ctypes.c_void_p),
        ("InternalHigh", ctypes.c_void_p),
        ("Offset", wintypes.DWORD),
        ("OffsetHigh", wintypes.DWORD),
        ("hEvent", wintypes.HANDLE),
    ]


def pipe_name(desk: str) -> str:
    return "\\\\.\\pipe\\mill-tw-" + desk


def _event() -> int:
    handle = _kernel32.CreateEventW(None, True, False, None)
    if not handle:
        raise OSError(ctypes.get_last_error(), "event")
    return handle


def _blank(ov: _OVERLAPPED, event: int) -> None:
    ov.Internal = None
    ov.InternalHigh = None
    ov.Offset = 0
    ov.OffsetHigh = 0
    ov.hEvent = event


class _PipeIO:
    """One pipe instance. Read waits on data or on cancel(), so a stop can be written."""

    def __init__(self, handle: int) -> None:
        self._handle = handle
        self._read_event = _event()
        self._wake_event = _event()
        self._write_event = _event()
        self._read_ov = _OVERLAPPED()
        self._write_ov = _OVERLAPPED()

    def read(self, n: int) -> bytes:
        buf = ctypes.create_string_buffer(n)
        got = wintypes.DWORD(0)
        _kernel32.ResetEvent(self._read_event)
        _blank(self._read_ov, self._read_event)
        ok = _kernel32.ReadFile(
            self._handle, buf, n, ctypes.byref(got), ctypes.byref(self._read_ov)
        )
        if ok:
            return buf.raw[: got.value]
        err = ctypes.get_last_error()
        if err != ERROR_IO_PENDING:
            if err in (ERROR_BROKEN_PIPE, ERROR_OPERATION_ABORTED, 0):
                return b""
            raise OSError(err, "read")
        handles = (wintypes.HANDLE * 2)(self._read_event, self._wake_event)
        which = _kernel32.WaitForMultipleObjects(2, handles, False, _INFINITE)
        if which == 1:
            _kernel32.CancelIoEx(self._handle, ctypes.byref(self._read_ov))
            _kernel32.GetOverlappedResult(
                self._handle, ctypes.byref(self._read_ov), ctypes.byref(got), True
            )
            _kernel32.ResetEvent(self._wake_event)
            raise OSError(ERROR_OPERATION_ABORTED, "read")
        if which != 0:
            raise OSError(ctypes.get_last_error() or which, "read wait")
        if not _kernel32.GetOverlappedResult(
            self._handle, ctypes.byref(self._read_ov), ctypes.byref(got), False
        ):
            err = ctypes.get_last_error()
            if err in (ERROR_BROKEN_PIPE, ERROR_OPERATION_ABORTED, 0):
                return b""
            raise OSError(err, "read")
        return buf.raw[: got.value]

    def write(self, data: bytes) -> None:
        view = ctypes.create_string_buffer(data)
        wrote = wintypes.DWORD(0)
        _kernel32.ResetEvent(self._write_event)
        _blank(self._write_ov, self._write_event)
        ok = _kernel32.WriteFile(
            self._handle, view, len(data), ctypes.byref(wrote), ctypes.byref(self._write_ov)
        )
        if not ok:
            err = ctypes.get_last_error()
            if err != ERROR_IO_PENDING:
                raise OSError(err, "write")
            if _kernel32.WaitForSingleObject(self._write_event, _INFINITE) != 0:
                raise OSError(ctypes.get_last_error(), "write wait")
            if not _kernel32.GetOverlappedResult(
                self._handle, ctypes.byref(self._write_ov), ctypes.byref(wrote), False
            ):
                raise OSError(ctypes.get_last_error(), "write")
        if wrote.value != len(data):
            raise OSError(ctypes.get_last_error(), "short write")

    def cancel(self) -> None:
        if not _kernel32.SetEvent(self._wake_event):
            raise OSError(ctypes.get_last_error(), "cancel")

    def close(self) -> None:
        for handle in (self._read_event, self._wake_event, self._write_event):
            if handle:
                _kernel32.CloseHandle(handle)
        self._read_event = 0
        self._wake_event = 0
        self._write_event = 0


class Pipe:
    kind = "pipe"

    def __init__(self, desk: str) -> None:
        self.address = pipe_name(desk)

    def serve(
        self,
        stop: threading.Event,
        on_conn: Callable[[Any], None],
        ready: threading.Event,
    ) -> None:
        while not stop.is_set():
            handle = _kernel32.CreateNamedPipeW(
                self.address,
                PIPE_ACCESS_DUPLEX | FILE_FLAG_OVERLAPPED,
                PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS,
                PIPE_UNLIMITED_INSTANCES,
                8192,
                8192,
                0,
                None,
            )
            if not handle or handle == _INVALID:
                raise OSError(ctypes.get_last_error(), "pipe")
            if not ready.is_set():
                ready.set()
            if not self._wait_client(handle, stop):
                _kernel32.DisconnectNamedPipe(handle)
                _kernel32.CloseHandle(handle)
                if stop.is_set():
                    break
                continue
            # Return to CreateNamedPipe so the next wrapper is not stuck behind this one.
            threading.Thread(
                target=self._run_one,
                args=(handle, on_conn),
                name="mill-tw-peer",
                daemon=True,
            ).start()

    def _wait_client(self, handle: int, stop: threading.Event) -> bool:
        event = _event()
        ov = _OVERLAPPED()
        _blank(ov, event)
        try:
            ok = _kernel32.ConnectNamedPipe(handle, ctypes.byref(ov))
            if ok:
                return True
            err = ctypes.get_last_error()
            if err == ERROR_PIPE_CONNECTED:
                return True
            if err != ERROR_IO_PENDING:
                return False
            while not stop.is_set():
                which = _kernel32.WaitForSingleObject(event, 200)
                if which == 0:
                    got = wintypes.DWORD(0)
                    done = _kernel32.GetOverlappedResult(
                        handle, ctypes.byref(ov), ctypes.byref(got), False
                    )
                    return bool(done) or ctypes.get_last_error() == ERROR_PIPE_CONNECTED
                if which != _WAIT_TIMEOUT:
                    return False
            _kernel32.CancelIoEx(handle, ctypes.byref(ov))
            got = wintypes.DWORD(0)
            _kernel32.GetOverlappedResult(handle, ctypes.byref(ov), ctypes.byref(got), True)
            return False
        finally:
            _kernel32.CloseHandle(event)

    def _run_one(self, handle: int, on_conn: Callable[[Any], None]) -> None:
        io = _PipeIO(handle)
        try:
            on_conn(io)
        finally:
            io.close()
            _kernel32.DisconnectNamedPipe(handle)
            _kernel32.CloseHandle(handle)

    def connect(self) -> Any:
        deadline = time.time() + 2.0
        last: OSError | None = None
        while time.time() < deadline:
            try:
                return open(self.address, "r+b", buffering=0)
            except OSError as exc:
                last = exc
                time.sleep(0.02)
        if last is not None:
            raise last
        raise OSError("pipe")

    def cleanup(self) -> None:
        return None
