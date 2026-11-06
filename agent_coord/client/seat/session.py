# -*- coding: utf-8 -*-
"""Hold a seat for mill connect, or borrow one for a single command."""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Callable

from agent_coord.helpers.errors import CoordError
from agent_coord.helpers.ident import desk as slug_desk

from agent_coord.client.seat.status import held_message, look, other_holder

_READY_WAIT_S = 20.0
_POLL_S = 0.02


class Running:
    """A socket thread this process opened."""

    def __init__(
        self,
        desk: str,
        stop: threading.Event,
        outcome: dict[str, Any],
        thread: threading.Thread,
    ) -> None:
        self.desk = desk
        self.stop = stop
        self.outcome = outcome
        self.thread = thread


def open_session(desk: str, token: str, *, refuse: bool, parent: int) -> Running:
    """Start the socket thread. The bridge appears when the seat is ours."""
    from agent_coord.client.ws import hold_sync_lines, start_ws_thread, write_connect_starting

    stop = threading.Event()
    outcome: dict[str, Any] = {}
    write_connect_starting(desk, pid=os.getpid(), parent_pid=parent)
    hold_sync_lines()
    thread = start_ws_thread(desk, token, stop, outcome, refuse=refuse)
    return Running(desk, stop, outcome, thread)


def release(running: Running) -> None:
    """Stop the socket thread and drop the local bridge."""
    from agent_coord.client.ws import clear_connect_starting

    running.stop.set()
    thread = running.thread
    if thread is not None:
        thread.join(timeout=5.0)
    clear_connect_starting(running.desk, pid=os.getpid())
    from agent_coord.client.ws import drop_sync_lines

    drop_sync_lines()


def wait_ready(running: Running, timeout_s: float = _READY_WAIT_S) -> None:
    """Block until this process can see its own bridge, or the open failed."""
    from agent_coord.client.ws import bridge_for_parent, busy_for_parent

    who = slug_desk(running.desk)
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if _closed(running):
            raise CoordError(busy_for_parent() or held_message())
        ep = bridge_for_parent()
        if ep and slug_desk(str(ep.get("desk") or "")) == who:
            return
        if running.thread is None or not running.thread.is_alive():
            break
        running.stop.wait(_POLL_S)
    if _closed(running):
        from agent_coord.client.ws import busy_for_parent

        raise CoordError(busy_for_parent() or held_message())
    raise CoordError("socket did not come up")


def hold(
    desk: str,
    token: str,
    *,
    parent: int,
    refuse: bool,
    parent_gone: Callable[[int], bool],
    project: str = "",
) -> int:
    """mill connect: open the socket and block until the sit ends."""
    running = open_session(desk, token, refuse=refuse, parent=parent)
    threading.Thread(
        target=_focus,
        args=(desk, project, running.stop, running.outcome),
        name="mill-connect-project-%s" % slug_desk(desk),
        daemon=True,
    ).start()
    try:
        try:
            while not running.stop.is_set():
                if parent_gone(parent):
                    running.stop.set()
                    from agent_coord.client.session_errors import parent_exited_notice

                    print(
                        json.dumps(parent_exited_notice(desk), default=str),
                        flush=True,
                    )
                    return 0
                running.stop.wait(1.0)
        except KeyboardInterrupt:
            running.stop.set()
            return 0
        return int(running.outcome.get("exit") or 0)
    finally:
        release(running)


def command(body: dict[str, Any]) -> Any:
    """One desk command.

    A sit this process can see carries the call. Otherwise open a socket,
    send this command, and release the bearer.
    """
    from agent_coord.client.session_errors import SESSION_WS_BRIDGE_REQUIRED
    from agent_coord.client.ws import mill_ws_call, wait_for_sitting_desk

    state = look()
    if state.kind == "sitting":
        return mill_ws_call(body)
    if state.kind == "starting":
        if wait_for_sitting_desk():
            return mill_ws_call(body)
        state = look()
    if state.kind == "busy":
        raise CoordError(state.detail or held_message())
    if state.kind == "fail":
        raise CoordError(state.detail or "connect failed")
    desk, token = _joined_bearer()
    if not desk or not token:
        if state.kind == "dead":
            raise CoordError(state.detail)
        raise CoordError(SESSION_WS_BRIDGE_REQUIRED)
    holder = other_holder(desk)
    if holder:
        raise CoordError(held_message(holder))
    return borrow(desk, token, body)


def borrow(desk: str, token: str, body: dict[str, Any]) -> Any:
    """Open, one RPC, release. The office sees the same verb and args."""
    from agent_coord.client.ws import _shell_ppid, mill_ws_call

    running = open_session(desk, token, refuse=True, parent=_shell_ppid())
    try:
        wait_ready(running)
        return mill_ws_call(body)
    finally:
        release(running)


def _focus(desk: str, project: str, stop: threading.Event, outcome: dict[str, Any]) -> None:
    from agent_coord.client.http import seat_then_focus

    seat_then_focus(desk, project, stop, outcome)


def _joined_bearer() -> tuple[str, str]:
    """The desk this process joined, when that seat has a stored bearer."""
    from agent_coord.client.tokens import read_active_desk, read_session_token

    who = (read_active_desk() or "").strip()
    if not who:
        return "", ""
    try:
        token = (read_session_token(who) or "").strip()
    except ValueError:
        return "", ""
    if not token:
        return "", ""
    return who, token


def _closed(running: Running) -> bool:
    thread = running.thread
    dead = thread is None or not thread.is_alive()
    return "exit" in running.outcome and dead
