# -*- coding: utf-8 -*-
"""Seat status for this process: sitting, starting, busy, failed, dead, or none."""
from __future__ import annotations

import os
from dataclasses import dataclass

from agent_coord.helpers.ident import desk as slug_desk


@dataclass(frozen=True)
class Status:
    kind: str
    desk: str = ""
    detail: str = ""


def look(parent_pid: int | None = None) -> Status:
    """Status of the sit this process can see. Does not open a socket."""
    from agent_coord.client import ws

    ep = ws.bridge_for_parent(parent_pid)
    if ep:
        return Status("sitting", str(ep.get("desk") or "").strip())
    if ws.dead_connect_for_parent(parent_pid):
        from agent_coord.client.session_errors import SESSION_CONNECT_DIED

        return Status("dead", "", SESSION_CONNECT_DIED)
    start = ws.starting_for_parent(parent_pid)
    if start and ws._pid_alive(int(start.get("pid") or 0)):
        return Status("starting", str(start.get("desk") or "").strip())
    busy = ws.busy_for_parent(parent_pid)
    if busy:
        return Status("busy", "", busy)
    fail = ws.fail_for_parent(parent_pid)
    if fail:
        return Status("fail", "", fail)
    return Status("none")


def other_holder(desk: str) -> int:
    """Pid of a live connect that already holds this desk, or 0."""
    from agent_coord.client import ws

    who = slug_desk(desk)
    me = os.getpid()
    if not who:
        return 0
    for path in ws._rpc_bridge_files():
        row = ws._load_rpc_bridge(path)
        if not row:
            continue
        if slug_desk(str(row.get("desk") or "")) != who:
            continue
        pid = int(row.get("pid") or 0)
        if pid and pid != me and ws._pid_alive(pid):
            return pid
    return 0


def held_message(pid: int = 0) -> str:
    if pid:
        return (
            "this desk's seat is held by another connect (pid %s); "
            "retry when it exits" % pid
        )
    return "this desk's seat is held by another connect; retry when it exits"
