# -*- coding: utf-8 -*-
"""Join workstation address is the LAN IP, never loopback."""
from agent_coord.server.allow import workstation_ip


def test_remote_peer_kept() -> None:
    assert workstation_ip("203.0.113.30") == "203.0.113.30"
    assert workstation_ip("198.51.100.50") == "198.51.100.50"


def test_loopback_uses_host_lan(monkeypatch) -> None:
    class Sock:
        def connect(self, addr):
            self.addr = addr

        def getsockname(self):
            return ("198.51.100.50", 0)

        def close(self):
            pass

    made: dict[str, Sock] = {}

    def factory(*_a, **_k):
        sock = Sock()
        made["sock"] = sock
        return sock

    monkeypatch.setattr("socket.socket", factory)
    assert workstation_ip("127.0.0.1") == "198.51.100.50"
    assert made["sock"].addr == ("192.0.2.1", 9)
    assert workstation_ip("::1") == "198.51.100.50"
    assert workstation_ip("") == "198.51.100.50"


def test_loopback_host_stays_empty(monkeypatch) -> None:
    class Sock:
        def connect(self, addr):
            pass

        def getsockname(self):
            return ("127.0.0.1", 0)

        def close(self):
            pass

    monkeypatch.setattr("socket.socket", lambda *a, **k: Sock())
    assert workstation_ip("localhost") == ""


def test_set_lan_ip_skips_blank() -> None:
    from agent_coord.server.records.join import set_lan_ip

    class Boom:
        def cursor(self):
            raise AssertionError("blank address must not touch the book")

    set_lan_ip(Boom(), "DESK_builder", "")
    set_lan_ip(Boom(), "", "198.51.100.5")


def test_join_saves_lan_ip_other_commands_do_not(monkeypatch) -> None:
    from pathlib import Path

    from fastapi.testclient import TestClient

    from agent_coord.lib.observe import parse_roots
    from agent_coord.server.asgi import make_asgi_app

    saved: list[tuple[str, str]] = []

    class Book:
        _cn = object()

    class Office:
        def __enter__(self):
            return Book()

        def __exit__(self, *a):
            return False

    def fake_dispatch(c, data, token="", client_mill=""):
        if data.get("verb") == "join":
            return {"owner": "DESK_builder", "token": "minted"}
        return {"ok": True}

    monkeypatch.setattr("agent_coord.server.api.mill.rpc.dispatch", fake_dispatch)
    monkeypatch.setattr(
        "agent_coord.server.records.join.set_lan_ip",
        lambda cn, desk, ip: saved.append((desk, ip)),
    )
    monkeypatch.setattr("agent_coord.server.allow.workstation_ip", lambda peer: "192.0.2.44")
    monkeypatch.setattr("agent_coord.server.admin.door.mode", lambda: "path")
    monkeypatch.setattr("agent_coord.server.allow.allowed", lambda *a, **k: True)
    monkeypatch.setattr("agent_coord.server.middleware._office", lambda: Office())

    root = Path(__file__).resolve().parents[2]
    app = make_asgi_app(parse_roots(cwd=root), api_only=True)
    client = TestClient(app)
    joined = client.post("/api/mill/join", json={"verb": "join", "project": "the-mill", "owner": "builder"})
    assert joined.status_code == 200
    assert joined.json()["owner"] == "DESK_builder"
    other = client.post("/api/mill/inbox", json={"verb": "inbox", "owner": "builder"})
    assert other.status_code == 200
    assert saved == [("DESK_builder", "192.0.2.44")]
