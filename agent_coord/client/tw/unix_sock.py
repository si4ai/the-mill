# -*- coding: utf-8 -*-
"""Local unix socket. One transport for Linux, macOS, and WSL."""
from __future__ import annotations

import os
import socket
import threading
from pathlib import Path
from typing import Any, Callable


def socket_path(directory: Path, desk: str) -> Path:
    return directory / f"{desk}.tw.sock"


class Unix:
    kind = "unix"

    def __init__(self, desk: str, directory: Path) -> None:
        self.address = str(socket_path(directory, desk))
        self._sock: socket.socket | None = None
        self._ino = 0

    def serve(
        self,
        stop: threading.Event,
        on_conn: Callable[[Any], None],
        ready: threading.Event,
    ) -> None:
        if not hasattr(socket, "AF_UNIX"):
            raise OSError("no unix socket on this os")
        path = Path(self.address)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            path.unlink()
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock = srv
        try:
            srv.bind(self.address)
            self._ino = os.stat(self.address).st_ino
            os.chmod(self.address, 0o600)
            srv.listen(16)
            srv.settimeout(0.2)
            ready.set()
            while not stop.is_set():
                try:
                    conn, _ = srv.accept()
                except socket.timeout:
                    continue
                if stop.is_set():
                    conn.close()
                    break
                # The handler runs off this loop so one slow peer cannot stall the next.
                threading.Thread(
                    target=self._run_one,
                    args=(conn, on_conn),
                    name="mill-tw-peer",
                    daemon=True,
                ).start()
        finally:
            srv.close()
            self._sock = None
            self.cleanup()

    def _run_one(self, conn: socket.socket, on_conn: Callable[[Any], None]) -> None:
        fileobj = conn.makefile("rwb", buffering=0)
        try:
            on_conn(fileobj)
        finally:
            try:
                fileobj.close()
            finally:
                conn.close()

    def connect(self) -> Any:
        if not hasattr(socket, "AF_UNIX"):
            raise OSError("no unix socket on this os")
        conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        conn.connect(self.address)
        return conn.makefile("rwb", buffering=0)

    def live(self) -> bool:
        """True when another link already answers on this desk's socket (card 1154)."""
        if not hasattr(socket, "AF_UNIX"):
            return False
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        probe.settimeout(0.5)
        try:
            probe.connect(self.address)
        except OSError:
            return False
        finally:
            probe.close()
        return True

    def cleanup(self) -> None:
        """Remove the socket file only while it is still the one this link bound."""
        try:
            ino = os.stat(self.address).st_ino
        except OSError:
            return
        if self._ino and ino == self._ino:
            try:
                os.unlink(self.address)
            except OSError:
                pass
