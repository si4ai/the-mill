# -*- coding: utf-8 -*-
"""Lean list ?limit= + ?cursor= paging for v1 mailbox/todos/agents/scores/holds/watchers/events/names."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from agent_coord.lib.observe import parse_roots
from agent_coord.server.asgi import make_asgi_app
from agent_coord.server.records.floor import (
    LIST_PAGE_DEFAULT,
    page_by_cursor,
    parse_list_page,
    v1_agents,
    v1_mailbox,
    v1_holds,
    v1_scores,
    v1_todos,
    v1_watchers,
    v1_events,
    v1_names,
)


def test_parse_list_page_defaults() -> None:
    lim, cur = parse_list_page({})
    assert lim == LIST_PAGE_DEFAULT and cur is None
    lim2, cur2 = parse_list_page({"limit": ["10"], "cursor": ["99"]})
    assert lim2 == 10 and cur2 == "99"
    lim3, _ = parse_list_page({"limit": ["9999"]})
    assert lim3 == 500
    lim4, _ = parse_list_page({"limit": ["0"]})
    assert lim4 == 1
    lim5, _ = parse_list_page({"limit": ["nope"]})
    assert lim5 == LIST_PAGE_DEFAULT


def test_page_by_cursor_next() -> None:
    rows = [{"id": i, "body": "x"} for i in (10, 9, 8, 7, 6)]
    p1, n1 = page_by_cursor(rows, 2, None)
    assert [r["id"] for r in p1] == [10, 9] and n1 == "9"
    p2, n2 = page_by_cursor(rows, 2, n1)
    assert [r["id"] for r in p2] == [8, 7] and n2 == "7"
    p3, n3 = page_by_cursor(rows, 2, n2)
    assert [r["id"] for r in p3] == [6] and n3 is None
    empty, n0 = page_by_cursor(rows, 2, "missing")
    assert empty == [] and n0 is None


def test_v1_mailbox_pages(monkeypatch) -> None:
    letters = [
        {
            "id": i,
            "created": "2026-01-01",
            "desk": "DESK_a",
            "body": "B" * 300,
            "mail_tos": [{"deskId": "DESK_b"}],
        }
        for i in range(5, 0, -1)
    ]

    def _build(cn, mail_ps, want=None):
        return letters, {"DESK_b": 5}

    monkeypatch.setattr("agent_coord.server.records.floor.build_mailbox", _build)
    monkeypatch.setattr("agent_coord.server.records.floor._projects_part_fp", lambda *a, **k: "aabbccddeeff0011")
    monkeypatch.setattr(
        "agent_coord.server.records.floor._v1_project_scope",
        lambda project=None, projects=None: (["PROJ_demo"], {"demo"}),
    )
    out = v1_mailbox(object(), project="demo", limit=2)
    assert len(out["mailbox"]) == 2
    assert out["mailbox"][0]["id"] == 5
    assert out["next"] == "4"
    assert out["desk_unread"]["DESK_b"] == 5
    out2 = v1_mailbox(object(), project="demo", limit=2, cursor=out["next"])
    assert [m["id"] for m in out2["mailbox"]] == [3, 2]
    assert out2["next"] == "2"
    out3 = v1_mailbox(object(), project="demo", limit=2, cursor=out2["next"])
    assert [m["id"] for m in out3["mailbox"]] == [1]
    assert out3["next"] is None


def test_v1_todos_pages_needs_then_issues(monkeypatch) -> None:
    needs = [{"id": i, "status": "open", "doing": "d", "detail": "x"} for i in (11, 10, 9)]
    issues = [{"id": i, "status": "parked", "doing": "d", "detail": "x", "kind": "next"} for i in (8, 7)]

    monkeypatch.setattr(
        "agent_coord.server.records.floor.build_todos",
        lambda cn, mail_ps, want=None, lean=True, **k: (needs, issues),
    )
    monkeypatch.setattr("agent_coord.server.records.floor._projects_part_fp", lambda *a, **k: "ffeeddccbbaa0011")
    monkeypatch.setattr(
        "agent_coord.server.records.floor._v1_project_scope",
        lambda project=None, projects=None: (["PROJ_demo"], {"demo"}),
    )
    out = v1_todos(object(), project="demo", limit=2)
    assert [c["id"] for c in out["needs"]] == [11, 10]
    assert out["issues"] == []
    assert out["next"] == "10"
    out2 = v1_todos(object(), project="demo", limit=2, cursor="10")
    assert [c["id"] for c in out2["needs"]] == [9]
    assert [c["id"] for c in out2["issues"]] == [8]
    assert out2["next"] == "8"
    out3 = v1_todos(object(), project="demo", limit=2, cursor="8")
    assert out3["needs"] == []
    assert [c["id"] for c in out3["issues"]] == [7]
    assert out3["next"] is None


def test_v1_agents_pages(monkeypatch) -> None:
    rows = [{"id": f"d{i}", "owner": f"d{i}"} for i in range(1, 6)]

    monkeypatch.setattr(
        "agent_coord.server.records.floor.build_agents",
        lambda cn, mail_ps, want=None, **k: list(rows),
    )
    monkeypatch.setattr("agent_coord.server.records.floor._projects_part_fp", lambda *a, **k: "0011223344556677")
    monkeypatch.setattr(
        "agent_coord.server.records.floor._v1_project_scope",
        lambda project=None, projects=None: (["PROJ_demo"], {"demo"}),
    )
    out = v1_agents(object(), project="demo", limit=2)
    assert [a["id"] for a in out["agents"]] == ["d1", "d2"]
    assert out["next"] == "d2"
    out2 = v1_agents(object(), project="demo", limit=2, cursor=out["next"])
    assert [a["id"] for a in out2["agents"]] == ["d3", "d4"]
    assert out2["next"] == "d4"
    out3 = v1_agents(object(), project="demo", limit=2, cursor=out2["next"])
    assert [a["id"] for a in out3["agents"]] == ["d5"]
    assert out3["next"] is None




def test_v1_scores_pages(monkeypatch) -> None:
    rows = [{"id": f"o{i}|k|a", "owner": f"o{i}", "kpi": "k", "roster_id": "a"} for i in range(1, 6)]

    monkeypatch.setattr(
        "agent_coord.server.records.floor.build_scores",
        lambda cn, mail_ps, want=None, **k: list(rows),
    )
    monkeypatch.setattr("agent_coord.server.records.floor._projects_part_fp", lambda *a, **k: "7788990011223344")
    monkeypatch.setattr(
        "agent_coord.server.records.floor._v1_project_scope",
        lambda project=None, projects=None: (["PROJ_demo"], {"demo"}),
    )
    out = v1_scores(object(), project="demo", limit=2)
    assert [r["id"] for r in out["kpis"]] == ["o1|k|a", "o2|k|a"]
    assert out["next"] == "o2|k|a"
    out2 = v1_scores(object(), project="demo", limit=2, cursor=out["next"])
    assert [r["id"] for r in out2["kpis"]] == ["o3|k|a", "o4|k|a"]
    assert out2["next"] == "o4|k|a"
    out3 = v1_scores(object(), project="demo", limit=2, cursor=out2["next"])
    assert [r["id"] for r in out3["kpis"]] == ["o5|k|a"]
    assert out3["next"] is None



def test_v1_holds_pages(monkeypatch) -> None:
    rows = [{"id": f"r{i}|o|a", "resource": f"r{i}", "owner": "o", "roster_id": "a"} for i in range(1, 6)]

    monkeypatch.setattr(
        "agent_coord.server.records.floor.build_holds",
        lambda cn, mail_ps, want=None, **k: list(rows),
    )
    monkeypatch.setattr("agent_coord.server.records.floor._projects_part_fp", lambda *a, **k: "99aabbccddeeff00")
    monkeypatch.setattr(
        "agent_coord.server.records.floor._v1_project_scope",
        lambda project=None, projects=None: (["PROJ_demo"], {"demo"}),
    )
    out = v1_holds(object(), project="demo", limit=2)
    assert [r["id"] for r in out["locks"]] == ["r1|o|a", "r2|o|a"]
    assert out["next"] == "r2|o|a"
    out2 = v1_holds(object(), project="demo", limit=2, cursor=out["next"])
    assert [r["id"] for r in out2["locks"]] == ["r3|o|a", "r4|o|a"]
    assert out2["next"] == "r4|o|a"
    out3 = v1_holds(object(), project="demo", limit=2, cursor=out2["next"])
    assert [r["id"] for r in out3["locks"]] == ["r5|o|a"]
    assert out3["next"] is None


def test_v1_watchers_pages(monkeypatch) -> None:
    rows = [{"type": "todo", "id": i, "title": f"t{i}"} for i in range(1, 6)]

    monkeypatch.setattr(
        "agent_coord.server.records.floor.build_watchers",
        lambda cn, mail_ps, want=None, **k: list(rows),
    )
    monkeypatch.setattr("agent_coord.server.records.floor._projects_part_fp", lambda *a, **k: "aabb99ccddeeff00")
    monkeypatch.setattr(
        "agent_coord.server.records.floor._v1_project_scope",
        lambda project=None, projects=None: (["PROJ_demo"], {"demo"}),
    )
    out = v1_watchers(object(), project="demo", limit=2)
    assert [f"{r['type']}:{r['id']}" for r in out["watchers"]] == ["todo:1", "todo:2"]
    assert out["next"] == "todo:2"
    out2 = v1_watchers(object(), project="demo", limit=2, cursor=out["next"])
    assert [f"{r['type']}:{r['id']}" for r in out2["watchers"]] == ["todo:3", "todo:4"]
    assert out2["next"] == "todo:4"
    out3 = v1_watchers(object(), project="demo", limit=2, cursor=out2["next"])
    assert [f"{r['type']}:{r['id']}" for r in out3["watchers"]] == ["todo:5"]
    assert out3["next"] is None


def test_v1_events_pages(monkeypatch) -> None:
    rows = [{"type": "todo", "id": i, "kind": "todo"} for i in range(1, 6)]

    monkeypatch.setattr(
        "agent_coord.server.records.floor.build_events",
        lambda cn, mail_ps, want=None, **k: list(rows),
    )
    monkeypatch.setattr("agent_coord.server.records.floor._projects_part_fp", lambda *a, **k: "ccddeeff00112233")
    monkeypatch.setattr(
        "agent_coord.server.records.floor._v1_project_scope",
        lambda project=None, projects=None: (["PROJ_demo"], {"demo"}),
    )
    out = v1_events(object(), project="demo", limit=2)
    assert [f"{r['type']}:{r['id']}" for r in out["events"]] == ["todo:1", "todo:2"]
    assert out["next"] == "todo:2"
    out2 = v1_events(object(), project="demo", limit=2, cursor=out["next"])
    assert [f"{r['type']}:{r['id']}" for r in out2["events"]] == ["todo:3", "todo:4"]
    assert out2["next"] == "todo:4"
    out3 = v1_events(object(), project="demo", limit=2, cursor=out2["next"])
    assert [f"{r['type']}:{r['id']}" for r in out3["events"]] == ["todo:5"]
    assert out3["next"] is None


def test_v1_names_pages(monkeypatch) -> None:
    rows = [
        {"kind": "project", "name": f"p{i}", "deleted": False}
        for i in range(1, 6)
    ]

    monkeypatch.setattr(
        "agent_coord.server.records.floor.build_names",
        lambda cn, mail_ps, want=None, **k: list(rows),
    )
    monkeypatch.setattr("agent_coord.server.records.floor._projects_part_fp", lambda *a, **k: "ddeeff0011223344")
    monkeypatch.setattr(
        "agent_coord.server.records.floor._v1_project_scope",
        lambda project=None, projects=None: (["PROJ_demo"], {"demo"}),
    )
    out = v1_names(object(), project="demo", limit=2)
    assert [f"{r['kind']}:{r['name']}" for r in out["catalog"]] == ["project:p1", "project:p2"]
    assert out["next"] == "project:p2"
    out2 = v1_names(object(), project="demo", limit=2, cursor=out["next"])
    assert [f"{r['kind']}:{r['name']}" for r in out2["catalog"]] == ["project:p3", "project:p4"]
    assert out2["next"] == "project:p4"
    out3 = v1_names(object(), project="demo", limit=2, cursor=out2["next"])
    assert [f"{r['kind']}:{r['name']}" for r in out3["catalog"]] == ["project:p5"]
    assert out3["next"] is None

def test_v1_routes_honor_limit_cursor(monkeypatch) -> None:
    monkeypatch.setattr("agent_coord.server.admin.door.mode", lambda: "path")
    monkeypatch.setattr("agent_coord.server.allow.allowed", lambda *a, **k: True)

    class _C:
        _cn = object()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr("agent_coord.server.middleware._office", lambda: _C())

    seen: dict[str, dict] = {}

    def _mailbox(cn, **k):
        seen["mailbox"] = k
        return {
            "at": "t",
            "node": "n",
            "version": "0.5.6",
            "parts": ["mail"],
            "mailbox": [{"id": 1}],
            "desk_unread": {},
            "next": None,
            "fp": {"mail": "a" * 16},
        }

    def _todos(cn, **k):
        seen["todos"] = k
        return {
            "at": "t",
            "node": "n",
            "version": "0.5.6",
            "parts": ["todos"],
            "needs": [],
            "issues": [],
            "next": None,
            "fp": {"todos": "b" * 16},
        }

    def _agents(cn, **k):
        seen["agents"] = k
        return {
            "at": "t",
            "node": "n",
            "version": "0.5.6",
            "parts": ["agents"],
            "agents": [],
            "next": None,
            "fp": {"agents": "c" * 16},
        }

    def _scores(cn, **k):
        seen["scores"] = k
        return {
            "at": "t",
            "node": "n",
            "version": "0.5.6",
            "parts": ["scores"],
            "kpis": [],
            "next": None,
            "fp": {"scores": "d" * 16},
        }

    def _holds(cn, **k):
        seen["holds"] = k
        return {
            "at": "t",
            "node": "n",
            "version": "0.5.6",
            "parts": ["holds"],
            "locks": [],
            "next": None,
            "fp": {"holds": "e" * 16},
        }

    def _watchers(cn, **k):
        seen["watchers"] = k
        return {
            "at": "t",
            "node": "n",
            "version": "0.5.6",
            "parts": ["watchers"],
            "watchers": [],
            "next": None,
            "fp": {"watchers": "f" * 16},
        }

    def _events(cn, **k):
        seen["events"] = k
        return {
            "at": "t",
            "node": "n",
            "version": "0.5.6",
            "parts": ["events"],
            "events": [],
            "next": None,
            "fp": {"events": "a" * 16},
        }

    def _names(cn, **k):
        seen["names"] = k
        return {
            "at": "t",
            "node": "n",
            "version": "0.5.6",
            "parts": ["names"],
            "catalog": [],
            "next": None,
            "fp": {"names": "b" * 16},
        }

    monkeypatch.setattr("agent_coord.server.records.floor.v1_mailbox", _mailbox)
    monkeypatch.setattr("agent_coord.server.records.floor.v1_todos", _todos)
    monkeypatch.setattr("agent_coord.server.records.floor.v1_agents", _agents)
    monkeypatch.setattr("agent_coord.server.records.floor.v1_scores", _scores)
    monkeypatch.setattr("agent_coord.server.records.floor.v1_holds", _holds)
    monkeypatch.setattr("agent_coord.server.records.floor.v1_watchers", _watchers)
    monkeypatch.setattr("agent_coord.server.records.floor.v1_events", _events)
    monkeypatch.setattr("agent_coord.server.records.floor.v1_names", _names)
    root = Path(__file__).resolve().parents[2]
    client = TestClient(make_asgi_app(parse_roots(cwd=root), api_only=True))
    r = client.get("/api/v1/mailbox?project=demo&limit=3&cursor=9")
    assert r.status_code == 200
    assert r.json()["next"] is None
    assert seen["mailbox"]["limit"] == 3
    assert seen["mailbox"]["cursor"] == "9"
    r2 = client.get("/api/v1/todos?project=demo&limit=7")
    assert r2.status_code == 200
    assert seen["todos"]["limit"] == 7
    assert seen["todos"]["cursor"] is None
    r3 = client.get("/api/v1/agents?project=demo&limit=4&cursor=d2")
    assert r3.status_code == 200
    assert seen["agents"]["limit"] == 4
    assert seen["agents"]["cursor"] == "d2"
    r4 = client.get("/api/v1/scores?project=demo&limit=5&cursor=o2|k|a")
    assert r4.status_code == 200
    assert seen["scores"]["limit"] == 5
    assert seen["scores"]["cursor"] == "o2|k|a"
    r5 = client.get("/api/v1/holds?project=demo&limit=6&cursor=r2|o|a")
    assert r5.status_code == 200
    assert seen["holds"]["limit"] == 6
    assert seen["holds"]["cursor"] == "r2|o|a"
    r6 = client.get("/api/v1/watchers?project=demo&limit=8&cursor=todo:2")
    assert r6.status_code == 200
    assert seen["watchers"]["limit"] == 8
    assert seen["watchers"]["cursor"] == "todo:2"
    r7 = client.get("/api/v1/events?project=demo&limit=9&cursor=todo:3")
    assert r7.status_code == 200
    assert seen["events"]["limit"] == 9
    assert seen["events"]["cursor"] == "todo:3"
    r8 = client.get("/api/v1/names?project=demo&limit=4&cursor=project:p2")
    assert r8.status_code == 200
    assert seen["names"]["limit"] == 4
    assert seen["names"]["cursor"] == "project:p2"
