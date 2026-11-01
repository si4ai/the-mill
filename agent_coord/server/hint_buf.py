"""Sit-side HINT buffer. Recv thread only enqueues; a drain thread does work.

Hub push is fire-and-forget. If mill-ws does poke/print on the recv loop, a busy
desk drops frames (keyboard serial: interrupt handler must not be the CPU).
PING is keep-alive: read it off the socket, do not queue it as work.
"""
from __future__ import annotations

import json
import queue
import threading
from pathlib import Path
from typing import Any

from agent_coord.helpers.ident import desk as slug_desk
from agent_coord.helpers.ident import desk_name
from agent_coord.server.push import dest_log, perf_log
from agent_coord.server.redact import redact_obj


def _bc_log(msg: str) -> None:
    dest_log("mill-backchannel.log", msg)

MAX_WORK = 256
_DROP_KEEP = ("type", "id", "hint", "route", "idem", "kind")


def drop_notice(frame: dict[str, Any]) -> dict[str, Any]:
    """Client text for a dropped frame. Not an RPC. The office does not take sync for it.

    A sent queue row is put back as missed. A missing row becomes one drop line.
    """
    src = frame or {}
    keep: dict[str, Any] = {}
    for key in _DROP_KEEP:
        if src.get(key) in (None, ""):
            continue
        keep[key] = src.get(key)
    return {"drop": 1, "frame": keep}


def hint_path(desk: str) -> Path:
    from agent_coord.client.offices import desk_local_file
    from agent_coord.config import mill_home

    hosted = desk_local_file(desk, "hints.jsonl")
    if hosted is not None:
        return hosted
    who = slug_desk(desk)
    dest = mill_home() / "session"
    dest.mkdir(parents=True, exist_ok=True)
    return dest / f"{who}.hints.jsonl"


class HintBuf:
    def __init__(self, desk: str, *, maxsize: int = MAX_WORK) -> None:
        self.desk = desk_name(desk)
        self.q: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=max(1, int(maxsize)))
        self.path = hint_path(desk)
        self._drops: list[dict[str, Any]] = []
        self._drop_lock = threading.Lock()
        self._exit_lock = threading.Lock()
        self._exit_sender: Any = None
        self._exit_wait: list[dict[str, Any]] = []

    def put_recv(self, msg: dict[str, Any]) -> None:
        """Recv thread only. Never poke, never print, never mill leftover.

        One HintBuf per mill connect / desk. N desks on one PC = N processes,
        N queues, N jsonl files. Stamp desk so a file cannot be misread as another sit.
        """
        from agent_coord.client.inbound import classify, ignore

        if ignore(msg):
            return
        item = dict(msg or {})
        item["desk"] = self.desk
        got = classify(msg)
        item["route"] = got.get("key") or ""
        if got.get("verb"):
            item["verb"] = got["verb"]
        hint = str(item.get("hint") or "")
        dropped = 0
        try:
            self.q.put_nowait(item)
        except queue.Full:
            dropped = 1
            try:
                old = self.q.get_nowait()
                _bc_log(
                    f"hint drop desk={self.desk} hint={old.get('hint')} id={old.get('id')} q={self.q.qsize()}"
                )
                with self._drop_lock:
                    self._drops.append(old)
            except queue.Empty:
                pass
            try:
                self.q.put_nowait(item)
            except queue.Full:
                pass
        frame_b = len(json.dumps(item, default=str, separators=(",", ":")).encode("utf-8"))
        _bc_log(
            f"ws recv desk={self.desk} hint={hint} id={item.get('id')} q={self.q.qsize()} drop={dropped} frame_b={frame_b}"
        )
        perf_log(
            "ws.recv",
            0.0,
            desk=self.desk,
            hint=hint,
            id=item.get("id"),
            q=self.q.qsize(),
            drop=dropped,
            frame_b=frame_b,
        )

    def pop_drops(self) -> list[dict[str, Any]]:
        """Frames removed to make room. The caller tells the office. Recv does not wait."""
        with self._drop_lock:
            out = self._drops
            self._drops = []
        return out

    def set_sender(self, sender: Any) -> None:
        """Sitting socket send. A route exit queued before the socket sits goes out now."""
        with self._exit_lock:
            self._exit_sender = sender
            pending = self._exit_wait
            self._exit_wait = []
        for notice in pending:
            try:
                sender(notice)
            except Exception:
                pass

    def push_exit(self, notice: dict[str, Any]) -> None:
        """A redirector exited non-zero. Tell the office. Do not wait for sync."""
        with self._exit_lock:
            sender = self._exit_sender
            if sender is None:
                self._exit_wait.append(dict(notice))
                return
        try:
            sender(notice)
        except Exception:
            pass

    def get_work(self, timeout: float = 1.0) -> dict[str, Any] | None:
        try:
            return self.q.get(timeout=timeout)
        except queue.Empty:
            return None

    def append_file(self, msg: dict[str, Any]) -> None:
        """Drain thread. Durable for this sit; not the book (activity/watchers)."""
        try:
            line = json.dumps(redact_obj(msg), default=str, separators=(",", ":"))
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception:
            pass


def _drain_one(
    buf: HintBuf,
    frame: dict[str, Any],
    hint: str,
    t0: float,
    replay: bool = False,
    stop: threading.Event | None = None,
    outcome: dict[str, Any] | None = None,
) -> None:
    """One frame's chain. Waiting for a program must not hold the next frame."""
    import time

    from agent_coord.client.dispatch import dispatch_hint
    from agent_coord.client.route_chain import bind_exit

    ok = 1
    err = ""
    try:
        with bind_exit(buf.push_exit):
            kind = dispatch_hint(buf.desk, frame, replay=replay)
        if kind == "skip":
            if not replay:
                # #670: a live skip answers the HINT line just printed. A replay is
                # not reprinted (#618), so its skip has nothing to answer; the log keeps it.
                print({"watch": "skip", "desk": buf.desk, "route": frame.get("route")}, flush=True)
            ms = (time.perf_counter() - t0) * 1000.0
            _bc_log(
                f"hint drain desk={buf.desk} hint={hint} id={frame.get('id')} ok={ok} watch=skip q={buf.q.qsize()}"
            )
            perf_log(
                "hint.drain",
                ms,
                desk=buf.desk,
                hint=hint,
                id=frame.get("id"),
                ok=ok,
                watch="skip",
                q=buf.q.qsize(),
            )
            return
        if kind == "sit-exit":
            # Card 985: plain connect with no chat-wake path exits like connect-wait.
            line = {
                "ok": True,
                "mode": "sit-exit",
                "desk": buf.desk,
                "hint": frame,
                "next": (
                    "plain mill connect cannot wake a chat for this HINT; "
                    "use mill connect-wait DESK, or mill connect DESK "
                    "--vendor grok-build --session UUID"
                ),
            }
            print(json.dumps(line, default=str), flush=True)
            if outcome is not None:
                outcome["exit"] = 0
                outcome["sit_exit"] = frame
            if stop is not None:
                stop.set()
            ms = (time.perf_counter() - t0) * 1000.0
            _bc_log(
                f"hint drain desk={buf.desk} hint={hint} id={frame.get('id')} ok={ok} sit-exit=1 q={buf.q.qsize()}"
            )
            perf_log(
                "hint.drain",
                ms,
                desk=buf.desk,
                hint=hint,
                id=frame.get("id"),
                ok=ok,
                sit_exit=1,
                q=buf.q.qsize(),
            )
            return
        if kind == "work":
            print({"route": "hit", "desk": buf.desk}, flush=True)
        elif kind == "suppress":
            print({"route": "suppress", "desk": buf.desk}, flush=True)
    except NotImplementedError as e:
        ok = 0
        err = str(e)[:160]
        print({"connector": "stub", "detail": err}, flush=True)
    except Exception as e:
        ok = 0
        err = str(e)[:160]
        print({"connector": "error", "detail": err}, flush=True)
    ms = (time.perf_counter() - t0) * 1000.0
    _bc_log(
        f"hint drain desk={buf.desk} hint={hint} id={frame.get('id')} ok={ok} q={buf.q.qsize()}"
    )
    kv = dict(desk=buf.desk, hint=hint, id=frame.get("id"), ok=ok, q=buf.q.qsize())
    if err:
        kv["err"] = err
    perf_log("hint.drain", ms, **kv)


def drain_loop(
    buf: HintBuf,
    stop: threading.Event,
    outcome: dict[str, Any] | None = None,
) -> None:
    """Work thread. Each frame walks its own chain. Recv does not wait. The hub does not wait."""
    import time

    from agent_coord.client.dispatch import public_frame

    while not stop.is_set():
        msg = buf.get_work(timeout=0.5)
        if msg is None:
            continue
        t0 = time.perf_counter()
        frame = public_frame(msg, buf.desk)
        hint = str(frame.get("hint") or "")
        # #618: a connect-sync replay is already on the sync line; walk it, do not reprint it.
        replay = bool(msg.get("replay"))
        buf.append_file(frame)
        if not replay:
            print({"HINT": frame}, flush=True)
        if hint == "PING":
            ms = (time.perf_counter() - t0) * 1000.0
            _bc_log(
                f"hint drain desk={buf.desk} hint={hint} id={frame.get('id')} ok=1 q={buf.q.qsize()}"
            )
            perf_log("hint.drain", ms, desk=buf.desk, hint=hint, id=frame.get("id"), ok=1, q=buf.q.qsize())
            continue
        threading.Thread(
            target=_drain_one,
            args=(buf, frame, hint, t0, replay, stop, outcome),
            name=f"mill-hint-{buf.desk}-{frame.get('id')}",
            daemon=True,
        ).start()
