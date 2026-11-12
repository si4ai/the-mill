# -*- coding: utf-8 -*-
"""Sitting connect's local task-wrapper link. Protocol is shared. The transport is not."""
from __future__ import annotations

import os
import re
import shlex
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from agent_coord.client.route_chain import add_route, route_path
from agent_coord.client.tw import protocol
from agent_coord.client.tw.transport import kind
from agent_coord.helpers.ident import desk as slug_desk

_DESK = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_STOP_REASONS = ("desk", "server", "overflow", "sit-end")


def _desk(name: str) -> str:
    who = slug_desk(name)
    if not who or _DESK.fullmatch(who) is None:
        raise ValueError("desk required")
    return who


def pointer_path(desk: str) -> Path:
    return route_path(desk).with_suffix(".tw")


def _open_transport(desk: str):
    who = _desk(desk)
    if kind() == "pipe":
        from agent_coord.client.tw.win_pipe import Pipe

        return Pipe(who)
    from agent_coord.client.tw.unix_sock import Unix

    return Unix(who, route_path(desk).parent)


def _argv_text(argv: Any) -> str:
    if isinstance(argv, str):
        text = argv.strip()
        if not text:
            raise ValueError("argv required")
        return text
    if not isinstance(argv, list) or not argv:
        raise ValueError("argv required")
    parts: list[str] = []
    for item in argv:
        if not isinstance(item, str) or item == "":
            raise ValueError("argv required")
        parts.append(item)
    if os.name == "nt":
        return subprocess.list2cmdline(parts)
    return shlex.join(parts)


def _byte_count(msg: dict[str, Any], name: str, previous: int) -> int:
    raw = msg.get(name + "_bytes")
    if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0:
        return raw
    text = msg.get(name)
    if isinstance(text, str):
        return len(text.encode("utf-8"))
    if isinstance(text, (bytes, bytearray)):
        return len(text)
    return previous


def _numeric(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, int] = {}
    for key, item in value.items():
        if isinstance(item, bool) or not isinstance(item, int):
            continue
        out[str(key)[:32]] = item
    return out


def _watch_id(msg: dict[str, Any]) -> str:
    raw = msg.get("watch_id")
    if isinstance(raw, bool) or raw is None:
        return ""
    if isinstance(raw, int):
        return str(raw)
    if isinstance(raw, str):
        return raw.strip()
    return ""


def _read_some(conn: Any) -> bytes:
    chunk = conn.read(1)
    return chunk or b""


def _read_line(conn: Any) -> bytes | None:
    buf = bytearray()
    while True:
        chunk = _read_some(conn)
        if not chunk:
            return None if not buf else bytes(buf)
        if chunk == b"\n":
            return bytes(buf)
        buf += chunk
        if len(buf) > protocol.LINE_MAX:
            raise ValueError("line too long")


def _discard_rest(conn: Any) -> None:
    """Read through the newline so a short reply is not stuck behind the rest of the line."""
    while True:
        chunk = _read_some(conn)
        if not chunk or chunk == b"\n":
            return


class _Peer:
    def __init__(self, conn: Any) -> None:
        self.conn = conn
        self.write_lock = threading.Lock()
        self.outbound: list[dict[str, Any]] = []
        self.watch_ids: set[str] = set()
        self.live = True
        self.done = threading.Event()


class Session:
    """Wrapper side of one sitting link. One connection, many frames."""

    def __init__(self, link: Link) -> None:
        self._conn = link._transport.connect()
        self._read_lock = threading.Lock()
        self._write_lock = threading.Lock()

    def send(self, obj: dict[str, Any]) -> None:
        self.send_raw(protocol.dumps(obj))

    def send_raw(self, data: bytes) -> None:
        with self._write_lock:
            self._conn.write(data)

    def read(self) -> dict[str, Any]:
        with self._read_lock:
            line = _read_line(self._conn)
        if line is None:
            raise OSError("closed")
        return protocol.loads(line)

    def request(self, obj: dict[str, Any]) -> dict[str, Any]:
        self.send(obj)
        return self.read()

    def close(self) -> None:
        close = getattr(self._conn, "close", None)
        if close is not None:
            close()

    @classmethod
    def from_conn(cls, conn: Any) -> Session:
        self = cls.__new__(cls)
        self._conn = conn
        self._read_lock = threading.Lock()
        self._write_lock = threading.Lock()
        return self


class Link:
    def __init__(self, desk: str) -> None:
        self.desk = _desk(desk)
        self.marks: list[str] = []
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._error: BaseException | None = None
        self._closed = False
        self._transport = _open_transport(self.desk)
        self._thread: threading.Thread | None = None
        self._peers: list[_Peer] = []
        self._by_watch: dict[str, _Peer] = {}
        self._peers_lock = threading.Lock()
        self._route_lock = threading.Lock()
        self._snap_lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._snapshots: dict[str, dict[str, Any]] = {}
        self._outbox = None
        self._sender: threading.Thread | None = None
        self._kick = threading.Event()
        self._down_marked = False
        self._reconcile_body: dict[str, Any] | None = None
        self._opened = False
        self._adopt: threading.Thread | None = None

    def start(self) -> None:
        """Serve this desk's link, unless another connect's link already serves it (card 1154).

        connect opens the link before the seat check, so a second connect for a
        sitting desk (busy, or --take) gets here too. It must not take the sitting
        connect's socket and pointer, or delete them when it exits. It waits instead
        and serves once that link is gone.
        """
        if self._transport.live():
            self._adopt = threading.Thread(
                target=self._adopt_loop, name="mill-tw-adopt-" + self.desk, daemon=True
            )
            self._adopt.start()
            return
        try:
            self._open()
        except OSError:
            self.close()
            raise

    def _adopt_loop(self) -> None:
        while not self._stop.wait(0.2):
            if self._transport.live():
                continue
            try:
                self._open()
            except OSError:
                self.marks.append("tw.adopt")
            return

    def _open(self) -> None:
        from agent_coord.client.tw.outbox import Outbox, outbox_path

        self._outbox = Outbox(outbox_path(self.desk))
        path = pointer_path(self.desk)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._opened = True
        path.write_text(kind() + " " + self._transport.address + "\n", encoding="utf-8")
        if os.name != "nt":
            os.chmod(path, 0o600)
        self._thread = threading.Thread(
            target=self._run, name="mill-tw-" + self.desk, daemon=True
        )
        self._thread.start()
        if not self._ready.wait(2.0):
            raise OSError("tw link did not open")
        if self._error is not None:
            raise OSError(str(self._error))
        self._drain_pending()
        self._live_watch_ids = self._reconcile_ghosts()
        self._post_reconcile(self._live_watch_ids)
        self._sender = threading.Thread(
            target=self._sender_loop, name="mill-tw-send-" + self.desk, daemon=True
        )
        self._sender.start()
        self._kick.set()

    def _drain_pending(self) -> None:
        for _ in range(256):
            if self._post_once() != "ok":
                return

    def _reconcile_ghosts(self) -> list[str]:
        from agent_coord.client.tw.proc import reconcile_ghosts

        if self._outbox is None:
            return []
        return reconcile_ghosts(self.desk, self._outbox)

    def _post_reconcile(self, live: list[str]) -> None:
        """one session hop once this process can see a sitting bridge.

        An over-long list is not sent, so none of the ids are dropped.
        A second socket before the sit exists consumes connect-wait's
        only frame, and that wait never returns.
        """
        if len(live) > 256:
            return
        self._reconcile_body = {
            "verb": "tw.reconcile",
            "live": [str(item) for item in live],
        }
        self._flush_reconcile()

    def _hop_can_send(self) -> bool:
        """true once a sit bridge is visible, or when connect has not opened the link yet.

        connect sets the before-sit flag, then opens this link, then sits.
        a hop in that gap would borrow a second socket.
        """
        from agent_coord.client.http import link_before_sit
        from agent_coord.client.seat.status import look

        try:
            if look().kind == "sitting":
                return True
        except Exception:
            return False
        try:
            return not link_before_sit()
        except Exception:
            return False

    def _flush_reconcile(self) -> None:
        with self._send_lock:
            body = self._reconcile_body
            if body is None or not self._hop_can_send():
                return
            self._reconcile_body = None
        try:
            got = self._call(body)
        except Exception:
            self.marks.append("tw.reconcile")
            return
        if not (isinstance(got, dict) and got.get("ok") is True):
            self.marks.append("tw.reconcile")

    def _run(self) -> None:
        try:
            self._transport.serve(self._stop, self._on_conn, self._ready)
        except Exception as exc:
            self._error = exc
            self._ready.set()

    def _push(self, peer: _Peer, obj: dict[str, Any]) -> None:
        data = protocol.dumps(obj)
        with peer.write_lock:
            peer.conn.write(data)

    def _flush(self, peer: _Peer) -> None:
        with peer.write_lock:
            batch = peer.outbound
            peer.outbound = []
            for obj in batch:
                peer.conn.write(protocol.dumps(obj))

    def _enqueue(self, peer: _Peer, obj: dict[str, Any]) -> bool:
        """Queue a connect-to-wrapper frame.

        On a Windows pipe the handler thread writes. cancel() wakes its read.
        A unix socket can write from this thread.
        """
        if not peer.live:
            return False
        with peer.write_lock:
            peer.outbound.append(obj)
        cancel = getattr(peer.conn, "cancel", None)
        if cancel is None:
            try:
                self._flush(peer)
            except OSError:
                return False
            return True
        try:
            cancel()
        except OSError:
            return False
        return True

    @staticmethod
    def _aborted(exc: OSError) -> bool:
        return exc.errno == 995 or getattr(exc, "winerror", None) == 995

    def _on_conn(self, conn: Any) -> None:
        with self._peers_lock:
            live = [peer for peer in self._peers if peer.live]
            if len(live) >= protocol.MAX_SESSIONS:
                self.marks.append("cap")
                peer = None
            else:
                peer = _Peer(conn)
                self._peers.append(peer)
        if peer is None:
            try:
                conn.write(protocol.dumps(protocol.reply(False, "cap", code="cap")))
                while _read_some(conn):
                    pass
            except OSError:
                pass
            return
        try:
            self._serve(peer)
        finally:
            peer.live = False
            with self._peers_lock:
                for wid in list(peer.watch_ids):
                    if self._by_watch.get(wid) is peer:
                        self._by_watch.pop(wid, None)
            if not self._stop.is_set():
                self._note_crash(peer)
            peer.done.set()

    def _serve(self, peer: _Peer) -> None:
        conn = peer.conn
        while True:
            try:
                self._flush(peer)
            except OSError:
                return
            if self._stop.is_set():
                return
            try:
                line = _read_line(conn)
            except ValueError:
                _discard_rest(conn)
                try:
                    self._push(peer, protocol.line_too_long())
                except OSError:
                    return
                continue
            except OSError as exc:
                if self._aborted(exc):
                    continue
                return
            if line is None:
                return
            try:
                msg = protocol.loads(line)
            except (UnicodeError, ValueError):
                try:
                    self._push(peer, protocol.reply(False, "bad line"))
                except OSError:
                    return
                continue
            try:
                reply = self._dispatch(peer, msg)
                if reply is not None:
                    self._push(peer, reply)
            except OSError:
                return

    def _dispatch(self, peer: _Peer, msg: dict[str, Any]) -> dict[str, Any] | None:
        kind_name = str(msg.get("type") or "")
        if kind_name == "register":
            return self._register(msg)
        if kind_name == "event":
            return self._event(peer, msg)
        if kind_name == "sample":
            return self._sample(msg)
        if kind_name == "status":
            return self._status(msg)
        return protocol.reply(False, "unknown type")

    def _register(self, msg: dict[str, Any]) -> dict[str, Any]:
        key = str(msg.get("key") or "").strip()
        if not key or any(ch in key for ch in "\r\n="):
            return protocol.reply(False, "key required")
        try:
            argv = _argv_text(msg.get("argv"))
        except ValueError:
            return protocol.reply(False, "argv required")
        with self._route_lock:
            add_route(self.desk, key, argv)
        return protocol.reply(True, "registered")

    def _event(self, peer: _Peer, msg: dict[str, Any]) -> dict[str, Any]:
        # Write the hop, ack, then the sender posts it. argv and streams stay here.
        wid = _watch_id(msg)
        body: dict[str, Any] = {}
        for key in ("watch_id", "desk", "card", "kind", "cause", "exit_code", "counts"):
            if key in msg:
                body[key] = msg[key]
        ts_ms = msg.get("ts_ms")
        if isinstance(ts_ms, int) and not isinstance(ts_ms, bool) and ts_ms >= 0:
            body["ts_ms"] = ts_ms
        if msg.get("wake") is False:
            body["wake"] = False
        if wid and "watch_id" not in body:
            body["watch_id"] = wid
        if self._outbox is None:
            self.marks.append("tw.event")
            return protocol.reply(False, "hop failed", wid or None)
        try:
            self._outbox.add(body)
        except OSError:
            self.marks.append("tw.event")
            return protocol.reply(False, "hop failed", wid or None)
        if wid:
            peer.watch_ids.add(wid)
            with self._peers_lock:
                self._by_watch[wid] = peer
            self._remember(wid, msg)
        self._kick.set()
        return protocol.reply(True, "accepted", wid or None)

    def _call(self, body: dict[str, Any]) -> Any:
        from agent_coord.client.http import mill_http_call

        return mill_http_call(body)

    def _post_once(self) -> str:
        if self._outbox is None:
            return "empty"
        if not self._hop_can_send():
            return "wait"
        from agent_coord.client.tw.outbox import send_pending

        with self._send_lock:
            result = send_pending(self._outbox, self._call)
        if result == "down":
            if not self._down_marked:
                self.marks.append("tw.event")
                self._down_marked = True
        elif result == "ok":
            self._down_marked = False
        return result

    def _sender_loop(self) -> None:
        while not self._stop.is_set():
            try:
                result = self._post_once()
            except Exception:
                result = "down"
            if self._stop.is_set():
                return
            if result == "ok":
                continue
            # events first, then the reconcile list, so a lost crash is not late.
            self._flush_reconcile()
            if result in ("empty", "wait"):
                self._kick.wait(0.5)
                self._kick.clear()
                continue
            if self._stop.wait(0.25):
                return

    def drain(self, limit: int = 32) -> str:
        """Send queued hops until one stays or the file is empty."""
        last = "empty"
        for _ in range(max(1, limit)):
            last = self._post_once()
            if last != "ok":
                return last
        return last

    def _note_crash(self, peer: _Peer) -> None:
        if self._outbox is None:
            return
        noted = False
        for wid in list(peer.watch_ids):
            with self._snap_lock:
                row = self._snapshots.get(wid)
                kind_name = str(row.get("kind") or "") if isinstance(row, dict) else ""
            if kind_name in ("exit", "crash"):
                continue
            try:
                box = self._outbox
                if box is None:
                    return
                box.add(
                    {
                        "watch_id": wid,
                        "kind": "crash",
                        "cause": "lost",
                        "ts_ms": time.time_ns() // 1_000_000,
                    }
                )
            except Exception:
                self.marks.append("tw.event")
                continue
            noted = True
            if isinstance(row, dict):
                with self._snap_lock:
                    row["kind"] = "crash"
                    if row.get("exit_code") is None:
                        row["exit_code"] = 1
        if noted:
            self._kick.set()

    def _sample(self, msg: dict[str, Any]) -> dict[str, Any]:
        # Local buffer only. stdout, stderr, log, and sample do not hop.
        wid = _watch_id(msg)
        if not wid:
            return protocol.reply(False, "watch_id required")
        self._remember(wid, msg)
        return protocol.reply(True, "noted", wid)

    def _status(self, msg: dict[str, Any]) -> dict[str, Any]:
        wid = _watch_id(msg)
        with self._snap_lock:
            if wid:
                row = self._snapshots.get(wid)
                if row is None:
                    return protocol.reply(False, "missing", wid)
                out = protocol.reply(True, "status", wid)
                out["snapshot"] = self._public(row)
                return out
            rows = [self._public(row) for _, row in sorted(self._snapshots.items())]
        out = protocol.reply(True, "status")
        out["snapshot"] = rows
        return out

    def _remember(self, wid: str, msg: dict[str, Any]) -> None:
        with self._snap_lock:
            row = self._snapshots.get(wid)
            if row is None:
                row = {
                    "watch_id": wid,
                    "pid": 0,
                    "kind": "",
                    "exit_code": None,
                    "stdout_bytes": 0,
                    "stderr_bytes": 0,
                    "log": False,
                    "sample": {},
                }
            if isinstance(msg.get("kind"), str) and msg["kind"].strip():
                row["kind"] = msg["kind"].strip()[:32]
            pid = msg.get("pid")
            if isinstance(pid, int) and not isinstance(pid, bool) and pid > 0:
                row["pid"] = pid
            code = msg.get("exit_code")
            if isinstance(code, int) and not isinstance(code, bool):
                row["exit_code"] = code
            row["stdout_bytes"] = _byte_count(msg, "stdout", row["stdout_bytes"])
            row["stderr_bytes"] = _byte_count(msg, "stderr", row["stderr_bytes"])
            if msg.get("log"):
                row["log"] = True
            sample = _numeric(msg.get("sample"))
            if sample:
                row["sample"] = sample
            self._snapshots[wid] = row

    def _public(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "watch_id": row["watch_id"],
            "pid": row["pid"],
            "kind": row["kind"],
            "exit_code": row["exit_code"],
            "stdout_bytes": row["stdout_bytes"],
            "stderr_bytes": row["stderr_bytes"],
            "log": bool(row["log"]),
            "sample": dict(row["sample"]),
        }

    def stop(self, watch_id: str, reason: str) -> bool:
        if reason not in _STOP_REASONS:
            return False
        wid = str(watch_id or "").strip()
        if not wid:
            return False
        with self._peers_lock:
            peer = self._by_watch.get(wid)
        if peer is None or not peer.live:
            return False
        return self._enqueue(peer, protocol.stop_frame(wid, reason))

    def _drop_peer(self, peer: _Peer) -> None:
        """Unblock a peer read so close does not leave the link accepting hops."""
        cancel = getattr(peer.conn, "cancel", None)
        if cancel is not None:
            try:
                cancel()
            except OSError:
                pass
            return
        fileno = getattr(peer.conn, "fileno", None)
        if fileno is None:
            return
        try:
            fd = fileno()
        except (OSError, ValueError):
            return
        if not isinstance(fd, int) or fd < 0:
            return
        import socket

        try:
            sock = socket.socket(fileno=fd)
        except (OSError, ValueError):
            return
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except (OSError, ValueError):
            pass
        finally:
            try:
                sock.detach()
            except (OSError, ValueError):
                pass

    def _wake(self) -> None:
        try:
            conn = self._transport.connect()
        except OSError:
            return
        close = getattr(conn, "close", None)
        if close is not None:
            try:
                close()
            except OSError:
                pass

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stop.set()
        adopt = self._adopt
        if adopt is not None and adopt is not threading.current_thread():
            adopt.join(3.0)
        with self._peers_lock:
            peers = [peer for peer in self._peers if peer.live]
        for peer in peers:
            for wid in list(peer.watch_ids):
                self._enqueue(peer, protocol.stop_frame(wid, "sit-end"))
            self._drop_peer(peer)
        if self._opened:
            self._wake()
        if self._thread is not None:
            self._thread.join(2.0)
        for peer in peers:
            peer.done.wait(0.5)
        self._kick.set()
        if self._sender is not None:
            self._sender.join(2.0)
        if self._outbox is not None:
            try:
                self._outbox.close()
            except Exception:
                pass
            self._outbox = None
        if not self._opened:
            return
        try:
            pointer_path(self.desk).unlink()
        except OSError:
            pass
        self._transport.cleanup()


def open_session(desk: str) -> Session:
    """Connect to the sitting link named by the desk pointer file."""
    who = _desk(desk)
    text = pointer_path(who).read_text(encoding="utf-8").strip()
    kind_name, _, _address = text.partition(" ")
    if kind_name == "pipe":
        from agent_coord.client.tw.win_pipe import Pipe

        conn = Pipe(who).connect()
    elif kind_name == "unix":
        from agent_coord.client.tw.unix_sock import Unix

        conn = Unix(who, pointer_path(who).parent).connect()
    else:
        raise OSError("bad pointer")
    return Session.from_conn(conn)


def serve(desk: str) -> Link:
    link = Link(desk)
    link.start()
    return link
