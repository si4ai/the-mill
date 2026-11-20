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


def bind_private(path: Path, backlog: int = 64) -> socket.socket:
    """Owner-only directory, umask before bind, refuse a path that already exists.

    The desk socket stays on Unix.serve (listen 16). A per-run endpoint uses
    this so a predictable path cannot be replaced out from under it.
    """
    if not hasattr(socket, "AF_UNIX"):
        raise OSError("no unix socket on this os")
    target = Path(path)
    if target.exists():
        raise OSError("endpoint exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(target.parent, 0o700)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    previous = os.umask(0o077)
    try:
        srv.bind(str(target))
    except OSError:
        srv.close()
        raise
    finally:
        os.umask(previous)
    os.chmod(target, 0o600)
    srv.listen(int(backlog))
    return srv


def server_pid(fileobj: Any) -> int:
    """Pid of the process that accepted this connection. 0 when this OS cannot say."""
    stamped = getattr(fileobj, "_mill_server_pid", None)
    if isinstance(stamped, int) and not isinstance(stamped, bool) and stamped > 0:
        return stamped
    fileno = getattr(fileobj, "fileno", None)
    if fileno is None:
        return 0
    try:
        fd = fileno()
    except (OSError, ValueError):
        return 0
    if not isinstance(fd, int) or fd < 0:
        return 0
    try:
        sock = socket.socket(fileno=fd)
    except (OSError, ValueError):
        return 0
    try:
        return peer_pid(sock)
    finally:
        try:
            sock.detach()
        except (OSError, ValueError):
            pass


def peer_pid(conn: socket.socket) -> int:
    """Pid on the other end of a connected unix socket. 0 when this OS cannot say."""
    import struct
    import sys

    try:
        if sys.platform.startswith("linux"):
            raw = conn.getsockopt(socket.SOL_SOCKET, 17, 12)
            pid, _uid, _gid = struct.unpack("iii", raw[:12])
            return int(pid)
        if sys.platform == "darwin":
            raw = conn.getsockopt(0, 0x002, 4)
            return int(struct.unpack("i", raw[:4])[0])
    except (OSError, struct.error):
        return 0
    return 0


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
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock = srv
        try:
            self._bind_desk(srv, path)
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

    def _bind_desk(self, srv: socket.socket, path: Path) -> None:
        """0700 directory and umask before bind. A stale socket does not block rebind."""
        previous = os.umask(0o077)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            os.chmod(path.parent, 0o700)
            if path.is_symlink() or path.exists():
                path.unlink()
            try:
                srv.bind(self.address)
            except OSError:
                if not (path.is_symlink() or path.exists()):
                    raise
                path.unlink()
                srv.bind(self.address)
        finally:
            os.umask(previous)

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
        try:
            conn.connect(self.address)
            pid = peer_pid(conn)
            fileobj = conn.makefile("rwb", buffering=0)
        except OSError:
            conn.close()
            raise
        try:
            fileobj._mill_server_pid = int(pid)
        except (AttributeError, TypeError):
            pass
        return fileobj

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
