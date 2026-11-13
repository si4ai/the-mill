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
