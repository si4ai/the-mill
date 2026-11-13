# -*- coding: utf-8 -*-
"""Tree window #58: ?window=1d|1w|30d on tree-mail/todo; omit=All; invalid=400."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent_coord.lib.observe import parse_roots
from agent_coord.server.asgi import make_asgi_app
from agent_coord.server.records.floor import (
    filter_trees_by_window,
    parse_tree_window,
    v1_tree_mail,
)


def test_parse_tree_window_omit_all_and_tokens() -> None:
    now = datetime(2026, 9, 27, 14, 0, 0)
    assert parse_tree_window({}) is None
    assert parse_tree_window({"window": [""]}) is None
    assert parse_tree_window(window=None) is None
    assert parse_tree_window(window="") is None
    assert parse_tree_window({"window": ["1d"]}, now=now) == now - timedelta(days=1)
    assert parse_tree_window({"window": ["1w"]}, now=now) == now - timedelta(days=7)
    assert parse_tree_window({"window": ["7d"]}, now=now) == now - timedelta(days=7)  # card 1193
    assert parse_tree_window({"window": ["30d"]}, now=now) == now - timedelta(days=30)
    assert parse_tree_window(window="1D", now=now) == now - timedelta(days=1)


def test_parse_tree_window_invalid_raises() -> None:
    with pytest.raises(ValueError, match="invalid window"):
        parse_tree_window({"window": ["2d"]})
    with pytest.raises(ValueError, match="1d\\|7d\\|30d"):
        parse_tree_window(window="24h")


def test_filter_trees_by_window_keeps_recent_forests() -> None:
    now = datetime(2026, 9, 27, 14, 0, 0)
    trees = [
        {"name": "TREE_new", "hidden": False, "nodes": [{"type": "mail", "id": 1}]},
        {"name": "TREE_old", "hidden": False, "nodes": [{"type": "mail", "id": 2}]},
        {"name": "TREE_none", "hidden": False, "nodes": [{"type": "mail", "id": 3}]},
    ]
    last = {
        "TREE_new": now - timedelta(hours=2),
        "TREE_old": now - timedelta(days=10),
    }
    since = now - timedelta(days=1)
    kept = filter_trees_by_window(trees, since, last)
    assert [t["name"] for t in kept] == ["TREE_new"]
    assert filter_trees_by_window(trees, None, last) == trees


def test_v1_tree_mail_window_1d_filters_old_keeps_progressive(monkeypatch) -> None:
    now = datetime(2026, 9, 27, 14, 0, 0)
    forest = [
        {
            "name": "TREE_fresh",
            "hidden": False,
            "nodes": [
                {
                    "type": "mail",
                    "id": 1,
                    "lft": 1,
                    "rgt": 4,
                    "depth": 0,
                    "title": "r",
                    "status": "",
                    "who": "",
                    "roster_id": "demo",
                    "has_children": True,
                },
                {
                    "type": "mail",
                    "id": 2,
                    "lft": 2,
                    "rgt": 3,
                    "depth": 1,
                    "title": "c",
                    "status": "",
                    "who": "",
                    "roster_id": "demo",
                    "has_children": False,
                },
            ],
        },
        {
            "name": "TREE_stale",
            "hidden": False,
            "nodes": [
                {
                    "type": "mail",
                    "id": 10,
                    "lft": 1,
                    "rgt": 2,
                    "depth": 0,
                    "title": "old",
                    "status": "",
                    "who": "",
                    "roster_id": "demo",
                    "has_children": False,
                },
            ],
        },
    ]
    monkeypatch.setattr(
        "agent_coord.server.records.floor.build_trees_typed",
        lambda cn, want, typ, aff: forest,
    )
    monkeypatch.setattr(
        "agent_coord.server.records.floor._v1_project_scope",
        lambda project=None, projects=None: (["PROJ_demo"], {"demo"}),
    )
    monkeypatch.setattr(
        "agent_coord.server.records.floor._v1_aff_ids",
        lambda cn, want: None,
    )
    monkeypatch.setattr(
        "agent_coord.server.records.tree.forest_last_activity",
        lambda cn, aff: {
            "TREE_fresh": now - timedelta(hours=3),
            "TREE_stale": now - timedelta(days=5),
        },
    )
    # freeze parse cutoff via window= + now injected through parse_tree_window patch
    real_parse = parse_tree_window

    def _parse(*, window=None, qs=None, now=None):
        return real_parse(qs=qs, window=window, now=now or now)

    # Call with window=1d; monkeypatch datetime.now used inside parse via now= by
    # wrapping parse_tree_window in floor module.
    monkeypatch.setattr(
        "agent_coord.server.records.floor.parse_tree_window",
        lambda qs=None, window=None, now=None: real_parse(
            qs=qs, window=window, now=now or datetime(2026, 9, 27, 14, 0, 0)
        ),
    )
    out = v1_tree_mail(object(), project="demo", window="1d", limit=50, depth=1)
    names = [t["name"] for t in out["trees"]]
    assert names == ["TREE_fresh"]
    ids = [n["id"] for t in out["trees"] for n in t["nodes"]]
    assert ids == [1, 2]  # progressive depth<=1 still OK
    assert "next" in out
    # omit window = All
    out_all = v1_tree_mail(object(), project="demo", limit=50, depth=1)
    assert [t["name"] for t in out_all["trees"]] == ["TREE_fresh", "TREE_stale"]


def _client(monkeypatch) -> TestClient:
    monkeypatch.setattr("agent_coord.server.admin.door.mode", lambda: "path")
    monkeypatch.setattr("agent_coord.server.allow.allowed", lambda *a, **k: True)
    root = Path(__file__).resolve().parents[2]
    app = make_asgi_app(parse_roots(cwd=root), api_only=True)
    return TestClient(app)


def test_middleware_invalid_window_400(monkeypatch) -> None:
    monkeypatch.setattr(
        "agent_coord.server.records.floor.v1_tree_mail",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not build")),
    )

    class _C:
        _cn = object()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr("agent_coord.server.middleware._office", lambda: _C())
    client = _client(monkeypatch)
    r = client.get("/api/v1/tree-mail?project=demo&window=2d")
    assert r.status_code == 400
    assert "window" in r.json()["error"].lower()


def test_middleware_passes_window_kwarg(monkeypatch) -> None:
    seen: dict = {}

    def _mail(cn, **k):
        seen.clear()
        seen.update(k)
        return {
            "at": "t",
            "node": "n",
            "version": "0.5.8",
            "parts": ["trees"],
            "trees": [],
            "next": None,
            "mill": "0.5.8",
        }

    monkeypatch.setattr("agent_coord.server.records.floor.v1_tree_mail", _mail)

    class _C:
        _cn = object()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr("agent_coord.server.middleware._office", lambda: _C())
    client = _client(monkeypatch)
    r = client.get("/api/v1/tree-mail?project=demo&window=1w&limit=10&depth=1")
    assert r.status_code == 200
    assert seen["window"] == "1w"
    assert seen["limit"] == 10
    assert seen["depth"] == 1
    assert "next" in r.json()
