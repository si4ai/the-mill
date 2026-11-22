"""Card 1223 hotfix 0.8.16.1: what a tw run's descendants forward arrives whole.

F1: the CLI hands try_forward a flat body; the forwarded args must carry its
fields, not {}. F2: a write two tw levels down reaches the root run's handler.
F3: a nested run's events name the run above it, never itself.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from agent_coord.client.tw import run_ipc
from agent_coord.client.tw.run_ipc import ERR_REFUSED, RunGate

ROOT = 10
CHILD = 11
GRAND = 12
TABLE = {ROOT: (1, "tw"), CHILD: (ROOT, "tw"), GRAND: (CHILD, "mill"), 1: (0, "shell")}
STARTS = {ROOT: 1000, CHILD: 1100, GRAND: 1200, 1: 500}
UNIX = pytest.mark.skipif(
    os.name == "nt" or not hasattr(socket, "AF_UNIX"), reason="unix socket"
)


def test_try_forward_sends_the_flat_body_fields_as_args(monkeypatch) -> None:
    sent: list[dict] = []
    monkeypatch.setattr(run_ipc, "lookup_parent", lambda: {"kind": "unix"})

    def call_parent(_pointer, frame):
        sent.append(frame)
        return {"ok": True, "result": {"ok": True}}

    monkeypatch.setattr(run_ipc, "call_parent", call_parent)
    body = {
        "verb": "todo",
        "project": "the-mill",
        "owner": "",
        "need": "some-need",
        "progress": "1/2",
        "token": "t",
        "desk": "other",
        "watch_id": "tw-fake",
        "sender_desk": "other",
    }
    run_ipc.try_forward(body)
    assert sent == [
        {
            "type": "call",
            "verb": "todo",
            "args": {"project": "the-mill", "need": "some-need", "progress": "1/2"},
        }
    ]


def _gate(watch_id: str, calls: list, events: list) -> RunGate:
    def call_fn(verb, args, wid):
        calls.append({"verb": verb, "args": dict(args), "watch_id": wid})
        return {"ok": True, "result": {"verb": verb}, "sync": []}

    def event_fn(body):
        events.append(dict(body))
        return True

    return RunGate("desk-a", watch_id, call_fn, event_fn)


def test_relayed_events_name_the_run_above_and_unknown_runs_are_refused() -> None:
    calls: list = []
    events: list = []
    gate = _gate("tw-root", calls, events)
    gate.pid = ROOT
    gate.start = 1000

    def frame(body, peer=CHILD, start=1100):
        return gate.handle_frame(
            body, peer_pid=peer, peer_start=start, table=TABLE, starts=dict(STARTS), fetch=None
        )

    child = frame({"type": "child", "argv": ["tool"]})["watch_id"]
    own = {"type": "event", "watch_id": child, "kind": "start", "pid": GRAND}
    assert frame({"type": "relay", "watch_id": child, "frame": own})["ok"] is True
    spoof = dict(own, parent_watch_id=child)
    assert frame({"type": "relay", "watch_id": child, "frame": spoof})["ok"] is True
    deeper = {"type": "event", "watch_id": "tw-grand", "kind": "start", "pid": GRAND,
              "parent_watch_id": child}
    assert frame({"type": "relay", "watch_id": child, "frame": deeper})["ok"] is True
    for event in events:
        assert event["parent_watch_id"] != event["watch_id"]
    assert [e["parent_watch_id"] for e in events] == ["tw-root", "tw-root", "tw-root", child]
    write = {"type": "call", "verb": "todo", "args": {"need": "n"}, "watch_id": "tw-grand"}
    assert frame({"type": "relay", "watch_id": child, "frame": write})["ok"] is True
    assert calls[-1] == {"verb": "todo", "args": {"need": "n"}, "watch_id": "tw-grand"}
    stranger = dict(write, watch_id="tw-not-under-child")
    assert frame({"type": "relay", "watch_id": child, "frame": stranger}) == {
        "ok": False,
        "error": ERR_REFUSED,
    }
    assert len(calls) == 1
    sibling = frame({"type": "child", "argv": ["tool"]})["watch_id"]
    events.pop()
    for taken in ("tw-root", sibling):
        claim = dict(deeper, watch_id=taken, parent_watch_id="tw-x")
        refused = frame({"type": "relay", "watch_id": child, "frame": claim})
        assert refused == {"ok": False, "error": ERR_REFUSED}
    assert len(events) == 4


def _env(home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["AGENT_COORD_MILL_HOME"] = str(home)
    src = str(Path(run_ipc.__file__).resolve().parents[3])
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    for name in list(env):
        if name.startswith("MILL_") and name != "MILL_HOME":
            env.pop(name, None)
    return env


def _serve(gate: RunGate, cmd: list[str], env: dict[str, str]) -> subprocess.CompletedProcess:
    gate.open()
    try:
        return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=120)
    finally:
        gate.close()


@UNIX
def test_cli_call_under_a_run_arrives_with_its_args(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))
    calls: list = []
    events: list = []
    gate = _gate("tw-root", calls, events)
    cmd = [sys.executable, "-m", "agent_coord", "todo", "the-mill", "some-need", "--progress", "1/2"]
    done = _serve(gate, cmd, _env(tmp_path))
    assert done.returncode == 0, done.stderr
    assert len(calls) == 1
    assert calls[0]["verb"] == "todo"
    assert calls[0]["watch_id"] == "tw-root"
    assert calls[0]["args"]["need"] == "some-need"
    assert calls[0]["args"]["progress"] == "1/2"
    assert calls[0]["args"]["project"] == "the-mill"


@UNIX
def test_write_two_tw_levels_down_reaches_the_root_handler(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))
    calls: list = []
    events: list = []
    gate = _gate("tw-root", calls, events)
    tw = [sys.executable, "-m", "agent_coord.client.tw.cli"]
    leaf = [sys.executable, "-m", "agent_coord", "todo", "the-mill", "nested", "--progress", "1/1"]
    done = _serve(gate, tw + tw + leaf, _env(tmp_path))
    assert done.returncode == 0, done.stdout + done.stderr
    assert len(calls) == 1, done.stdout + done.stderr
    assert calls[0]["args"]["need"] == "nested"
    assert calls[0]["args"]["progress"] == "1/1"
    starts = [e for e in events if e.get("kind") == "start"]
    middle = starts[0]["watch_id"]
    assert starts[0]["parent_watch_id"] == "tw-root"
    deepest = [e for e in starts if e.get("parent_watch_id") == middle]
    assert deepest, json.dumps(events)
    assert calls[0]["watch_id"] == deepest[0]["watch_id"]
    for event in events:
        assert event["parent_watch_id"] != event["watch_id"], json.dumps(event)
    exits = {e["watch_id"]: e["parent_watch_id"] for e in events if e.get("kind") == "exit"}
    assert exits == {middle: "tw-root", deepest[0]["watch_id"]: middle}


def test_gate_threads_are_not_left_running() -> None:
    assert not [t for t in threading.enumerate() if t.name == "mill-tw-run"]


def test_desk_link_keeps_a_nested_start_parent(tmp_path, monkeypatch) -> None:
    from agent_coord.client.tw.link import Session, serve

    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)
    monkeypatch.setattr("agent_coord.client.offices.desk_local_file", lambda *a, **k: None)
    hops: list = []
    monkeypatch.setattr(
        "agent_coord.client.http.mill_http_call",
        lambda body: hops.append(dict(body)) or {"ok": True, "result": {"ok": True}},
    )
    link = serve("tw-parent-link")
    session = Session(link)
    try:
        session.request({"type": "register", "key": "tw:p", "argv": ["tw", "run"]})
        got = session.request(
            {"type": "event", "watch_id": "tw-child", "kind": "start", "parent_watch_id": "tw-root"}
        )
        assert got["ok"] is True
        assert link.drain() == "empty"
        events = [hop for hop in hops if hop.get("verb") == "tw.event"]
        assert [e.get("parent_watch_id") for e in events] == ["tw-root"]
    finally:
        session.close()
        link.close()


def test_hop_file_from_0816_gains_the_parent_column(tmp_path) -> None:
    import sqlite3

    from agent_coord.client.tw.outbox import Outbox, _post_body

    path = tmp_path / "old.hops.sqlite"
    db = sqlite3.connect(str(path))
    db.execute(
        "CREATE TABLE hop (id INTEGER PRIMARY KEY, watch_id TEXT NOT NULL, kind TEXT NOT NULL,"
        " cause TEXT, exit_code INTEGER, wake INTEGER, counts TEXT, desk TEXT, card INTEGER,"
        " ts_ms INTEGER)"
    )
    db.execute("INSERT INTO hop (watch_id, kind) VALUES ('tw-old', 'exit')")
    db.commit()
    db.close()
    box = Outbox(path)
    try:
        box.add({"watch_id": "tw-child", "kind": "start", "parent_watch_id": "tw-root"})
        old = box.next_row(set())
        assert _post_body(old) == {"verb": "tw.event", "watch_id": "tw-old", "kind": "exit"}
        box.drop(int(old["id"]))
        assert _post_body(box.next_row(set()))["parent_watch_id"] == "tw-root"
    finally:
        box.close()
