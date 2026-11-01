# -*- coding: utf-8 -*-
"""hint.dispatch is one mill-perf line on every dispatch_hint return."""
import json

from agent_coord.client.dispatch import dispatch_hint
from agent_coord.client.route_chain import save_routes


def _lines(tmp_path):
    path = tmp_path / "mill-perf.log"
    if not path.is_file():
        return []
    return path.read_text(encoding="utf-8").splitlines()


def _op(line: str) -> dict:
    out = {}
    for part in line.split():
        if part.startswith("op=") or part.startswith("decision=") or part.startswith("key="):
            k, v = part.split("=", 1)
            out[k] = v
        elif part.startswith("idem=") or part.startswith("vendor="):
            k, v = part.split("=", 1)
            out[k] = v
    return out


def test_ping_stamps_skip(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)
    assert dispatch_hint("builder", {"type": "heartbeat", "id": 0, "hint": "PING"}) == "skip"
    ops = [_op(line) for line in _lines(tmp_path)]
    assert ops[-1]["op"] == "hint.dispatch"
    assert ops[-1]["decision"] == "skip"
    assert "ms=" not in _lines(tmp_path)[-1]


def test_route_stamps_work_and_does_not_poke(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)
    monkeypatch.setenv("AGENT_COORD_VENDOR", "freeze-sentinel")
    monkeypatch.setattr(
        "agent_coord.client.connectors.poke",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("wake")),
    )

    class FakeProc:
        returncode = 0

        def communicate(self, data=None, timeout=None):
            return b"handled\n", b""

    monkeypatch.setattr(
        "agent_coord.client.route_chain.subprocess.Popen",
        lambda argv, **kw: FakeProc(),
    )
    save_routes("builder", {"todo:TODO": "python -c pass"})
    kind = dispatch_hint(
        "builder",
        {"type": "todo", "id": 9, "hint": "TODO", "idem": "freeze-a7"},
    )
    assert kind == "work"
    op = _op(_lines(tmp_path)[-1])
    assert op["decision"] == "work"
    assert op["key"] == "todo:TODO"
    assert op["idem"] == "freeze-a7"
    assert op["vendor"] == "freeze-sentinel"


def test_wake_stamps_vendor_before_poke(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)
    monkeypatch.setenv("AGENT_COORD_VENDOR", "freeze-stub")
    seen = {}

    def fake_poke(vendor, hint):
        seen["vendor"] = vendor
        seen["stamped"] = "op=hint.dispatch" in "\n".join(_lines(tmp_path))
        return True

    monkeypatch.setattr("agent_coord.client.connectors.poke", fake_poke)
    kind = dispatch_hint(
        "builder",
        {"type": "todo", "id": 3, "hint": "TODO", "idem": "freeze-a1"},
    )
    assert kind == "wake"
    assert seen["vendor"] == "freeze-stub"
    assert seen["stamped"] is True
    op = _op(_lines(tmp_path)[-1])
    assert op["decision"] == "wake"
    assert op["vendor"] == "freeze-stub"
    assert json.dumps(op)
