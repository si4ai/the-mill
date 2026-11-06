# -*- coding: utf-8 -*-
"""Sitting connect's local task-wrapper link. Protocol is shared. The transport is not."""
from __future__ import annotations

import os
import re
import shlex
import subprocess
import threading
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

    def start(self) -> None:
        path = pointer_path(self.desk)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(kind() + " " + self._transport.address + "\n", encoding="utf-8")
        if os.name != "nt":
            os.chmod(path, 0o600)
        self._thread = threading.Thread(
            target=self._run, name="mill-tw-" + self.desk, daemon=True
        )
        self._thread.start()
        if not self._ready.wait(2.0):
            self.close()
            raise OSError("tw link did not open")
        if self._error is not None:
            err = self._error
            self.close()
            raise OSError(str(err))

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
                conn.write(protocol.dumps(protocol.reply(False, "cap")))
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
        # Hop before ok (letter 4618). Doing scores stay server-side; this slice
        # only posts tw.event and writes no doing / tw_* row itself.
        wid = _watch_id(msg)
        body: dict[str, Any] = {"verb": "tw.event"}
        for key in ("watch_id", "desk", "card", "kind", "cause", "exit_code", "counts",
                    "argv", "title", "pattern"):
            if key in msg:
                body[key] = msg[key]
        if wid and "watch_id" not in body:
            body["watch_id"] = wid
        try:
            from agent_coord.client.http import mill_http_call

            got = mill_http_call(body)
        except Exception as exc:
            self.marks.append("tw.event")
            msg_text = str(exc) if str(exc) else "hop failed"
            return protocol.reply(False, msg_text[:200], wid or None)
        ok = isinstance(got, dict) and got.get("ok") is True
        if not ok:
            self.marks.append("tw.event")
            err = ""
            if isinstance(got, dict):
                err = str(got.get("error") or "")
                result = got.get("result")
                if not err and isinstance(result, dict):
                    err = str(result.get("error") or result.get("msg") or "")
            return protocol.reply(False, (err or "hop failed")[:200], wid or None)
        if wid:
            peer.watch_ids.add(wid)
            with self._peers_lock:
                self._by_watch[wid] = peer
        return protocol.reply(True, "accepted", wid or None)

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
        with self._peers_lock:
            peers = [peer for peer in self._peers if peer.live]
        for peer in peers:
            ids = list(peer.watch_ids)
            for wid in ids:
                self._enqueue(peer, protocol.stop_frame(wid, "sit-end"))
            if not ids:
                cancel = getattr(peer.conn, "cancel", None)
                if cancel is not None:
                    try:
                        cancel()
                    except OSError:
                        pass
        self._wake()
        if self._thread is not None:
            self._thread.join(2.0)
        for peer in peers:
            peer.done.wait(0.5)
        try:
            pointer_path(self.desk).unlink()
        except OSError:
            pass
        self._transport.cleanup()


def serve(desk: str) -> Link:
    link = Link(desk)
    link.start()
    return link
