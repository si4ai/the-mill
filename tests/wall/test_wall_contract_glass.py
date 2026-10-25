# -*- coding: utf-8 -*-
"""Wall contract glass rules with no test yet (validator review, mail 2294).

Each test runs the real boot.js function in node with stubbed neighbours and
asserts what the glass sends:
- rule-lean-rows glass (692): opening a truncated mail/todo GETs its detail route.
- rule-rooms-trust glass (695): limited trust sends desk=+scope=membership, high omits desk.
- rule-trees glass (698): expand sends parent_id=type:id, and the window chips are All/1d/1w/30d.
"""
from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from agent_coord.web.wall_logic.packs import wall_ui_root

from ._wall_src import wall_fn

BOOT = wall_ui_root() / "default" / "boot.js"


def _fn(name: str) -> str:
    """The real function, in boot.js or the pane module it was split into (#872)."""
    return wall_fn(name)


def _const(name: str) -> str:
    src = BOOT.read_text(encoding="utf-8")
    head = src.index("    const " + name + " =")
    return src[head: src.index("\n", head) + 1]


def _node(script: str):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def test_692_open_truncated_row_gets_detail_route():
    script = (
        "const window = {_floor: {}}; const calls = [];\n"
        "let rows = {};\n"
        "function wallFindMailRow(id) { return rows['m' + id] || null; }\n"
        "function wallFindTodoRow(id) { return rows['t' + id] || null; }\n"
        "function wallMergeMailDetail(x) { return !!x; }\n"
        "function wallMergeTodoDetail(x) { return !!x; }\n"
        "function mail() {} function board() {} function paintPlan() {}\n"
        "async function fetch(url) { calls.push(url); return {ok: true, json: async () => ({mail: {id: 1}, todo: {id: 1}})}; }\n"
        + _fn("wallMailIsTrunc") + _fn("wallTodoIsTrunc")
        + "const _wallLeanDetailInflight = Object.create(null);\n"
        + _fn("wallOpenMailIfTrunc") + _fn("wallOpenTodoIfTrunc")
        + "(async () => {\n"
        "  rows = {m7: {id: 7, body_trunc: true}, m8: {id: 8, body_trunc: false},"
        " t9: {id: 9, detail_trunc: true}, t10: {id: 10}};\n"
        "  const out = {};\n"
        "  out.m7 = await wallOpenMailIfTrunc(7); out.m8 = await wallOpenMailIfTrunc(8);\n"
        "  out.t9 = await wallOpenTodoIfTrunc(9); out.t10 = await wallOpenTodoIfTrunc(10);\n"
        "  out.calls = calls; console.log(JSON.stringify(out));\n"
        "})();\n"
    )
    out = _node(script)
    assert out["calls"] == ["/api/v1/mail/7", "/api/v1/todo/9"]
    assert out["m7"] is True and out["t9"] is True
    assert out["m8"] is False and out["t10"] is False


def test_695_rooms_query_follows_trust():
    script = (
        "let trust = 'high', desk = 'wall-ui';\n"
        "function wallTrust() { return trust; }\n"
        "function wallResolveDeskId() { return desk; }\n"
        + _fn("wallRoomsMembershipQuery")
        + "const out = {};\n"
        "for (const t of ['high', 'limited', '']) { trust = t; out[t || 'unknown'] = wallRoomsMembershipQuery(); }\n"
        "trust = 'limited'; desk = ''; out.limited_no_desk = wallRoomsMembershipQuery();\n"
        "console.log(JSON.stringify(out));\n"
    )
    out = _node(script)
    assert out["high"] == ""
    assert out["limited"] == "&desk=wall-ui&scope=membership"
    assert out["unknown"] == "&desk=wall-ui"
    assert out["limited_no_desk"] == ""


def test_698_tree_expand_sends_parent_id_and_window():
    script = (
        "const store = {}; const localStorage = {getItem: k => store[k] || null, setItem: (k, v) => { store[k] = v; }};\n"
        "const calls = [];\n"
        "function floorScope() { return {query: 'roster=Office'}; }\n"
        "function wallActiveTreeKind() { return 'tree-mail'; }\n"
        "function wallAppendTreesPage() { return true; }\n"
        "function wallPaintTreesKind() {}\n"
        "async function fetch(url) { calls.push(url); return {ok: true,"
        " headers: {get: () => 'application/json'}, json: async () => ({next: null})}; }\n"
        "const _wallTreeExpandNext = {}; const _wallTreeExpandInflight = {};\n"
        + _const("TREES_WINDOW_KEY") + _const("TREES_WINDOW_OK")
        + _fn("loadTreesWindow") + _fn("saveTreesWindow")
        + _fn("wallTreesWindowEffective") + _fn("wallTreesWindowQuery")
        + _fn("wallFetchTreeExpand")
        + "(async () => {\n"
        "  await wallFetchTreeExpand('mail', 2290);\n"
        "  saveTreesWindow('1w'); await wallFetchTreeExpand('todo', 680, {kind: 'tree-todo'});\n"
        "  saveTreesWindow('bogus'); const fallback = loadTreesWindow();\n"
        "  console.log(JSON.stringify({calls, chips: Object.keys(TREES_WINDOW_OK).sort(), fallback}));\n"
        "})();\n"
    )
    out = _node(script)
    first, second = out["calls"]
    assert first.startswith("/api/v1/tree-mail?roster=Office&")
    assert "parent_id=mail%3A2290" in first and "window=" not in first
    assert second.startswith("/api/v1/tree-todo?")
    assert "parent_id=todo%3A680" in second and "&window=1w" in second
    assert out["chips"] == ["1d", "1w", "30d", "all"]
    assert out["fallback"] == "all"
