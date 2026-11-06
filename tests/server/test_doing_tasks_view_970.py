"""Card 970: connected exposes only live, private task summaries."""
from types import SimpleNamespace

import pytest

from agent_coord.server.api.mill import rpc
from agent_coord.server.records import doing


def view(monkeypatch, tasks, **focus):
    monkeypatch.setattr(doing, "now", lambda *a: [
        {"part": "desk", "desk": "Builder", **focus},
        *[{"part": "task", "desk": "Builder", **t} for t in tasks],
        {"part": "desk", "desk": "Validator"},
    ])
    return rpc._h_session(SimpleNamespace(_cn=None), {"all": True}, "", None)


def test_task_fields_and_focus_are_independent(monkeypatch):
    tasks = [
        {"state": "active", "join_key": "task:Builder:a"},
        {"state": "waiting", "join_key": "task:Builder:b", "cause": "quiet", "card_id": 970},
        {"state": "idle"},
    ]
    got = view(monkeypatch, tasks, text="reviewing", act="focus", age_s=42, on_type="todo", on_id=970)
    assert got[0]["tasks"] == [
        {"state": "active", "join_key": "task:Builder:a"},
        {"state": "waiting", "join_key": "task:Builder:b", "waiting_on": "quiet", "card": "todo-970"},
        {"state": "idle"},
    ]
    assert (got[0]["doing"], got[0]["act"], got[0]["on"]) == ("reviewing", "focus", "todo-970")
    assert got[1]["tasks"] == []
    assert got[1]["doing"] == ""


@pytest.mark.parametrize("state", ["finished", "failed", "stale", "cleared"])
def test_terminal_rows_never_reach_the_view(monkeypatch, state):
    assert view(monkeypatch, [{"state": state, "join_key": "task:Builder:a"}])[0]["tasks"] == []


def test_task_cap_is_eight(monkeypatch):
    got = view(monkeypatch, [{"state": "active", "join_key": f"task:Builder:w{i}"} for i in range(12)])
    assert len(got[0]["tasks"]) == doing.TASK_CAP == 8


@pytest.mark.parametrize("state,cause", [("waiting", "quiet"), ("waiting", "secret.*pattern"), ("active", "quiet")])
def test_task_projection_never_leaks_private_fields(monkeypatch, state, cause):
    private = {key: "SECRET" for key in ("title", "argv", "pattern", "stdout", "stderr", "log", "sample", "pid")}
    got = view(monkeypatch, [{"state": state, "join_key": "task:Builder:a", "cause": cause, **private}])[0]["tasks"][0]
    expected = {"state": state, "join_key": "task:Builder:a"}
    if state == "waiting" and cause == "quiet":
        expected["waiting_on"] = "quiet"
    assert got == expected


def test_now_attaches_one_batched_task_read(monkeypatch):
    desks = [{"part": "desk", "desk": role} for role in ("Builder", "Validator")]
    task = {"part": "task", "desk": "Builder", "state": "active"}
    monkeypatch.setattr(doing, "call", lambda *a: list(desks))
    calls = []

    def read(cn, names):
        calls.append(names)
        return [task]

    monkeypatch.setattr(doing, "task_rows", read, raising=False)
    assert doing.now(None, all_desks=True) == [*desks, task]
    assert calls == [["Builder", "Validator"]]
