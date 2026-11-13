"""TODO tab views: Kanban / List toggle, a Jira-style List, and Tree as an outline.

Runs todo/todo.js, rd-model.js and rd-view.js in Node and checks what a reader
sees: list rows sort and filter as asked, a column shows only when the payload
serves its field, a tree reads as an indented outline that folds, and TODO opens
on Kanban when wide and List when narrow unless the reader picked a view.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

DEFAULT = Path(__file__).resolve().parents[2] / "agent_coord" / "web" / "wall_ui" / "default"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")

# The /api/v1/todos card shape (records/floor.py build_todos): no age or eta stamp.
CARDS = [
    {"id": 7, "need_id": "7", "status": "claimed", "detail": "Stations route", "assigned": "builder", "creator": "validator"},
    {"id": 12, "need_id": "12", "status": "open", "detail": "Review labels", "assigned": "", "creator": "gardener"},
    {"id": 3, "need_id": "3", "status": "done", "detail": "Old work", "assigned": "gardener", "creator": "builder"},
    {"id": 9, "need_id": "9", "status": "parked", "detail": "Later", "assigned": "", "creator": ""},
    {"id": 15, "need_id": "15", "status": "shipped", "detail": "Wall list", "assigned": "builder", "creator": "validator"},
]
# A nested-set tree: 1 > (2 > 4), 3; 5 is a root with children not loaded yet.
NODES = [
    {"type": "todo", "id": 1, "lft": 1, "rgt": 8},
    {"type": "todo", "id": 2, "lft": 2, "rgt": 5},
    {"type": "todo", "id": 4, "lft": 3, "rgt": 4},
    {"type": "todo", "id": 3, "lft": 6, "rgt": 7},
    {"type": "todo", "id": 5, "lft": 9, "rgt": 10, "has_children": True},
]

SCRIPT = r"""
const dir = process.argv[1];
require(dir + '/todo/todo.js');
require(dir + '/rd/rd-model.js');
require(dir + '/rd/rd-view.js');
const T = WallTodo, R = WallRd, V = WallRdView;
const cards = JSON.parse(process.argv[2]), nodes = JSON.parse(process.argv[3]);
const rows = cards.map(T.todoListRow);
const ids = list => list.map(r => r.id);
const lines = (opt) => T.todoOutline(nodes, opt).map(L => [L.id, L.depth, L.kids, !!L.more, !!L.collapsed]);
console.log(JSON.stringify({
  row: rows[0],
  cols: T.todoListCols(rows).map(c => c.key),
  colsEta: T.todoListCols(cards.concat([{id: 20, status: 'open', eta: '2026-11-14T10:00:00Z'}]).map(T.todoListRow)).map(c => c.key),
  byDefault: ids(T.todoListView(rows, {})),
  byIdAsc: ids(T.todoListView(rows, {col: 'id', dir: 'asc'})),
  byIdDesc: ids(T.todoListView(rows, {col: 'id', dir: 'desc'})),
  byClaimant: ids(T.todoListView(rows, {col: 'claimant', dir: 'asc'})),
  byClaimantDesc: ids(T.todoListView(rows, {col: 'claimant', dir: 'desc'})),
  desk: ids(T.todoListView(rows, {desk: 'validator', col: 'id', dir: 'asc'})),
  deskState: ids(T.todoListView(rows, {desk: 'builder', state: 'claimed'})),
  choices: T.todoListChoices(rows),
  outline: lines({}),
  folded: lines({collapsed: {'2': 1}}),
  kept: lines({keep: {'1': 1, '3': 1}}),
  views: [R.todoView('', true), R.todoView('', false), R.todoView('list', true), R.todoView('nest', false), R.todoView('all', true)],
  order: {
    merged: T.todoColOrder(['asker', 'id', 'title'], ['id', 'title', 'state', 'claimant', 'asker']),
    gone: T.todoColOrder(['eta', 'title', 'id', 'state', 'claimant', 'asker'], ['id', 'title', 'state', 'claimant', 'asker']),
    back: T.todoColOrder(['eta', 'title', 'id', 'state', 'claimant', 'asker'], ['id', 'title', 'state', 'claimant', 'asker', 'eta']),
    fresh: T.todoColOrder(['title', 'id', 'state', 'claimant', 'asker'], ['id', 'title', 'state', 'claimant', 'asker', 'eta']),
    none: T.todoColOrder(null, ['id', 'title', 'state']),
    junk: T.todoColOrder(['nope', 'title', 'title'], ['id', 'title']),
    left: T.todoColMove(['id', 'title', 'state'], 'state', -1),
    clampL: T.todoColMove(['id', 'title', 'state'], 'id', -1),
    clampR: T.todoColMove(['id', 'title', 'state'], 'state', 5),
    drop: T.todoColDrop(['id', 'title', 'state', 'claimant'], 'claimant', 'title'),
    dropR: T.todoColDrop(['id', 'title', 'state', 'claimant'], 'id', 'state'),
    cols: T.todoListCols(rows, ['asker', 'title']).map(c => c.key),
    defaults: T.todoListDefaults(),
  },
  head: V.hostHead('todo', {scope: {label: 'Office'}}, [{key: 'board', label: 'Kanban'}, {key: 'list', label: 'List'}, {key: 'nest', label: 'Tree', alone: true}], 'list'),
}));
"""


def run() -> dict:
    out = subprocess.run([NODE, "-e", SCRIPT, "--", str(DEFAULT), json.dumps(CARDS), json.dumps(NODES)],
                         capture_output=True, text=True, check=True, timeout=30)
    return json.loads(out.stdout)


def test_list_row_reads_the_served_card():
    row = run()["row"]
    assert row == {"id": "7", "title": "Stations route", "state": "claimed", "claimant": "builder",
                   "asker": "validator", "eta": ""}


def test_list_shows_only_served_columns():
    got = run()
    assert got["cols"] == ["id", "title", "state", "claimant", "asker"], "no eta served, so no ETA column"
    assert got["colsEta"][-1] == "eta"
    assert "age" not in got["cols"] + got["colsEta"], "age in state is not served yet (card 1194)"
    src = (DEFAULT / "todo" / "todo.js").read_text(encoding="utf-8")
    assert "TODO(card 1194)" in src


def test_list_sorts_by_any_column_blank_last():
    got = run()
    assert got["byDefault"] == ["9", "12", "7", "15", "3"], "default: workflow order parked..done"
    assert got["byIdAsc"] == ["3", "7", "9", "12", "15"]
    assert got["byIdDesc"] == ["15", "12", "9", "7", "3"]
    # Ties fall back to the newest card; cards nobody claimed sort last either way.
    assert got["byClaimant"] == ["15", "7", "3", "12", "9"]
    assert got["byClaimantDesc"] == ["3", "15", "7", "12", "9"]


def test_list_filters_by_desk_and_state():
    got = run()
    assert got["desk"] == ["7", "15"], "a desk filter matches the claimant or the asker"
    assert got["deskState"] == ["7"]
    assert got["choices"] == {"desks": ["builder", "gardener", "validator"],
                              "states": ["parked", "open", "claimed", "shipped", "done"]}


def test_tree_outline_indents_and_folds():
    got = run()
    # [id, depth, direct kids, more not loaded, folded]
    assert got["outline"] == [["1", 0, 2, False, False], ["2", 1, 1, False, False], ["4", 2, 0, False, False],
                              ["3", 1, 0, False, False], ["5", 0, 0, True, False]]
    assert got["folded"] == [["1", 0, 2, False, False], ["2", 1, 1, False, True],
                             ["3", 1, 0, False, False], ["5", 0, 0, True, False]]
    assert got["kept"] == [["1", 0, 1, False, False], ["3", 1, 0, False, False]]


def test_todo_opens_on_kanban_wide_and_list_narrow_unless_picked():
    assert run()["views"] == ["board", "list", "list", "nest", "board"]


def test_tree_is_its_own_button_beside_the_kanban_list_toggle():
    head = run()["head"]
    group, _, rest = head.partition('<span class="rd-view-switch rd-view-alone">')
    assert 'role="group"' in group and 'data-rd-view="board"' in group and 'data-rd-view="list"' in group
    assert 'data-rd-view="nest"' not in group
    assert 'data-rd-view="nest"' in rest
    assert 'data-rd-view="list" class="on" aria-pressed="true"' in head
    assert head.count('aria-pressed="false"') == 2


def test_column_order_merges_with_served_columns():
    o = run()["order"]
    assert o["merged"] == ["asker", "id", "title", "state", "claimant"]
    # A saved column not served today drops out, and comes back in its saved place.
    assert o["gone"] == ["title", "id", "state", "claimant", "asker"]
    assert o["back"] == ["eta", "title", "id", "state", "claimant", "asker"]
    # A column the saved order never had sits after its default neighbour.
    assert o["fresh"] == ["title", "id", "state", "claimant", "asker", "eta"]
    assert o["none"] == ["id", "title", "state"]
    assert o["junk"] == ["id", "title"] or o["junk"] == ["title", "id"]
    # id leads the default order, so a saved order without it gets it first.
    assert o["cols"] == ["id", "asker", "title", "state", "claimant"]


def test_column_moves_by_key_and_by_drop():
    o = run()["order"]
    assert o["left"] == ["id", "state", "title"]
    assert o["clampL"] == ["id", "title", "state"]
    assert o["clampR"] == ["id", "title", "state"]
    assert o["drop"] == ["id", "claimant", "title", "state"]
    assert o["dropR"] == ["title", "state", "id", "claimant"]


def test_reset_restores_defaults_and_text_fit_is_the_shared_control():
    assert run()["order"]["defaults"] == {"col": "state", "dir": "asc", "desk": "", "state": "", "order": []}
    boot = (DEFAULT / "boot.js").read_text(encoding="utf-8")
    start = boot.index("    function wallTodoListPaint() {")
    paint = boot[start:boot.index("\n    function wireTodoList() {", start)]
    # No list-only wrap toggle: text fit is the Wall's TEXT control (Overflow | Wrap | Clip), as on MAIL.
    assert "data-todo-density" not in boot and "Truncate" not in paint
    assert 'data-todo-reset="1"' in paint and 'draggable="true"' in paint
    assert 'aria-keyshortcuts="Alt+ArrowLeft Alt+ArrowRight"' in paint
    assert 'window.applyTextMode("wrap", "jobs")' in boot
    # Alt+Arrow on a heading moves the column and must beat lib/keys.js's document-capture
    # pane switch, so it listens on window in the capture phase and stops the stroke.
    wire = boot.split("function wireTodoList()", 1)[1].split("/* nest time window", 1)[0]
    alt = wire.split("Keyboard path for column order", 1)[1].split("/* Drag a heading", 1)[0]
    assert 'window.addEventListener("keydown"' in alt and "ev.stopPropagation()" in alt and "}, true);" in alt
    css = (DEFAULT / "todo" / "todo.css").read_text(encoding="utf-8")
    for mode in ("overflow", "wrap", "clip"):
        assert f'#pane-todo[data-todo-text="{mode}"] .todo-jira td' in css
    assert "table-layout: fixed" in css and "width: max-content" not in css
