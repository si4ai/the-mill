# -*- coding: utf-8 -*-
"""Card 1223 part A: a tw run forwards allowlisted mill calls from its descendants."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from agent_coord.client.tw import run_ipc
from agent_coord.client.tw.run_ipc import (
    ALLOW,
    ERR_CAP,
    ERR_ENDED,
    ERR_LONG,
    ERR_PEER,
    ERR_REFUSED,
    INFLIGHT,
    LINE_MAX,
    RunGate,
    call_parent,
    is_descendant,
    lookup_parent,
    report_status,
)
from agent_coord.client.tw.unix_sock import bind_private
from agent_coord.client.tw.win_pipe import Pipe, pipe_name
from agent_coord.helpers.errors import CoordError

ROOT = 10
CHILD = 11
GRAND = 12
OTHER = 40
TABLE = {
    ROOT: (1, "python.exe"),
    CHILD: (ROOT, "tool.exe"),
    GRAND: (CHILD, "mill.exe"),
    OTHER: (2, "other.exe"),
    1: (0, "shell"),
    2: (0, "shell"),
}
STARTS = {ROOT: 1000, CHILD: 1100, GRAND: 1200, OTHER: 1300, 1: 500, 2: 500}


def _gate(call=None, events=None):
    seen = events if events is not None else []

    def event_fn(body):
        seen.append(dict(body))
        return True

    def call_fn(verb, args, watch_id):
        return {"ok": True, "verb": verb, "watch_id": watch_id, "args": dict(args)}

    gate = RunGate("desk-a", "tw-parent", call or call_fn, event_fn)
    gate.pid = ROOT
    gate.start = 1000
    return gate, seen


def _frame(gate, frame, *, peer=CHILD, peer_start=1100, starts=None):
    return gate.handle_frame(
        frame,
        peer_pid=peer,
        peer_start=peer_start,
        table=TABLE,
        starts=dict(STARTS if starts is None else starts),
        fetch=None,
    )


def test_descendant_walk_rejects_reuse_and_outsiders() -> None:
    assert is_descendant(GRAND, ROOT, table=TABLE, starts=dict(STARTS), root_start=1000)
    assert is_descendant(ROOT, ROOT, table=TABLE, starts=dict(STARTS), root_start=1000)
    assert not is_descendant(OTHER, ROOT, table=TABLE, starts=dict(STARTS), root_start=1000)
    older = dict(STARTS)
    older[CHILD] = 50
    assert not is_descendant(CHILD, ROOT, table=TABLE, starts=older, root_start=1000)
    reused = dict(STARTS)
    reused[ROOT] = 2000
    assert not is_descendant(CHILD, ROOT, table=TABLE, starts=reused, root_start=1000)
    assert not is_descendant(CHILD, ROOT, table=TABLE, starts={}, root_start=1000, fetch=None)


def test_allowlist_strips_desk_and_stamps_the_run() -> None:
    seen: dict = {}

    def call_fn(verb, args, watch_id):
        seen["verb"] = verb
        seen["args"] = dict(args)
        seen["watch_id"] = watch_id
        return {"ok": True}

    gate, _events = _gate(call_fn)
    reply = _frame(
        gate,
        {
            "type": "call",
            "verb": "todo",
            "args": {"desk": "other", "watch_id": "tw-fake", "owner": "nope", "need": "n"},
        },
    )
    assert reply["ok"] is True
    assert seen == {"verb": "todo", "args": {"need": "n"}, "watch_id": "tw-parent"}
    for verb in ("reset", "delete", "purge", "reclaim", "rename", "join", "connect", "session"):
        refused = _frame(gate, {"type": "call", "verb": verb, "args": {}})
        assert refused == {"ok": False, "error": ERR_REFUSED}
    assert seen["verb"] == "todo"
    for verb in sorted(ALLOW):
        allowed = _frame(gate, {"type": "call", "verb": verb, "args": {}})
        assert allowed["ok"] is True
        assert seen["verb"] == verb
        assert seen["watch_id"] == "tw-parent"


def test_over_cap_and_exit_are_loud_and_do_not_forward() -> None:
    calls = []

    def call_fn(verb, args, watch_id):
        calls.append(verb)
        return {"ok": True}

    gate, events = _gate(call_fn)
    gate.inflight = INFLIGHT
    assert _frame(gate, {"type": "call", "verb": "todo", "args": {}})["error"] == ERR_CAP
    assert calls == []
    gate.inflight = 0
    gate.exiting = True
    assert _frame(gate, {"type": "call", "verb": "mail-thread", "args": {}})["error"] == ERR_ENDED
    assert _frame(gate, {"type": "child", "argv": ["tool"]})["error"] == ERR_ENDED
    assert _frame(gate, {"type": "status"})["error"] == ERR_ENDED
    assert events == []
    assert calls == []


def test_outsider_is_refused_and_a_child_run_is_linked() -> None:
    gate, events = _gate()
    assert _frame(gate, {"type": "status"}, peer=OTHER, peer_start=1300)["error"] == ERR_PEER
    opened = _frame(gate, {"type": "child", "argv": ["tool"]})
    assert opened["ok"] is True
    assert opened["parent"] == "tw-parent"
    assert opened["desk"] == "desk-a"
    assert events[0]["kind"] == "start"
    assert events[0]["watch_id"] == opened["watch_id"]
    assert events[0]["parent_watch_id"] == "tw-parent"
    assert "argv" not in events[0]
    relayed = _frame(
        gate,
        {
            "type": "relay",
            "watch_id": opened["watch_id"],
            "frame": {"type": "call", "verb": "score", "args": {"desk": "other", "kpi": "k"}},
        },
    )
    assert relayed["ok"] is True
    assert relayed["result"]["watch_id"] == opened["watch_id"]
    assert "desk" not in relayed["result"]["args"]
    gate.children["tw-grand"] = {"pid": GRAND, "start": 1200}
    stolen = _frame(
        gate,
        {
            "type": "relay",
            "watch_id": "tw-grand",
            "frame": {"type": "call", "verb": "hold", "args": {}},
        },
        peer=CHILD,
        peer_start=1100,
    )
    assert stolen["error"] == ERR_PEER


def test_line_over_cap_is_refused_whole() -> None:
    gate, _events = _gate()

    class Mem:
        def __init__(self, data: bytes) -> None:
            self.data = data
            self.out = bytearray()

        def read(self, n: int) -> bytes:
            take = self.data[:n]
            self.data = self.data[n:]
            return take

        def write(self, blob: bytes) -> int:
            self.out += blob
            return len(blob)

        def flush(self) -> None:
            return None

    mem = Mem(b"{" + b"a" * (LINE_MAX + 1) + b"\n")
    gate._speak(mem, CHILD)
    assert ERR_LONG.encode("utf-8") in mem.out
    assert b"todo" not in mem.out


def test_watch_env_grants_nothing(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("MILL_TW_WATCH", "tw-spoof")
    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))
    assert lookup_parent() is None
    assert "MILL_TW_WATCH" not in Path(run_ipc.__file__).read_text(encoding="utf-8")


def test_desk_pipe_defaults_stay() -> None:
    pipe = Pipe("desk-a")
    assert pipe.address == pipe_name("desk-a")
    assert pipe.owner_only is False
    assert pipe.first_instance is False
    assert pipe.buffer_size == 8192
    text = Path(run_ipc.__file__).resolve().parents[0].joinpath("unix_sock.py").read_text(encoding="utf-8")
    assert "srv.listen(16)" in text


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="unix socket")
def test_private_bind_refuses_an_existing_path(tmp_path) -> None:
    target = tmp_path / "taken.sock"
    target.write_text("x", encoding="utf-8")
    with pytest.raises(OSError):
        bind_private(target, 64)


@pytest.mark.skipif(os.name != "nt", reason="named pipe")
def test_windows_pipe_checks_the_peer_and_a_child(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))
    calls = []

    def call_fn(verb, args, watch_id):
        calls.append((verb, dict(args), watch_id))
        return {"ok": True, "verb": verb, "watch_id": watch_id}

    gate = RunGate("desk-a", "tw-pipe", call_fn, lambda body: True)
    gate.open()
    try:
        found = lookup_parent()
        assert found is not None
        assert found["watch_id"] == "tw-pipe"
        assert int(found["pid"]) == os.getpid()
        status = call_parent(found, {"type": "status"})
        assert status == {"ok": True, "desk": "desk-a", "watch_id": "tw-pipe"}
        forwarded = call_parent(
            found,
            {
                "type": "call",
                "verb": "todo",
                "args": {"desk": "other", "need": "n", "watch_id": "tw-nope"},
            },
        )
        assert forwarded["ok"] is True
        assert calls == [("todo", {"need": "n"}, "tw-pipe")]
        gate.pid = 2**31 - 1
        refused = call_parent(found, {"type": "status"})
        assert refused["error"] == ERR_PEER
        root = Path(__file__).resolve().parents[2]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")
        env["AGENT_COORD_MILL_HOME"] = str(tmp_path)
        env["MILL_TW_WATCH"] = "tw-spoof"
        # The gate's recorded root is this process. Put it back for the child.
        gate.pid = os.getpid()
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                "from agent_coord.client.tw.run_ipc import report_status; raise SystemExit(report_status())",
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert proc.returncode == 0, proc.stderr
        assert json.loads(proc.stdout) == {"desk": "desk-a", "watch_id": "tw-pipe"}
        assert "tw-spoof" not in proc.stdout
    finally:
        gate.close()
    assert lookup_parent() is None
    assert report_status() == 1
    err = capsys.readouterr().err
    assert "mill connect" in err


def test_server_mismatch_raises(monkeypatch) -> None:
    monkeypatch.setattr(run_ipc, "process_start", lambda pid: 5 if int(pid) == 7 else None)
    monkeypatch.setattr(run_ipc, "_open_pipe", lambda address: (MemConn(), 7))
    pointer = {
        "kind": "pipe",
        "address": "pipe",
        "pid": 7,
        "start": 9,
        "watch_id": "tw-x",
        "desk": "desk-a",
    }
    with pytest.raises(CoordError, match=run_ipc.ERR_SERVER):
        call_parent(pointer, {"type": "status"})


class MemConn:
    def write(self, blob: bytes) -> int:
        raise AssertionError("refused before send")

    def close(self) -> None:
        return None
