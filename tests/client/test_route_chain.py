# -*- coding: utf-8 -*-
"""Per-desk chain: order, marks, exit line, vendor only after next."""
from agent_coord.client.dispatch import dispatch_hint
from agent_coord.client.route_chain import bind_exit, save_routes
from agent_coord.client.wake_post import accept_wake


def test_star_where_added_runs_before_a_later_specific(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)
    calls: list[str] = []

    def run(cmd, msg):
        calls.append(cmd)
        return ("next", 0) if cmd.startswith("star") else ("handled", 0)

    monkeypatch.setattr("agent_coord.client.route_chain.run_program", run)
    monkeypatch.setattr(
        "agent_coord.client.connectors.poke",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("wake")),
    )
    save_routes("builder", [("*", "star"), ("mail:MAIL", "mail")])
    assert dispatch_hint("builder", {"kind": "mail", "id": 4}) == "work"
    assert calls == ["star", "mail"]


def test_handled_stops_before_the_next_redirector(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)
    calls: list[str] = []

    def run(cmd, msg):
        calls.append(cmd)
        return "handled", 0

    monkeypatch.setattr("agent_coord.client.route_chain.run_program", run)
    monkeypatch.setattr(
        "agent_coord.client.connectors.poke",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("wake")),
    )
    save_routes("builder", [("*", "star"), ("todo:TODO", "todo")])
    assert dispatch_hint("builder", {"type": "todo", "hint": "TODO", "id": 1}) == "work"
    assert calls == ["star"]


def test_nonzero_writes_exit_and_continues(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)
    calls: list[str] = []
    exits: list[dict] = []

    def run(cmd, msg):
        calls.append(cmd)
        if cmd == "bad":
            return "fail", 3
        return "handled", 0

    monkeypatch.setattr("agent_coord.client.route_chain.run_program", run)
    monkeypatch.setattr(
        "agent_coord.client.connectors.poke",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("wake")),
    )
    save_routes("builder", [("todo:TODO", "bad"), ("*", "star")])
    with bind_exit(exits.append):
        assert dispatch_hint("builder", {"type": "todo", "hint": "TODO", "id": 8}) == "work"
    assert calls == ["bad", "star"]
    assert exits == [{"exit": 1, "frame": {"route": "todo:TODO", "id": 8, "exit": 3}}]


def test_failed_chain_does_not_wake(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)
    exits: list[dict] = []
    monkeypatch.setattr("agent_coord.client.route_chain.run_program", lambda cmd, msg: ("fail", 2))
    monkeypatch.setattr(
        "agent_coord.client.connectors.poke",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("wake")),
    )
    save_routes("builder", [("todo:TODO", "bad"), ("*", "star")])
    with bind_exit(exits.append):
        assert dispatch_hint("builder", {"type": "todo", "hint": "TODO", "id": 6}) == "work"
    assert [row["frame"]["route"] for row in exits] == ["todo:TODO", "*"]


def test_all_next_wakes_vendor(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)
    monkeypatch.setenv("AGENT_COORD_VENDOR", "grok-build")
    woke: list[str] = []
    monkeypatch.setattr("agent_coord.client.route_chain.run_program", lambda cmd, msg: ("next", 0))
    monkeypatch.setattr(
        "agent_coord.client.connectors.poke",
        lambda vendor, frame: woke.append(vendor),
    )
    save_routes("builder", [("todo:TODO", "todo"), ("*", "star")])
    assert dispatch_hint("builder", {"type": "todo", "hint": "TODO", "id": 2}) == "wake"
    assert woke == ["grok-build"]


def test_doing_with_no_route_stays_skip(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)
    monkeypatch.setattr(
        "agent_coord.client.connectors.poke",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("wake")),
    )
    assert dispatch_hint("builder", {"type": "doing", "hint": "DOING", "id": 1}) == "skip"


def test_other_desk_chain_is_not_used(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)
    monkeypatch.setenv("AGENT_COORD_VENDOR", "grok-build")
    ran: list[str] = []
    woke: list[str] = []
    monkeypatch.setattr(
        "agent_coord.client.route_chain.run_program",
        lambda cmd, msg: ran.append(cmd) or ("handled", 0),
    )
    monkeypatch.setattr(
        "agent_coord.client.connectors.poke",
        lambda vendor, frame: woke.append(str(frame.get("desk") or "")),
    )
    save_routes("builder", [("*", "builder-only")])
    assert dispatch_hint("grok-tui", {"type": "todo", "hint": "TODO", "id": 5}) == "wake"
    assert ran == []
    assert woke == ["grok-tui"]


def test_duplicate_key_does_not_enter_the_chain(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)
    from agent_coord.client import dispatch

    dispatch._SEEN.clear()
    calls: list[int] = []
    monkeypatch.setattr(
        "agent_coord.client.route_chain.run_program",
        lambda cmd, msg: calls.append(1) or ("handled", 0),
    )
    save_routes("builder", [("*", "star")])
    frame = {"type": "todo", "hint": "TODO", "id": 9, "idem": "hint:todo:9:builder"}
    assert dispatch_hint("builder", frame) == "work"
    assert dispatch_hint("builder", frame) == "skip"
    assert calls == [1]


def test_wake_post_uses_the_same_chain(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(
        "agent_coord.client.route_chain.run_program",
        lambda cmd, msg: calls.append(cmd) or ("handled", 0),
    )
    monkeypatch.setattr(
        "agent_coord.client.connectors.poke",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("wake")),
    )
    save_routes("away", [("todo:TODO", "todo")])
    assert accept_wake({"type": "todo", "hint": "TODO", "id": 3, "desk": "away"}) == "work"
    assert calls == ["todo"]
    assert accept_wake({"type": "todo", "hint": "TODO", "id": 3}) == "skip"
