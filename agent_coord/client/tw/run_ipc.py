# -*- coding: utf-8 -*-
"""Per-run endpoint for mill calls from a tw run's descendants (card 1223).

The sitting connect keeps the bearer. This process checks the caller and
forwards an allowlisted command over the connect it already has. The desk
pipe is a different socket and is not a mill front door.
"""
from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from agent_coord.client.outbound import canonical_command

LINE_MAX = 32768
INFLIGHT = 64
LISTEN = 64

ALLOW = frozenset(
    {
        "todo",
        "claim",
        "pass",
        "assign",
        "unclaim",
        "replace-body",
        "send",
        "reply",
        "mail-thread",
        "mark",
        "inbox",
        "rooms",
        "hold",
        "drop",
        "score",
    }
)

ERR_REFUSED = "command refused"
ERR_CAP = "over cap"
ERR_LONG = "line too long"
ERR_PEER = "not a descendant"
ERR_ENDED = "run ended"
ERR_SERVER = "server pid mismatch"
ERR_BAD = "bad line"

_DROP = frozenset({"desk", "owner", "token", "verb", "cmd", "watch_id", "sender_desk"})
_StartFn = Callable[[int], int | None]


def _home() -> Path:
    from agent_coord.config import mill_home

    return mill_home()


def _own(path: Path, *, directory: bool) -> None:
    mode = 0o700 if directory else 0o600
    try:
        os.chmod(path, mode)
    except OSError:
        pass
    if os.name != "nt":
        return
    try:
        from agent_coord.client.tokens import _acl_identity

        who = _acl_identity(windows=True)
    except Exception:
        who = ""
    if not who:
        return
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", who + ":F"],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=flags,
        )
    except (OSError, subprocess.SubprocessError):
        return


def process_start(pid: int) -> int | None:
    """Stable start stamp for pid. None when this OS cannot read one (fail closed)."""
    who = int(pid)
    if who <= 0:
        return None
    if os.name == "nt":
        return _win_start(who)
    if sys.platform.startswith("linux"):
        return _linux_start(who)
    if sys.platform == "darwin":
        return _darwin_start(who)
    return None


def _win_start(pid: int) -> int | None:
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL

    class FILETIME(ctypes.Structure):
        _fields_ = [("lo", wintypes.DWORD), ("hi", wintypes.DWORD)]

    kernel.GetProcessTimes.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(FILETIME),
        ctypes.POINTER(FILETIME),
        ctypes.POINTER(FILETIME),
        ctypes.POINTER(FILETIME),
    ]
    kernel.GetProcessTimes.restype = wintypes.BOOL
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    created = FILETIME()
    exited = FILETIME()
    kernel_time = FILETIME()
    user_time = FILETIME()
    try:
        ok = kernel.GetProcessTimes(
            handle,
            ctypes.byref(created),
            ctypes.byref(exited),
            ctypes.byref(kernel_time),
            ctypes.byref(user_time),
        )
        if not ok:
            return None
        return (int(created.hi) << 32) | int(created.lo)
    finally:
        kernel.CloseHandle(handle)


def _linux_start(pid: int) -> int | None:
    try:
        text = Path("/proc/%s/stat" % pid).read_text(encoding="utf-8")
        rest = text.rsplit(")", 1)[1].split()
        return int(rest[19])
    except (OSError, IndexError, ValueError):
        return None


def _darwin_start(pid: int) -> int | None:
    """Wall-clock seconds from ps. A failed read is None so the run refuses."""
    import datetime

    try:
        env = os.environ.copy()
        env["LC_ALL"] = "C"
        out = subprocess.check_output(
            ["ps", "-p", str(pid), "-o", "lstart="],
            text=True,
            env=env,
            timeout=2,
        )
        stamp = datetime.datetime.strptime(out.strip(), "%a %b %d %H:%M:%S %Y")
        return int(stamp.replace(tzinfo=datetime.timezone.utc).timestamp())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def process_table() -> dict[int, tuple[int, str]]:
    """pid -> (parent pid, exe). Real parents, launchers included. {} on failure."""
    if os.name == "nt":
        try:
            from agent_coord.lib.proc import _win_process_table

            return _win_process_table()
        except Exception:
            return {}
    if sys.platform.startswith("linux"):
        return _linux_table()
    return _ps_table()


def _linux_table() -> dict[int, tuple[int, str]]:
    table: dict[int, tuple[int, str]] = {}
    root = Path("/proc")
    if not root.is_dir():
        return table
    for entry in root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            text = (entry / "stat").read_text(encoding="utf-8")
            rest = text.rsplit(")", 1)[1].split()
            table[int(entry.name)] = (int(rest[1]), "")
        except (OSError, IndexError, ValueError):
            continue
    return table


def _ps_table() -> dict[int, tuple[int, str]]:
    table: dict[int, tuple[int, str]] = {}
    try:
        out = subprocess.check_output(
            ["ps", "-ax", "-o", "pid=,ppid="],
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return table
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            table[int(parts[0])] = (int(parts[1]), "")
        except ValueError:
            continue
    return table


def is_descendant(
    caller: int,
    root: int,
    *,
    table: dict[int, tuple[int, str]],
    starts: dict[int, int | None],
    root_start: int,
    fetch: _StartFn | None = None,
) -> bool:
    """True when caller is root, or a real descendant, and neither pid was reused.

    caller start must be at or after root_start. root's live start must still
    equal the start recorded when the run opened. Launchers stay in the walk.
    """
    if int(caller) <= 0 or int(root) <= 0 or root_start is None:
        return False

    def start_of(pid: int) -> int | None:
        if pid in starts:
            return starts[pid]
        if fetch is None:
            return None
        value = fetch(pid)
        starts[pid] = value
        return value

    live_root = start_of(int(root))
    if live_root is None or int(live_root) != int(root_start):
        return False
    caller_start = start_of(int(caller))
    if caller_start is None or int(caller_start) < int(root_start):
        return False
    pid = int(caller)
    seen: set[int] = set()
    while pid > 0 and pid not in seen and len(seen) < 64:
        if pid == int(root):
            return True
        seen.add(pid)
        row = table.get(pid)
        if not row:
            return False
        parent = int(row[0])
        if parent <= 0 or parent == pid:
            return False
        pid = parent
    return False


def _read_pointer(home: Path, pid: int) -> dict[str, Any] | None:
    path = home / "tw-run" / str(int(pid)) / "pointer.json"
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(row, dict):
        return None
    try:
        if int(row.get("pid") or 0) != int(pid):
            return None
        if row.get("start") is None:
            return None
    except (TypeError, ValueError):
        return None
    if row.get("kind") not in ("pipe", "unix"):
        return None
    if not str(row.get("address") or "") or not str(row.get("watch_id") or ""):
        return None
    if not str(row.get("desk") or ""):
        return None
    return row


def lookup_parent(
    pid: int | None = None,
    *,
    table: dict[int, tuple[int, str]] | None = None,
    starts: dict[int, int | None] | None = None,
    home: Path | None = None,
    fetch: _StartFn | None = None,
) -> dict[str, Any] | None:
    """Nearest live tw on this process's real parent chain. None when there is none.

    The optional watch environment variable is not read. A pointer counts only
    when that pid's live start still matches the start the run recorded.
    """
    root = home if home is not None else _home()
    chain = table if table is not None else process_table()
    known = starts if starts is not None else {}
    if fetch is None and starts is None:
        fetch = process_start
    current = int(os.getpid() if pid is None else pid)
    seen: set[int] = set()
    while current > 0 and current not in seen and len(seen) < 64:
        seen.add(current)
        row = _read_pointer(root, current)
        if row is not None:
            if current in known:
                live = known[current]
            elif fetch is not None:
                live = fetch(current)
                known[current] = live
            else:
                live = None
            try:
                recorded = int(row["start"])
            except (TypeError, ValueError):
                recorded = -1
            if live is not None and int(live) == recorded:
                return row
        parent_row = chain.get(current)
        if not parent_row:
            break
        parent = int(parent_row[0])
        if parent <= 0 or parent == current:
            break
        current = parent
    return None


def _args(frame: dict[str, Any]) -> dict[str, Any]:
    raw = frame.get("args")
    if not isinstance(raw, dict):
        return {}
    return {key: value for key, value in raw.items() if key not in _DROP}


def _read_line(conn: Any, limit: int = LINE_MAX) -> bytes | None:
    buf = bytearray()
    while len(buf) <= limit:
        want = min(4096, limit + 1 - len(buf))
        if want <= 0:
            break
        chunk = conn.read(want)
        if not chunk:
            return None if not buf else bytes(buf)
        cut = chunk.find(b"\n")
        if cut >= 0:
            buf += chunk[:cut]
            if len(buf) > limit:
                raise ValueError(ERR_LONG)
            return bytes(buf)
        buf += chunk
    raise ValueError(ERR_LONG)


def _write_line(conn: Any, obj: dict[str, Any]) -> None:
    data = json.dumps(obj, separators=(",", ":"), default=str).encode("utf-8") + b"\n"
    if len(data) > LINE_MAX:
        raise OSError(ERR_LONG)
    view = data
    while view:
        wrote = conn.write(view)
        if wrote is None:
            break
        if wrote <= 0:
            raise OSError("short write")
        view = view[wrote:]
    flush = getattr(conn, "flush", None)
    if flush is not None:
        flush()


def _server_ok(pointer: dict[str, Any], server_pid: int, server_start: int | None) -> bool:
    try:
        return (
            server_start is not None
            and int(server_pid) == int(pointer["pid"])
            and int(server_start) == int(pointer["start"])
        )
    except (TypeError, ValueError, KeyError):
        return False


def _open_pipe(address: str) -> tuple[Any, int]:
    from agent_coord.client.tw.win_pipe import server_pid

    deadline = time.time() + 5.0
    last: OSError | None = None
    while time.time() < deadline:
        try:
            handle = open(address, "r+b", buffering=0)
        except OSError as exc:
            last = exc
            time.sleep(0.02)
            continue
        try:
            pid = server_pid(handle)
        except OSError:
            handle.close()
            raise
        return handle, pid
    if last is not None:
        raise last
    raise OSError("pipe")


def _open_unix(address: str) -> tuple[Any, int]:
    import socket

    from agent_coord.client.tw.unix_sock import peer_pid

    if not hasattr(socket, "AF_UNIX"):
        raise OSError("no unix socket on this os")
    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        conn.connect(address)
        pid = peer_pid(conn)
        return conn.makefile("rwb", buffering=0), pid
    except OSError:
        conn.close()
        raise


def call_parent(pointer: dict[str, Any], frame: dict[str, Any]) -> dict[str, Any]:
    """One request to a run endpoint. Checks the server pid before sending."""
    from agent_coord.helpers.errors import CoordError

    kind = str(pointer.get("kind") or "")
    address = str(pointer.get("address") or "")
    if kind == "pipe":
        conn, server = _open_pipe(address)
    elif kind == "unix":
        conn, server = _open_unix(address)
    else:
        raise OSError(ERR_ENDED)
    try:
        if not _server_ok(pointer, server, process_start(server)):
            raise CoordError(ERR_SERVER)
        _write_line(conn, frame)
        line = _read_line(conn)
        if not line:
            raise OSError("closed")
        msg = json.loads(line.decode("utf-8"))
        if not isinstance(msg, dict):
            raise OSError(ERR_BAD)
        return msg
    finally:
        close = getattr(conn, "close", None)
        if close is not None:
            try:
                close()
            except OSError:
                pass


def try_forward(body: dict[str, Any]) -> Any | None:
    """Forward one mill command when this process sits under a live tw run.

    None when no run is on the parent chain (the caller keeps its own path).
    A run that refuses, or a run that is already gone, raises.
    """
    from agent_coord.helpers.errors import CoordError

    found = lookup_parent()
    if not found:
        return None
    verb = canonical_command(str(body.get("verb") or body.get("cmd") or ""))
    frame = {"type": "call", "verb": verb, "args": _args(body)}
    try:
        reply = call_parent(found, frame)
    except CoordError:
        raise
    except OSError as exc:
        raise CoordError(ERR_ENDED) from exc
    if not isinstance(reply, dict) or reply.get("ok") is not True:
        raise CoordError(str((reply or {}).get("error") or ERR_REFUSED))
    result = reply.get("result")
    if isinstance(result, dict) and "ok" in result:
        return result
    return {"ok": True, "result": result, "sync": []}


def report_status() -> int:
    """Inside a verified run: one JSON line, desk and watch id, exit 0.

    Outside a run: the bridge hint and exit 1. The watch environment variable
    is not consulted.
    """
    from agent_coord.client.session_errors import bridge_hint
    from agent_coord.helpers.errors import CoordError

    found = lookup_parent()
    if not found:
        print(bridge_hint(), file=sys.stderr)
        return 1
    try:
        reply = call_parent(found, {"type": "status"})
    except CoordError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except OSError:
        print(bridge_hint(), file=sys.stderr)
        return 1
    if not isinstance(reply, dict) or reply.get("ok") is not True:
        print(str((reply or {}).get("error") or bridge_hint()), file=sys.stderr)
        return 1
    print(json.dumps({"desk": reply.get("desk"), "watch_id": reply.get("watch_id")}))
    return 0


class RelaySession:
    """Nested tw session. Events and calls go to the parent run, not the desk pipe."""

    relay = True

    def __init__(self, pointer: dict[str, Any], watch_id: str) -> None:
        self.pointer = pointer
        self.watch_id = str(watch_id)

    def request(self, frame: dict[str, Any]) -> dict[str, Any]:
        from agent_coord.helpers.errors import CoordError

        try:
            reply = call_parent(
                self.pointer,
                {"type": "relay", "watch_id": self.watch_id, "frame": frame},
            )
        except CoordError as exc:
            raise OSError(str(exc)) from exc
        if not isinstance(reply, dict):
            raise OSError("closed")
        return reply

    def close(self) -> None:
        return None


def relay_call(pointer: dict[str, Any]) -> Callable[[str, dict[str, Any], str], Any]:
    """call_fn for a nested run: the parent stamps the watch id it issued."""

    def call(verb: str, args: dict[str, Any], watch_id: str) -> Any:
        from agent_coord.helpers.errors import CoordError

        reply = call_parent(
            pointer,
            {
                "type": "relay",
                "watch_id": watch_id,
                "frame": {"type": "call", "verb": verb, "args": args},
            },
        )
        if not isinstance(reply, dict) or reply.get("ok") is not True:
            raise CoordError(str((reply or {}).get("error") or ERR_REFUSED))
        return reply.get("result")

    return call


def open_child(pointer: dict[str, Any], argv: list[str]) -> tuple[RelaySession, str, str]:
    """Ask the parent run for a child watch id. The parent refuses once it is exiting."""
    from agent_coord.helpers.errors import CoordError

    try:
        reply = call_parent(pointer, {"type": "child", "argv": list(argv)})
    except CoordError as exc:
        raise OSError(str(exc)) from exc
    if not isinstance(reply, dict) or reply.get("ok") is not True:
        raise OSError(str((reply or {}).get("error") or ERR_ENDED))
    watch_id = str(reply.get("watch_id") or "")
    desk = str(reply.get("desk") or "")
    if not watch_id or not desk:
        raise OSError(ERR_ENDED)
    return RelaySession(pointer, watch_id), watch_id, desk


class RunGate:
    """One run's endpoint. Open before the child. Close sets the exiting flag first."""

    def __init__(
        self,
        desk: str,
        watch_id: str,
        call_fn: Callable[[str, dict[str, Any], str], Any],
        event_fn: Callable[[dict[str, Any]], bool],
    ) -> None:
        self.desk = str(desk)
        self.watch_id = str(watch_id)
        self.call_fn = call_fn
        self.event_fn = event_fn
        self.pid = os.getpid()
        self.start = 0
        self.exiting = False
        self.inflight = 0
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.children: dict[str, dict[str, int]] = {}
        self.ready = threading.Event()
        self.error: BaseException | None = None
        self.kind = ""
        self.address = ""
        self._thread: threading.Thread | None = None
        self._pointer: Path | None = None
        self._pipe: Any = None
        self._srv: Any = None

    def begin_exit(self) -> None:
        self.exiting = True

    def open(self) -> None:
        self.pid = os.getpid()
        started = process_start(self.pid)
        if started is None:
            raise OSError("process start unreadable")
        self.start = int(started)
        try:
            if os.name == "nt":
                self._open_pipe()
            else:
                self._open_unix()
            self._write_pointer()
        except Exception:
            self.close()
            raise

    def _open_pipe(self) -> None:
        from agent_coord.client.tw.win_pipe import Pipe

        self.kind = "pipe"
        self.address = "\\\\.\\pipe\\mill-tw-run-" + secrets.token_hex(16)
        self._pipe = Pipe(
            "run",
            address=self.address,
            owner_only=True,
            first_instance=True,
            buffer_size=LINE_MAX,
        )
        self._thread = threading.Thread(target=self._serve_pipe, name="mill-tw-run", daemon=True)
        self._thread.start()
        if not self.ready.wait(5):
            raise OSError("run endpoint did not open")
        if self.error is not None:
            raise OSError("run endpoint did not open: %s" % self.error) from self.error

    def _serve_pipe(self) -> None:
        try:
            self._pipe.serve(self.stop, self._on_pipe, self.ready)
        except BaseException as exc:
            self.error = exc
            self.ready.set()

    def _on_pipe(self, io: Any) -> None:
        try:
            self._speak(io, int(getattr(io, "peer_pid", 0) or 0))
        except Exception:
            return

    def _open_unix(self) -> None:
        from agent_coord.client.tw.unix_sock import bind_private

        self.kind = "unix"
        directory = _home() / "tw-run" / str(self.pid)
        directory.mkdir(parents=True, exist_ok=True)
        _own(directory, directory=True)
        self.address = str(directory / ("sock-" + secrets.token_hex(8)))
        self._srv = bind_private(Path(self.address), LISTEN)
        self._thread = threading.Thread(target=self._serve_unix, name="mill-tw-run", daemon=True)
        self._thread.start()
        if not self.ready.wait(5):
            raise OSError("run endpoint did not open")

    def _serve_unix(self) -> None:
        import socket

        from agent_coord.client.tw.unix_sock import peer_pid

        srv = self._srv
        srv.settimeout(0.2)
        self.ready.set()
        try:
            while not self.stop.is_set():
                try:
                    conn, _addr = srv.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                if self.stop.is_set():
                    conn.close()
                    break
                pid = peer_pid(conn)
                threading.Thread(
                    target=self._speak_unix,
                    args=(conn, pid),
                    name="mill-tw-run-peer",
                    daemon=True,
                ).start()
        finally:
            try:
                srv.close()
            except OSError:
                pass

    def _speak_unix(self, conn: Any, peer: int) -> None:
        fileobj = conn.makefile("rwb", buffering=0)
        try:
            self._speak(fileobj, peer)
        finally:
            try:
                fileobj.close()
            finally:
                try:
                    conn.close()
                except OSError:
                    pass

    def _speak(self, conn: Any, peer_pid: int) -> None:
        try:
            try:
                line = _read_line(conn)
            except ValueError:
                _write_line(conn, {"ok": False, "error": ERR_LONG})
                return
            if not line:
                return
            try:
                frame = json.loads(line.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError):
                _write_line(conn, {"ok": False, "error": ERR_BAD})
                return
            if not isinstance(frame, dict):
                _write_line(conn, {"ok": False, "error": ERR_BAD})
                return
            peer_start = process_start(peer_pid) if peer_pid else None
            starts: dict[int, int | None] = {}
            if peer_pid and peer_start is not None:
                starts[int(peer_pid)] = peer_start
            live_root = process_start(self.pid)
            if live_root is not None:
                starts[int(self.pid)] = live_root
            reply = self.handle_frame(
                frame,
                peer_pid=int(peer_pid),
                peer_start=peer_start,
                table=process_table(),
                starts=starts,
                fetch=process_start,
            )
            _write_line(conn, reply)
        except OSError:
            return

    def handle_frame(
        self,
        frame: dict[str, Any],
        *,
        peer_pid: int,
        peer_start: int | None,
        table: dict[int, tuple[int, str]],
        starts: dict[int, int | None],
        fetch: _StartFn | None,
    ) -> dict[str, Any]:
        if not is_descendant(
            peer_pid,
            self.pid,
            table=table,
            starts=starts,
            root_start=self.start,
            fetch=fetch,
        ):
            return {"ok": False, "error": ERR_PEER}
        kind = str(frame.get("type") or "")
        if kind == "status":
            if self.exiting:
                return {"ok": False, "error": ERR_ENDED}
            return {"ok": True, "desk": self.desk, "watch_id": self.watch_id}
        if kind == "call":
            return self._forward_call(frame, self.watch_id)
        if kind == "child":
            return self._child(peer_pid, peer_start)
        if kind == "relay":
            return self._relay(frame, peer_pid, table, starts, fetch)
        return {"ok": False, "error": ERR_REFUSED}

    def _reserve(self) -> str | None:
        with self.lock:
            if self.exiting:
                return ERR_ENDED
            if self.inflight >= INFLIGHT:
                return ERR_CAP
            self.inflight += 1
            return None

    def _release(self) -> None:
        with self.lock:
            if self.inflight > 0:
                self.inflight -= 1

    def _forward_call(self, frame: dict[str, Any], watch_id: str) -> dict[str, Any]:
        from agent_coord.helpers.errors import CoordError

        verb = canonical_command(str(frame.get("verb") or ""))
        if verb not in ALLOW:
            return {"ok": False, "error": ERR_REFUSED}
        reason = self._reserve()
        if reason:
            return {"ok": False, "error": reason}
        try:
            result = self.call_fn(verb, _args(frame), watch_id)
        except CoordError as exc:
            return {"ok": False, "error": str(exc) or ERR_REFUSED}
        except Exception:
            return {"ok": False, "error": "forward failed"}
        finally:
            self._release()
        return {"ok": True, "result": result}

    def _child(self, peer_pid: int, peer_start: int | None) -> dict[str, Any]:
        reason = self._reserve()
        if reason:
            return {"ok": False, "error": reason}
        child = ""
        kept = False
        try:
            if peer_start is None:
                return {"ok": False, "error": ERR_PEER}
            child = "tw-" + uuid.uuid4().hex[:16]
            self.children[child] = {"pid": int(peer_pid), "start": int(peer_start)}
            event = {
                "type": "event",
                "watch_id": child,
                "kind": "start",
                "pid": int(peer_pid),
                "parent_watch_id": self.watch_id,
                "ts_ms": time.time_ns() // 1_000_000,
            }
            ok = bool(self.event_fn(event)) if self.event_fn is not None else False
            if not ok:
                return {"ok": False, "error": ERR_ENDED}
            kept = True
            return {
                "ok": True,
                "watch_id": child,
                "desk": self.desk,
                "parent": self.watch_id,
            }
        finally:
            if child and not kept:
                self.children.pop(child, None)
            self._release()

    def _relay(
        self,
        frame: dict[str, Any],
        peer_pid: int,
        table: dict[int, tuple[int, str]],
        starts: dict[int, int | None],
        fetch: _StartFn | None,
    ) -> dict[str, Any]:
        watch_id = str(frame.get("watch_id") or "")
        inner = frame.get("frame")
        issued = self.children.get(watch_id)
        if not watch_id or not isinstance(inner, dict) or not issued:
            return {"ok": False, "error": ERR_REFUSED}
        if not is_descendant(
            peer_pid,
            int(issued["pid"]),
            table=table,
            starts=starts,
            root_start=int(issued["start"]),
            fetch=fetch,
        ):
            return {"ok": False, "error": ERR_PEER}
        inner_type = str(inner.get("type") or "")
        if inner_type == "event":
            if self.exiting:
                return {"ok": False, "error": ERR_ENDED}
            event = dict(inner)
            event.setdefault("parent_watch_id", watch_id)
            ok = bool(self.event_fn(event)) if self.event_fn is not None else False
            if not ok:
                return {"ok": False, "error": ERR_ENDED}
            return {"ok": True}
        if inner_type == "call":
            return self._forward_call(inner, watch_id)
        return {"ok": False, "error": ERR_REFUSED}

    def _write_pointer(self) -> None:
        directory = _home() / "tw-run" / str(self.pid)
        directory.mkdir(parents=True, exist_ok=True)
        _own(directory.parent, directory=True)
        _own(directory, directory=True)
        body = {
            "watch_id": self.watch_id,
            "desk": self.desk,
            "start": self.start,
            "pid": self.pid,
            "kind": self.kind,
            "address": self.address,
        }
        target = directory / "pointer.json"
        tmp = directory / "pointer.json.tmp"
        tmp.write_text(json.dumps(body, separators=(",", ":")), encoding="utf-8")
        _own(tmp, directory=False)
        os.replace(tmp, target)
        _own(target, directory=False)
        self._pointer = target

    def close(self) -> None:
        self.begin_exit()
        self.stop.set()
        srv = self._srv
        if srv is not None:
            try:
                srv.close()
            except OSError:
                pass
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(2)
        pointer = self._pointer
        if pointer is not None:
            try:
                pointer.unlink(missing_ok=True)
            except OSError:
                pass
            self._pointer = None
        if self.kind == "unix" and self.address:
            try:
                os.unlink(self.address)
            except OSError:
                pass
        pipe = self._pipe
        if pipe is not None:
            try:
                pipe.release_security()
            except OSError:
                pass
