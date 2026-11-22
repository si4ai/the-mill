"""Card 1281: a tw run's descendant cannot forge a start to take a run's credit.

At 0.8.16.1 the gate accepted an origin below a child once it saw any event
for it inside a relay frame from that child's tree. A direct child, or a
grandchild talking to the root gate itself, could send its own start for a
made-up watch id and then have calls recorded under it. The gate now accepts
an origin below a child only from a start the child's own gate relayed (the
process the watch id was issued to) for a live process below that gate.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from agent_coord.client.tw import run_ipc
from agent_coord.client.tw.run_ipc import ERR_PEER, ERR_REFUSED, RunGate

ROOT = 10
CHILD = 11
GRAND = 12
OUTSIDER = 99
TABLE = {
    ROOT: (1, "tw"),
    CHILD: (ROOT, "tw"),
    GRAND: (CHILD, "python"),
    OUTSIDER: (1, "python"),
    1: (0, "shell"),
}
STARTS = {ROOT: 1000, CHILD: 1100, GRAND: 1200, OUTSIDER: 1300, 1: 500}
FORGED = "tw-forged-origin"
UNIX = pytest.mark.skipif(
    os.name == "nt" or not hasattr(socket, "AF_UNIX"), reason="unix socket"
)


def _gate(calls: list, events: list) -> RunGate:
    def call_fn(verb, args, wid):
        calls.append({"verb": verb, "args": dict(args), "watch_id": wid})
        return {"ok": True, "result": {"verb": verb}, "sync": []}

    def event_fn(body):
        events.append(dict(body))
        return True

    gate = RunGate("desk-a", "tw-root", call_fn, event_fn)
    gate.pid = ROOT
    gate.start = 1000
    return gate


def _frame(gate: RunGate, body: dict, peer: int = CHILD) -> dict:
    return gate.handle_frame(
        body,
        peer_pid=peer,
        peer_start=STARTS[peer],
        table=TABLE,
        starts=dict(STARTS),
        fetch=None,
    )


def _relay(child: str, inner: dict) -> dict:
    return {"type": "relay", "watch_id": child, "frame": inner}


def _call(origin: str) -> dict:
    return {"type": "call", "verb": "todo", "args": {"need": "spoofed"}, "watch_id": origin}


def _nothing_under(origin: str, calls: list, events: list) -> None:
    assert [c for c in calls if c["watch_id"] == origin] == []
    assert [e for e in events if e.get("watch_id") == origin] == []


@pytest.mark.parametrize(
    "stamp",
    [{}, {"pid": CHILD}, {"pid": OUTSIDER}, {"pid": ROOT}],
    ids=["no-pid", "own-pid", "outsider-pid", "root-pid"],
)
def test_direct_child_start_by_hand_does_not_open_an_origin(stamp) -> None:
    calls: list = []
    events: list = []
    gate = _gate(calls, events)
    child = _frame(gate, {"type": "child", "argv": ["tool"]})["watch_id"]
    events.clear()
    start = dict(
        {"type": "event", "kind": "start", "watch_id": FORGED, "parent_watch_id": child},
        **stamp,
    )
    assert _frame(gate, _relay(child, start)) == {"ok": False, "error": ERR_REFUSED}
    assert _frame(gate, _relay(child, _call(FORGED))) == {"ok": False, "error": ERR_REFUSED}
    _nothing_under(FORGED, calls, events)


def test_grandchild_relay_to_the_root_gate_is_refused() -> None:
    calls: list = []
    events: list = []
    gate = _gate(calls, events)
    child = _frame(gate, {"type": "child", "argv": ["tool"]})["watch_id"]
    events.clear()
    start = {
        "type": "event",
        "kind": "start",
        "watch_id": FORGED,
        "parent_watch_id": child,
        "pid": GRAND,
    }
    assert _frame(gate, _relay(child, start), peer=GRAND) == {"ok": False, "error": ERR_PEER}
    call = _relay(child, _call(FORGED))
    assert _frame(gate, call, peer=GRAND)["ok"] is False
    assert _frame(gate, call)["ok"] is False
    _nothing_under(FORGED, calls, events)


def test_an_unannounced_origin_cannot_open_with_a_non_start_event() -> None:
    calls: list = []
    events: list = []
    gate = _gate(calls, events)
    child = _frame(gate, {"type": "child", "argv": ["tool"]})["watch_id"]
    events.clear()
    for kind in ("exit", "sample"):
        bye = {
            "type": "event",
            "kind": kind,
            "watch_id": FORGED,
            "parent_watch_id": child,
            "pid": GRAND,
        }
        assert _frame(gate, _relay(child, bye)) == {"ok": False, "error": ERR_REFUSED}
    assert _frame(gate, _relay(child, _call(FORGED))) == {"ok": False, "error": ERR_REFUSED}
    _nothing_under(FORGED, calls, events)


def test_a_start_relayed_by_the_child_gate_still_opens_its_run() -> None:
    calls: list = []
    events: list = []
    gate = _gate(calls, events)
    child = _frame(gate, {"type": "child", "argv": ["tool"]})["watch_id"]
    start = {
        "type": "event",
        "kind": "start",
        "watch_id": "tw-grand",
        "parent_watch_id": child,
        "pid": GRAND,
    }
    assert _frame(gate, _relay(child, start)) == {"ok": True}
    assert _frame(gate, _relay(child, _call("tw-grand")))["ok"] is True
    assert calls == [{"verb": "todo", "args": {"need": "spoofed"}, "watch_id": "tw-grand"}]
    deeper = dict(start, watch_id="tw-deeper", parent_watch_id="tw-grand")
    assert _frame(gate, _relay(child, deeper)) == {"ok": True}
    stray = dict(start, watch_id="tw-stray", parent_watch_id="tw-nowhere")
    assert _frame(gate, _relay(child, stray)) == {"ok": False, "error": ERR_REFUSED}


FORGER = r"""
import json, os, subprocess, sys
from agent_coord.client.tw.run_ipc import call_parent, lookup_parent

FORGED = "tw-forged-origin"


def forge(child):
    p = lookup_parent()
    start = {"type": "event", "kind": "start", "watch_id": FORGED,
             "parent_watch_id": child, "pid": os.getpid()}
    call = {"type": "call", "verb": "todo", "args": {"need": "spoofed"}, "watch_id": FORGED}
    out = {}
    for name, inner in (("start", start), ("call", call)):
        try:
            out[name] = call_parent(p, {"type": "relay", "watch_id": child, "frame": inner})
        except Exception as exc:
            out[name] = {"ok": False, "error": str(exc)}
    return out


if sys.argv[1] == "grand":
    print(json.dumps(forge(sys.argv[2])))
    raise SystemExit(0)
p = lookup_parent()
child = call_parent(p, {"type": "child", "argv": ["forger"]})["watch_id"]
out = {"child": child, "direct": forge(child)}
grand = subprocess.run([sys.executable, __file__, "grand", child],
                       capture_output=True, text=True, timeout=60)
out["grand"] = json.loads(grand.stdout or "{}")
print(json.dumps(out))
"""


@UNIX
def test_real_processes_cannot_forge_a_start(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))
    env = os.environ.copy()
    env["AGENT_COORD_MILL_HOME"] = str(tmp_path)
    src = str(Path(run_ipc.__file__).resolve().parents[3])
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    script = tmp_path / "forger.py"
    script.write_text(FORGER, encoding="utf-8")
    calls: list = []
    events: list = []

    def call_fn(verb, args, wid):
        calls.append({"verb": verb, "args": dict(args), "watch_id": wid})
        return {"ok": True, "result": {"verb": verb}, "sync": []}

    def event_fn(body):
        events.append(dict(body))
        return True

    gate = RunGate("desk-a", "tw-root", call_fn, event_fn)
    gate.open()
    try:
        done = subprocess.run(
            [sys.executable, str(script), "direct"],
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
    finally:
        gate.close()
    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout)
    for who in ("direct", "grand"):
        assert out[who]["start"]["ok"] is False, json.dumps(out)
        assert out[who]["call"]["ok"] is False, json.dumps(out)
    _nothing_under(FORGED, calls, events)
